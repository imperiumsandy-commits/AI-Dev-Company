"""Git-based repository change detection.

Compares two committed Git states and reports added, modified, deleted,
renamed, copied and other file changes.

This module does not modify the repository, switch branches, create commits,
or execute repository source code.
"""

from __future__ import annotations

import subprocess

from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Sequence

GIT_CHANGE_SCHEMA_VERSION = "1.0"
DEFAULT_GIT_TIMEOUT_SECONDS = 30.0

_STATUS_LABELS = {
    "A": "added",
    "M": "modified",
    "D": "deleted",
    "R": "renamed",
    "C": "copied",
    "T": "type_changed",
    "U": "unmerged",
    "X": "unknown",
    "B": "broken_pairing",
}

_IMPACT_CANDIDATE_STATUSES = frozenset({"A", "M", "R", "C", "T"})


class GitChangeError(ValueError):
    """Raised when Git change detection cannot be performed safely."""


@dataclass(frozen=True)
class GitChange:
    """One file-level change reported by Git."""

    status: str
    path: str
    previous_path: str | None = None
    similarity: int | None = None

    @property
    def status_label(self) -> str:
        return _STATUS_LABELS[self.status]

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "status_label": self.status_label,
        }


@dataclass(frozen=True)
class GitChangeReport:
    """Immutable result of comparing two committed repository states."""

    schema_version: str
    base_ref: str
    head_ref: str
    base_commit: str
    head_commit: str
    merge_base: str
    changes: tuple[GitChange, ...]

    @property
    def change_count(self) -> int:
        return len(self.changes)

    @property
    def status_counts(self) -> dict[str, int]:
        counts = {
            label: 0
            for label in _STATUS_LABELS.values()
        }

        for change in self.changes:
            counts[change.status_label] += 1

        return counts

    @property
    def impact_candidate_paths(self) -> tuple[str, ...]:
        """Current paths that may be analyzed against the current snapshot."""

        return tuple(
            sorted({
                change.path
                for change in self.changes
                if change.status in _IMPACT_CANDIDATE_STATUSES
            })
        )

    @property
    def removed_paths(self) -> tuple[str, ...]:
        """Paths removed from the target tree, including rename sources."""

        removed: set[str] = set()

        for change in self.changes:
            if change.status == "D":
                removed.add(change.path)
            elif change.status == "R" and change.previous_path:
                removed.add(change.previous_path)

        return tuple(sorted(removed))

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "base_ref": self.base_ref,
            "head_ref": self.head_ref,
            "base_commit": self.base_commit,
            "head_commit": self.head_commit,
            "merge_base": self.merge_base,
            "change_count": self.change_count,
            "status_counts": self.status_counts,
            "impact_candidate_paths": list(self.impact_candidate_paths),
            "removed_paths": list(self.removed_paths),
            "changes": [
                change.to_dict()
                for change in self.changes
            ],
        }


def _decode_git_text(value: bytes, description: str) -> str:
    """Decode Git output strictly to avoid corrupting repository paths."""

    try:
        return value.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise GitChangeError(
            f"Git returned non-UTF-8 data for {description}; "
            "the operation was stopped rather than corrupting file paths."
        ) from exc


def _run_git(
    root: Path,
    arguments: Sequence[str],
    timeout: float,
) -> bytes:
    """Execute Git without a shell and return stdout bytes."""

    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise GitChangeError(
            "Git executable was not found. Install Git and make it available "
            "on PATH."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise GitChangeError(
            f"Git command exceeded the {timeout:g}-second timeout."
        ) from exc
    except OSError as exc:
        raise GitChangeError(
            f"Unable to execute Git safely: {exc}"
        ) from exc

    if result.returncode != 0:
        error = result.stderr.decode(
            "utf-8",
            errors="replace",
        ).strip()

        if len(error) > 600:
            error = error[:600] + "..."

        raise GitChangeError(
            f"Git command failed with exit code {result.returncode}: "
            f"{error or 'no error details returned'}"
        )

    return result.stdout


def _validate_ref(ref: str, label: str) -> str:
    if not isinstance(ref, str):
        raise TypeError(f"{label} must be a string.")

    normalized = ref.strip()

    if not normalized:
        raise ValueError(f"{label} cannot be empty.")

    if any(ord(character) < 32 for character in normalized):
        raise ValueError(f"{label} cannot contain control characters.")

    return normalized


def _resolve_commit(
    root: Path,
    ref: str,
    label: str,
    timeout: float,
) -> str:
    """Resolve a user-supplied ref to a commit object ID."""

    normalized_ref = _validate_ref(ref, label)

    output = _run_git(
        root,
        [
            "rev-parse",
            "--verify",
            "--quiet",
            "--end-of-options",
            f"{normalized_ref}^{{commit}}",
        ],
        timeout,
    )

    commit_id = _decode_git_text(
        output,
        f"{label} commit reference",
    )

    if not commit_id or any(
        character not in "0123456789abcdefABCDEF"
        for character in commit_id
    ):
        raise GitChangeError(
            f"Git returned an invalid commit ID for {label}."
        )

    return commit_id.lower()


def _normalize_git_path(raw_path: bytes) -> str:
    """Convert a Git path into a safe repository-relative POSIX path."""

    try:
        value = raw_path.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GitChangeError(
            "A changed Git path is not valid UTF-8. "
            "The report was stopped to avoid path corruption."
        ) from exc

    if not value or value.startswith("/"):
        raise GitChangeError(
            f"Git returned an invalid repository-relative path: {value!r}"
        )

    parts = value.split("/")

    if any(part in {"", ".", ".."} for part in parts):
        raise GitChangeError(
            f"Git returned an unsafe repository-relative path: {value!r}"
        )

    return PurePosixPath(value).as_posix()


def _parse_name_status(raw: bytes) -> tuple[GitChange, ...]:
    """Parse Git's NUL-delimited --name-status output.

    NUL delimiting is essential because valid filenames may contain spaces,
    tabs, quotes, or newline characters.
    """

    if not raw:
        return ()

    fields = raw.split(b"\0")

    if fields and fields[-1] == b"":
        fields.pop()

    changes: list[GitChange] = []
    index = 0

    while index < len(fields):
        status_token = fields[index]
        index += 1

        try:
            status_text = status_token.decode("ascii")
        except UnicodeDecodeError as exc:
            raise GitChangeError(
                "Git returned an invalid file status token."
            ) from exc

        if not status_text:
            raise GitChangeError("Git returned an empty file status.")

        status = status_text[0]

        if status not in _STATUS_LABELS:
            raise GitChangeError(
                f"Git returned an unsupported status: {status_text!r}"
            )

        similarity = None

        if status in {"R", "C"}:
            if index + 1 >= len(fields):
                raise GitChangeError(
                    f"Incomplete Git {status_text} path record."
                )

            previous_path = _normalize_git_path(fields[index])
            current_path = _normalize_git_path(fields[index + 1])
            index += 2

            suffix = status_text[1:]

            if suffix:
                if not suffix.isdigit():
                    raise GitChangeError(
                        f"Invalid Git similarity score: {status_text!r}"
                    )
                similarity = int(suffix)

            if similarity is not None and not 0 <= similarity <= 100:
                raise GitChangeError(
                    f"Git similarity score is outside 0..100: {similarity}"
                )

            changes.append(
                GitChange(
                    status=status,
                    path=current_path,
                    previous_path=previous_path,
                    similarity=similarity,
                )
            )
            continue

        if index >= len(fields):
            raise GitChangeError(
                f"Incomplete Git {status_text} path record."
            )

        path = _normalize_git_path(fields[index])
        index += 1

        changes.append(
            GitChange(
                status=status,
                path=path,
            )
        )

    return tuple(
        sorted(
            changes,
            key=lambda item: (
                item.path,
                item.previous_path or "",
                item.status,
            ),
        )
    )


def detect_git_changes(
    root: str | Path,
    base_ref: str,
    head_ref: str = "HEAD",
    *,
    timeout: float = DEFAULT_GIT_TIMEOUT_SECONDS,
) -> GitChangeReport:
    """Compare committed Git states and return a deterministic change report.

    The comparison uses the merge-base of base_ref and head_ref, matching
    the common three-dot comparison used for branch change analysis.

    Only committed changes are included. Uncommitted and untracked working
    tree files are deliberately not mixed into a commit-to-commit report.

    The repository is never modified.
    """

    if timeout <= 0:
        raise ValueError("timeout must be greater than zero.")

    repository_root = Path(root).expanduser().resolve()

    if not repository_root.exists() or not repository_root.is_dir():
        raise GitChangeError(
            f"Repository root is not an existing directory: "
            f"{repository_root}"
        )

    top_level_output = _run_git(
        repository_root,
        ["rev-parse", "--show-toplevel"],
        timeout,
    )

    git_root = Path(
        _decode_git_text(top_level_output, "repository root")
    ).resolve()

    if git_root != repository_root:
        raise GitChangeError(
            "The supplied root must be the Git repository's top-level "
            f"directory. Git root: {git_root}; supplied root: "
            f"{repository_root}."
        )

    normalized_base = _validate_ref(base_ref, "base_ref")
    normalized_head = _validate_ref(head_ref, "head_ref")

    base_commit = _resolve_commit(
        repository_root,
        normalized_base,
        "base_ref",
        timeout,
    )

    head_commit = _resolve_commit(
        repository_root,
        normalized_head,
        "head_ref",
        timeout,
    )

    merge_base_output = _run_git(
        repository_root,
        [
            "merge-base",
            base_commit,
            head_commit,
        ],
        timeout,
    )

    merge_base = _decode_git_text(
        merge_base_output,
        "merge base",
    )

    diff_output = _run_git(
        repository_root,
        [
            "diff",
            "--no-ext-diff",
            "--find-renames=50%",
            "--name-status",
            "-z",
            merge_base,
            head_commit,
            "--",
        ],
        timeout,
    )

    changes = _parse_name_status(diff_output)

    return GitChangeReport(
        schema_version=GIT_CHANGE_SCHEMA_VERSION,
        base_ref=normalized_base,
        head_ref=normalized_head,
        base_commit=base_commit,
        head_commit=head_commit,
        merge_base=merge_base,
        changes=changes,
    )
