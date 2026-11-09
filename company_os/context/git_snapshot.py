"""Read-only Python dependency snapshots from historical Git revisions.

Only regular tracked Python blobs are materialized, inside a temporary
directory. Repository files, branches, index, and working tree are untouched.
"""

from __future__ import annotations

import fnmatch
import subprocess
import tempfile

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .dependency_mapper import DependencyReport, map_python_dependencies
from .repository_scanner import RepositorySnapshot, ScanPolicy, scan_repository

GIT_SNAPSHOT_SCHEMA_VERSION = "1.0"
DEFAULT_MAX_TOTAL_PYTHON_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_PYTHON_FILES = 10_000
DEFAULT_GIT_TIMEOUT_SECONDS = 60.0


class GitRevisionSnapshotError(ValueError):
    """Raised when a historical Git snapshot cannot be read safely."""


@dataclass(frozen=True)
class _GitBlob:
    path: str
    object_id: str
    size: int


@dataclass(frozen=True)
class GitRevisionDependencySnapshot:
    """Dependency graph and metadata from one immutable Git commit."""

    commit: str
    snapshot: RepositorySnapshot
    dependencies: DependencyReport
    skipped_paths: tuple[str, ...]

    @property
    def indexed_paths(self) -> frozenset[str]:
        return frozenset(
            record.path
            for record in self.snapshot.files
            if record.language == "python" and record.path.endswith(".py")
        )

    def to_dict(self) -> dict:
        return {
            "schema_version": GIT_SNAPSHOT_SCHEMA_VERSION,
            "commit": self.commit,
            "snapshot_sha256": self.snapshot.snapshot_sha256,
            "python_files_indexed": len(self.indexed_paths),
            "python_files_analyzed": self.dependencies.files_analyzed,
            "dependency_edge_count": len(self.dependencies.edges),
            "parse_issue_count": len(self.dependencies.parse_issues),
            "scan_warning_count": len(self.snapshot.warnings),
            "dependency_warning_count": len(self.dependencies.warnings),
            "skipped_paths": list(self.skipped_paths),
        }


def _run_git(
    root: Path,
    arguments: list[str],
    *,
    input_bytes: bytes | None = None,
    timeout: float,
) -> bytes:
    """Run Git with an argument list; never invoke a shell."""

    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=root,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise GitRevisionSnapshotError(
            "Git executable was not found on PATH."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise GitRevisionSnapshotError(
            f"Historical Git operation exceeded {timeout:g} seconds."
        ) from exc
    except OSError as exc:
        raise GitRevisionSnapshotError(
            f"Unable to read historical Git data: {exc}"
        ) from exc

    if result.returncode != 0:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        if len(error) > 600:
            error = error[:600] + "..."

        raise GitRevisionSnapshotError(
            f"Git historical operation failed: "
            f"{error or 'no error details returned'}"
        )

    return result.stdout


def _resolve_commit(root: Path, revision: str, timeout: float) -> str:
    if not isinstance(revision, str) or not revision.strip():
        raise ValueError("revision must be a non-empty Git reference.")

    if any(ord(character) < 32 for character in revision):
        raise ValueError("revision cannot contain control characters.")

    output = _run_git(
        root,
        [
            "rev-parse",
            "--verify",
            "--quiet",
            "--end-of-options",
            f"{revision.strip()}^{{commit}}",
        ],
        timeout=timeout,
    )

    try:
        commit = output.decode("ascii").strip().lower()
    except UnicodeDecodeError as exc:
        raise GitRevisionSnapshotError(
            "Git returned an invalid commit identifier."
        ) from exc

    if len(commit) not in {40, 64} or any(
        character not in "0123456789abcdef"
        for character in commit
    ):
        raise GitRevisionSnapshotError(
            "Git returned an invalid commit identifier."
        )

    return commit


def _safe_relative_path(raw_path: bytes) -> str:
    try:
        value = raw_path.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GitRevisionSnapshotError(
            "Historical tree contains a non-UTF-8 path. "
            "The snapshot was stopped to avoid path corruption."
        ) from exc

    if not value or value.startswith("/") or "\\" in value:
        raise GitRevisionSnapshotError(
            f"Unsafe historical repository path: {value!r}"
        )

    parts = value.split("/")

    if any(part in {"", ".", ".."} for part in parts):
        raise GitRevisionSnapshotError(
            f"Unsafe historical repository path: {value!r}"
        )

    return PurePosixPath(value).as_posix()


def _is_excluded(path: str, policy: ScanPolicy) -> bool:
    parts = PurePosixPath(path).parts

    if not policy.include_hidden_files and any(
        part.startswith(".") for part in parts
    ):
        return True

    if any(
        part.casefold() in policy.excluded_dirs
        for part in parts[:-1]
    ):
        return True

    filename = parts[-1].casefold()

    if filename != ".env.example" and any(
        fnmatch.fnmatchcase(filename, pattern)
        for pattern in policy.excluded_patterns
    ):
        return True

    return False


def _list_python_blobs(
    root: Path,
    commit: str,
    policy: ScanPolicy,
    *,
    max_total_python_bytes: int,
    max_python_files: int,
    timeout: float,
) -> tuple[tuple[_GitBlob, ...], tuple[str, ...]]:
    """List bounded, regular Python blobs from a committed tree."""

    if ".py" not in policy.extensions:
        return (), ()

    tree = _run_git(
        root,
        [
            "ls-tree",
            "-r",
            "-l",
            "-z",
            "--full-tree",
            commit,
        ],
        timeout=timeout,
    )

    blobs: list[_GitBlob] = []
    skipped: set[str] = set()
    total_bytes = 0

    for entry in tree.split(b"\0"):
        if not entry:
            continue

        try:
            metadata, raw_path = entry.split(b"\t", 1)
            fields = metadata.decode("ascii").split()
        except (ValueError, UnicodeDecodeError) as exc:
            raise GitRevisionSnapshotError(
                "Git returned a malformed historical tree record."
            ) from exc

        if len(fields) != 4:
            raise GitRevisionSnapshotError(
                "Git historical tree record has an unexpected format."
            )

        mode, object_type, object_id, size_text = fields

        try:
            path = _safe_relative_path(raw_path)
        except GitRevisionSnapshotError:
            # Non-Python paths are irrelevant to this Python-only snapshot.
            try:
                candidate = raw_path.decode("utf-8")
            except UnicodeDecodeError:
                raise
            if candidate.endswith(".py"):
                raise
            continue

        if not path.endswith(".py"):
            continue

        # Symlinks and submodules are deliberately never followed.
        if mode not in {"100644", "100755"} or object_type != "blob":
            skipped.add(path)
            continue

        if _is_excluded(path, policy):
            skipped.add(path)
            continue

        if len(object_id) not in {40, 64} or any(
            character not in "0123456789abcdefABCDEF"
            for character in object_id
        ):
            raise GitRevisionSnapshotError(
                f"Git returned an invalid blob identifier for {path!r}."
            )

        try:
            size = int(size_text)
        except ValueError as exc:
            raise GitRevisionSnapshotError(
                f"Git returned an invalid blob size for {path!r}."
            ) from exc

        if size < 0:
            raise GitRevisionSnapshotError(
                f"Git returned a negative blob size for {path!r}."
            )

        if size > policy.max_file_bytes:
            skipped.add(path)
            continue

        if len(blobs) >= max_python_files:
            raise GitRevisionSnapshotError(
                f"Historical snapshot exceeds the limit of "
                f"{max_python_files} Python files."
            )

        total_bytes += size

        if total_bytes > max_total_python_bytes:
            raise GitRevisionSnapshotError(
                "Historical Python snapshot exceeds the total byte limit "
                f"of {max_total_python_bytes} bytes."
            )

        blobs.append(
            _GitBlob(
                path=path,
                object_id=object_id.lower(),
                size=size,
            )
        )

    return tuple(blobs), tuple(sorted(skipped))


def _read_blob_batch(
    root: Path,
    blobs: tuple[_GitBlob, ...],
    timeout: float,
) -> tuple[bytes, ...]:
    """Read selected blobs in one bounded cat-file batch operation."""

    if not blobs:
        return ()

    request = b"".join(
        blob.object_id.encode("ascii") + b"\n"
        for blob in blobs
    )

    output = _run_git(
        root,
        ["cat-file", "--batch"],
        input_bytes=request,
        timeout=timeout,
    )

    contents: list[bytes] = []
    cursor = 0

    for expected in blobs:
        header_end = output.find(b"\n", cursor)

        if header_end < 0:
            raise GitRevisionSnapshotError(
                "Git returned an incomplete cat-file object header."
            )

        try:
            object_id, object_type, size_text = (
                output[cursor:header_end].decode("ascii").split()
            )
            actual_size = int(size_text)
        except (ValueError, UnicodeDecodeError) as exc:
            raise GitRevisionSnapshotError(
                "Git returned a malformed cat-file object header."
            ) from exc

        if object_id.lower() != expected.object_id:
            raise GitRevisionSnapshotError(
                "Git returned blobs in an unexpected order."
            )

        if object_type != "blob" or actual_size != expected.size:
            raise GitRevisionSnapshotError(
                f"Historical blob metadata changed for {expected.path!r}."
            )

        body_start = header_end + 1
        body_end = body_start + actual_size

        if body_end >= len(output) or output[body_end:body_end + 1] != b"\n":
            raise GitRevisionSnapshotError(
                f"Git returned truncated data for {expected.path!r}."
            )

        contents.append(output[body_start:body_end])
        cursor = body_end + 1

    if cursor != len(output):
        raise GitRevisionSnapshotError(
            "Git returned unexpected trailing data from cat-file."
        )

    return tuple(contents)


def load_git_revision_dependencies(
    root: str | Path,
    revision: str,
    policy: ScanPolicy | None = None,
    *,
    max_total_python_bytes: int = DEFAULT_MAX_TOTAL_PYTHON_BYTES,
    max_python_files: int = DEFAULT_MAX_PYTHON_FILES,
    timeout: float = DEFAULT_GIT_TIMEOUT_SECONDS,
) -> GitRevisionDependencySnapshot:
    """Build a static Python dependency graph from an immutable Git commit.

    Historical content is written only to a disposable temporary directory.
    The caller receives metadata and dependency edges, never source contents.
    """

    if max_total_python_bytes < 1:
        raise ValueError("max_total_python_bytes must be greater than zero.")

    if max_python_files < 1:
        raise ValueError("max_python_files must be greater than zero.")

    if timeout <= 0:
        raise ValueError("timeout must be greater than zero.")

    repository_root = Path(root).expanduser().resolve()

    if not repository_root.exists() or not repository_root.is_dir():
        raise GitRevisionSnapshotError(
            f"Repository root is not a directory: {repository_root}"
        )

    top_level = _run_git(
        repository_root,
        ["rev-parse", "--show-toplevel"],
        timeout=timeout,
    )

    try:
        git_root = Path(top_level.decode("utf-8").strip()).resolve()
    except UnicodeDecodeError as exc:
        raise GitRevisionSnapshotError(
            "Git returned an invalid repository root."
        ) from exc

    if git_root != repository_root:
        raise GitRevisionSnapshotError(
            "The supplied root must be the Git repository top-level "
            f"directory. Git root: {git_root}; supplied root: "
            f"{repository_root}."
        )

    selected_policy = policy or ScanPolicy()
    commit = _resolve_commit(
        repository_root,
        revision,
        timeout,
    )

    blobs, skipped = _list_python_blobs(
        repository_root,
        commit,
        selected_policy,
        max_total_python_bytes=max_total_python_bytes,
        max_python_files=max_python_files,
        timeout=timeout,
    )

    contents = _read_blob_batch(
        repository_root,
        blobs,
        timeout,
    )

    with tempfile.TemporaryDirectory(
        prefix="company-os-git-snapshot-"
    ) as temporary_directory:
        temporary_root = Path(temporary_directory).resolve()

        for blob, content in zip(blobs, contents, strict=True):
            target = temporary_root.joinpath(
                *PurePosixPath(blob.path).parts
            )

            target.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            try:
                target.resolve().relative_to(temporary_root)
            except ValueError as exc:
                raise GitRevisionSnapshotError(
                    f"Historical path escaped the temporary root: "
                    f"{blob.path!r}"
                ) from exc

            target.write_bytes(content)

        snapshot = scan_repository(
            temporary_root,
            selected_policy,
        )

        dependencies = map_python_dependencies(
            temporary_root,
            snapshot,
        )

    indexed_paths = {
        record.path
        for record in snapshot.files
        if record.language == "python" and record.path.endswith(".py")
    }

    not_indexed = {
        blob.path
        for blob in blobs
        if blob.path not in indexed_paths
    }

    not_indexed.update(
        warning.path
        for warning in snapshot.warnings
        if warning.path.endswith(".py")
    )

    not_indexed.update(skipped)

    return GitRevisionDependencySnapshot(
        commit=commit,
        snapshot=snapshot,
        dependencies=dependencies,
        skipped_paths=tuple(sorted(not_indexed)),
    )
