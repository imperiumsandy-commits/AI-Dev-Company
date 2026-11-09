"""Incremental, cache-backed repository inventory.

The full repository scanner remains the reference implementation.
Metadata-based cache reuse is a performance optimization, not tamper-proof
audit evidence. Use strict verification or a full scan for audit-sensitive
operations.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .repository_scanner import (
    SCHEMA_VERSION,
    _is_excluded_name,
    _is_supported_file,
    _LANGUAGE_BY_EXTENSION,
    FileRecord,
    RepositorySnapshot,
    ScanPolicy,
    ScanWarning,
)

CACHE_SCHEMA_VERSION = "1.0"
DEFAULT_CACHE_RELATIVE_PATH = Path(".ai-dev-company") / "repository-scan-cache.json"
MAX_CACHE_BYTES = 64 * 1024 * 1024

_FINGERPRINT_FIELDS = (
    "device",
    "inode",
    "file_type",
    "size",
    "mtime_ns",
    "ctime_ns",
)


@dataclass(frozen=True)
class IncrementalScanStats:
    """Observable accounting for one incremental scan."""

    cache_state: str
    cache_reason: str | None
    files_reused: int
    files_read: int
    bytes_read: int
    entries_written: int
    verification_mode: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class IncrementalScanResult:
    """Repository snapshot plus cache and performance evidence."""

    snapshot: RepositorySnapshot
    stats: IncrementalScanStats
    cache_path: str

    def to_dict(self) -> dict:
        return {
            "snapshot_sha256": self.snapshot.snapshot_sha256,
            "cache_path": self.cache_path,
            "stats": self.stats.to_dict(),
        }


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _policy_payload(policy: ScanPolicy) -> dict:
    return {
        "extensions": sorted(policy.extensions),
        "excluded_dirs": sorted(policy.excluded_dirs),
        "excluded_patterns": list(policy.excluded_patterns),
        "max_file_bytes": policy.max_file_bytes,
        "include_hidden_files": policy.include_hidden_files,
    }


def _policy_sha256(policy: ScanPolicy) -> str:
    return _sha256_json(_policy_payload(policy))


def _stat_fingerprint(file_stat: os.stat_result) -> dict[str, int]:
    """Build a conservative filesystem identity/metadata fingerprint."""

    return {
        "device": int(file_stat.st_dev),
        "inode": int(file_stat.st_ino),
        "file_type": int(stat.S_IFMT(file_stat.st_mode)),
        "size": int(file_stat.st_size),
        "mtime_ns": int(
            getattr(
                file_stat,
                "st_mtime_ns",
                file_stat.st_mtime * 1_000_000_000,
            )
        ),
        "ctime_ns": int(
            getattr(
                file_stat,
                "st_ctime_ns",
                file_stat.st_ctime * 1_000_000_000,
            )
        ),
    }


def _safe_relative_path(value: str) -> bool:
    if not isinstance(value, str) or not value:
        return False

    normalized = value.replace("\\", "/")

    if normalized.startswith("/"):
        return False

    parts = normalized.split("/")

    return not any(part in {"", ".", ".."} for part in parts)


def _record_from_cache(value: Any) -> FileRecord | None:
    if value is None:
        return None

    if not isinstance(value, dict):
        raise ValueError("Cached file record must be an object.")

    expected = {
        "path",
        "extension",
        "language",
        "size_bytes",
        "line_count",
        "sha256",
    }

    if set(value) != expected:
        raise ValueError("Cached file record has an invalid shape.")

    path = value["path"]
    extension = value["extension"]
    language = value["language"]
    size_bytes = value["size_bytes"]
    line_count = value["line_count"]
    digest = value["sha256"]

    if not _safe_relative_path(path):
        raise ValueError("Cached file record contains an unsafe path.")

    if not isinstance(extension, str) or not isinstance(language, str):
        raise ValueError("Cached file record contains invalid text fields.")

    if (
        not isinstance(size_bytes, int)
        or isinstance(size_bytes, bool)
        or size_bytes < 0
    ):
        raise ValueError("Cached file record has an invalid size.")

    if (
        not isinstance(line_count, int)
        or isinstance(line_count, bool)
        or line_count < 0
    ):
        raise ValueError("Cached file record has an invalid line count.")

    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError("Cached file record has an invalid SHA-256 digest.")

    return FileRecord(
        path=path,
        extension=extension,
        language=language,
        size_bytes=size_bytes,
        line_count=line_count,
        sha256=digest,
    )


def _warning_from_cache(value: Any) -> ScanWarning | None:
    if value is None:
        return None

    if not isinstance(value, dict):
        raise ValueError("Cached warning must be an object.")

    if set(value) != {"code", "path", "message"}:
        raise ValueError("Cached warning has an invalid shape.")

    if not all(
        isinstance(value[key], str)
        for key in ("code", "path", "message")
    ):
        raise ValueError("Cached warning fields must be strings.")

    if not _safe_relative_path(value["path"]):
        raise ValueError("Cached warning contains an unsafe path.")

    return ScanWarning(
        code=value["code"],
        path=value["path"],
        message=value["message"],
    )


def _validate_cache_entry(path: str, value: Any) -> dict:
    if not _safe_relative_path(path):
        raise ValueError("Cache contains an unsafe repository path.")

    if not isinstance(value, dict):
        raise ValueError("Cache entry must be an object.")

    if set(value) != {"fingerprint", "record", "warning"}:
        raise ValueError("Cache entry has an invalid shape.")

    fingerprint = value["fingerprint"]

    if not isinstance(fingerprint, dict):
        raise ValueError("Cache fingerprint must be an object.")

    if set(fingerprint) != set(_FINGERPRINT_FIELDS):
        raise ValueError("Cache fingerprint has an invalid shape.")

    for key in _FINGERPRINT_FIELDS:
        item = fingerprint[key]

        if not isinstance(item, int) or isinstance(item, bool):
            raise ValueError("Cache fingerprint values must be integers.")

    if fingerprint["size"] < 0:
        raise ValueError("Cache fingerprint size cannot be negative.")

    record = _record_from_cache(value["record"])
    warning = _warning_from_cache(value["warning"])

    if (record is None) == (warning is None):
        raise ValueError(
            "Cache entry must contain exactly one record or warning."
        )

    if record is not None and record.path != path:
        raise ValueError("Cache record path does not match its entry key.")

    if warning is not None and warning.path != path:
        raise ValueError("Cache warning path does not match its entry key.")

    return {
        "fingerprint": fingerprint,
        "record": asdict(record) if record is not None else None,
        "warning": asdict(warning) if warning is not None else None,
    }


def _load_cache(
    cache_path: Path,
    root: Path,
    policy: ScanPolicy,
) -> tuple[dict[str, dict], str, str | None]:
    """Load and validate cache; invalid caches become safe full-scan misses."""

    if not cache_path.exists():
        return {}, "miss", "Cache file does not exist."

    if cache_path.is_symlink():
        raise ValueError("The scan cache cannot be a symbolic link.")

    try:
        cache_stat = cache_path.stat()

        if not stat.S_ISREG(cache_stat.st_mode):
            return {}, "invalid", "Cache path is not a regular file."

        if cache_stat.st_size > MAX_CACHE_BYTES:
            return {}, "invalid", "Cache file exceeds the maximum size."

        raw = cache_path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))

    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        return {}, "invalid", f"Cache could not be read or parsed: {exc}"

    if not isinstance(payload, dict):
        return {}, "invalid", "Cache root must be a JSON object."

    expected_fields = {
        "schema_version",
        "scanner_schema_version",
        "root",
        "policy_sha256",
        "entries",
        "cache_sha256",
    }

    if set(payload) != expected_fields:
        return {}, "invalid", "Cache envelope has an invalid shape."

    supplied_digest = payload.get("cache_sha256")
    core = {
        key: value
        for key, value in payload.items()
        if key != "cache_sha256"
    }

    try:
        calculated_digest = _sha256_json(core)
    except (TypeError, ValueError):
        return {}, "invalid", "Cache contains non-canonical JSON values."

    if (
        not isinstance(supplied_digest, str)
        or supplied_digest != calculated_digest
    ):
        return {}, "invalid", "Cache integrity digest does not match."

    if payload["schema_version"] != CACHE_SCHEMA_VERSION:
        return {}, "schema_changed", "Cache schema version changed."

    if payload["scanner_schema_version"] != SCHEMA_VERSION:
        return {}, "scanner_changed", "Scanner schema version changed."

    if payload["root"] != str(root):
        return {}, "root_changed", "Repository root changed."

    if payload["policy_sha256"] != _policy_sha256(policy):
        return {}, "policy_changed", "Scan policy changed."

    raw_entries = payload["entries"]

    if not isinstance(raw_entries, dict):
        return {}, "invalid", "Cache entries must be an object."

    try:
        entries = {
            path: _validate_cache_entry(path, item)
            for path, item in raw_entries.items()
        }
    except (TypeError, ValueError) as exc:
        return {}, "invalid", f"Cache entries failed validation: {exc}"

    return entries, "hit", None


def _cache_path_for(
    root: Path,
    requested_path: str | os.PathLike[str] | None,
    policy: ScanPolicy,
) -> Path:
    """Resolve cache location and prevent self-indexing or symlink escapes."""

    if requested_path is None:
        candidate = root / DEFAULT_CACHE_RELATIVE_PATH
    else:
        candidate = Path(requested_path).expanduser()

        if not candidate.is_absolute():
            candidate = root / candidate

    candidate = Path(os.path.abspath(candidate))

    # Reject symlinks in the cache path and all existing parent components.
    for component in (*reversed(candidate.parents), candidate):
        if component.is_symlink():
            raise ValueError(
                "The scan cache path cannot pass through symbolic links."
            )

    if candidate.exists() and not candidate.is_file():
        raise ValueError("The scan cache path must be a regular file.")

    resolved = candidate.resolve()

    try:
        lexical_relative = candidate.relative_to(root)
    except ValueError:
        lexical_relative = None

    if lexical_relative is not None and not resolved.is_relative_to(root):
        raise ValueError(
            "The scan cache path resolves outside the repository through "
            "a symbolic link."
        )

    if resolved.is_relative_to(root):
        relative = resolved.relative_to(root)
        parts = relative.parts

        inside_excluded_directory = any(
            part.casefold() in policy.excluded_dirs
            for part in parts[:-1]
        )

        excluded_filename = _is_excluded_name(
            relative.name,
            policy.excluded_patterns,
        )

        if not inside_excluded_directory and not excluded_filename:
            raise ValueError(
                "A cache file inside the repository must be stored in an "
                "excluded directory or use an excluded filename. The cache "
                "must never become part of its own repository snapshot."
            )

    return resolved


def _write_cache(
    cache_path: Path,
    root: Path,
    policy: ScanPolicy,
    entries: dict[str, dict],
) -> None:
    core = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "scanner_schema_version": SCHEMA_VERSION,
        "root": str(root),
        "policy_sha256": _policy_sha256(policy),
        "entries": entries,
    }

    payload = {
        **core,
        "cache_sha256": _sha256_json(core),
    }

    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ) + "\n"

    if len(serialized.encode("utf-8")) > MAX_CACHE_BYTES:
        raise ValueError(
            "The generated scan cache exceeds the maximum cache size. "
            "Use a narrower scan policy or a larger cache implementation."
        )

    cache_path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=cache_path.parent,
            prefix=f".{cache_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary_path, cache_path)
        temporary_path = None

    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _entry_for(
    fingerprint: dict[str, int],
    *,
    record: FileRecord | None = None,
    warning: ScanWarning | None = None,
) -> dict:
    if (record is None) == (warning is None):
        raise ValueError("An entry must contain exactly one result.")

    return {
        "fingerprint": fingerprint,
        "record": asdict(record) if record is not None else None,
        "warning": asdict(warning) if warning is not None else None,
    }


def _restore_entry(
    value: dict,
) -> tuple[FileRecord | None, ScanWarning | None]:
    return (
        _record_from_cache(value["record"]),
        _warning_from_cache(value["warning"]),
    )


def scan_repository_incremental(
    root: str | os.PathLike[str],
    policy: ScanPolicy | None = None,
    *,
    cache_path: str | os.PathLike[str] | None = None,
    verify_unchanged: bool = False,
    force_full: bool = False,
) -> IncrementalScanResult:
    """Create an incremental snapshot using a validated metadata cache.

    Unchanged files are reused only when device, inode, file type, size,
    mtime, ctime, scanner schema, repository root, and policy fingerprint
    match.

    `verify_unchanged=True` reads and hashes every eligible file even when
    metadata matches. `force_full=True` ignores cached entries and rebuilds
    the cache from the current repository.

    Directory traversal always occurs, so added and deleted paths are found.
    The cache never stores source contents.
    """

    if not isinstance(verify_unchanged, bool):
        raise TypeError("verify_unchanged must be a boolean.")

    if not isinstance(force_full, bool):
        raise TypeError("force_full must be a boolean.")

    selected_policy = policy or ScanPolicy()
    root_path = Path(root).expanduser().resolve()

    if not root_path.exists() or not root_path.is_dir():
        raise ValueError(
            f"Repository root is not an existing directory: {root}"
        )

    resolved_cache_path = _cache_path_for(
        root_path,
        cache_path,
        selected_policy,
    )

    if force_full:
        previous_entries: dict[str, dict] = {}
        cache_state = "forced_full"
        cache_reason = "A full content scan was explicitly requested."
    else:
        previous_entries, cache_state, cache_reason = _load_cache(
            resolved_cache_path,
            root_path,
            selected_policy,
        )

    records: list[FileRecord] = []
    warnings: list[ScanWarning] = []
    new_entries: dict[str, dict] = {}

    skipped = 0
    files_reused = 0
    files_read = 0
    bytes_read = 0

    def walk_error(error: OSError) -> None:
        nonlocal skipped

        skipped += 1
        raw_error_path = getattr(error, "filename", None) or "."

        try:
            error_path = (
                Path(raw_error_path)
                .resolve()
                .relative_to(root_path)
                .as_posix()
            )
        except (OSError, ValueError):
            error_path = "."

        warnings.append(
            ScanWarning(
                "directory_read_error",
                error_path,
                str(error),
            )
        )

    for current_root, directory_names, file_names in os.walk(
        root_path,
        topdown=True,
        followlinks=False,
        onerror=walk_error,
    ):
        current = Path(current_root)
        kept_directories: list[str] = []

        for directory_name in sorted(directory_names, key=str.casefold):
            candidate = current / directory_name

            if (
                directory_name.casefold() in selected_policy.excluded_dirs
                or candidate.is_symlink()
            ):
                continue

            if (
                not selected_policy.include_hidden_files
                and directory_name.startswith(".")
            ):
                continue

            kept_directories.append(directory_name)

        directory_names[:] = kept_directories

        for file_name in sorted(file_names, key=str.casefold):
            candidate = current / file_name
            relative = candidate.relative_to(root_path).as_posix()

            if candidate.is_symlink():
                skipped += 1
                warnings.append(
                    ScanWarning(
                        "symlink_skipped",
                        relative,
                        "Symbolic links are not followed.",
                    )
                )
                continue

            if (
                not selected_policy.include_hidden_files
                and file_name.startswith(".")
            ):
                skipped += 1
                continue

            if _is_excluded_name(
                file_name,
                selected_policy.excluded_patterns,
            ):
                skipped += 1
                continue

            if not _is_supported_file(candidate, selected_policy):
                skipped += 1
                continue

            try:
                before = candidate.lstat()
            except OSError as exc:
                skipped += 1
                warnings.append(
                    ScanWarning("file_read_error", relative, str(exc))
                )
                continue

            if not stat.S_ISREG(before.st_mode):
                skipped += 1
                continue

            before_fingerprint = _stat_fingerprint(before)
            cached = previous_entries.get(relative)

            if (
                cached is not None
                and cached["fingerprint"] == before_fingerprint
                and not verify_unchanged
            ):
                # Recheck metadata after cache lookup to reduce scan races.
                try:
                    after = candidate.lstat()
                except OSError as exc:
                    skipped += 1
                    warnings.append(
                        ScanWarning("file_read_error", relative, str(exc))
                    )
                    continue

                if (
                    not stat.S_ISREG(after.st_mode)
                    or _stat_fingerprint(after) != before_fingerprint
                ):
                    skipped += 1
                    warnings.append(
                        ScanWarning(
                            "file_changed_during_scan",
                            relative,
                            "File metadata changed during cache validation; "
                            "record omitted.",
                        )
                    )
                    continue

                record, warning = _restore_entry(cached)
                new_entries[relative] = cached
                files_reused += 1

                if record is not None:
                    records.append(record)
                else:
                    skipped += 1
                    warnings.append(warning)

                continue

            if before.st_size > selected_policy.max_file_bytes:
                skipped += 1

                warning = ScanWarning(
                    "file_too_large",
                    relative,
                    f"File is {before.st_size} bytes; limit is "
                    f"{selected_policy.max_file_bytes} bytes.",
                )

                warnings.append(warning)
                new_entries[relative] = _entry_for(
                    before_fingerprint,
                    warning=warning,
                )
                continue

            try:
                raw = candidate.read_bytes()
                files_read += 1
                bytes_read += len(raw)
                after = candidate.lstat()

            except OSError as exc:
                skipped += 1
                warnings.append(
                    ScanWarning("file_read_error", relative, str(exc))
                )
                continue

            after_fingerprint = _stat_fingerprint(after)

            if (
                not stat.S_ISREG(after.st_mode)
                or before_fingerprint != after_fingerprint
                or len(raw) != after.st_size
            ):
                skipped += 1

                warning = ScanWarning(
                    "file_changed_during_scan",
                    relative,
                    "File metadata changed while it was being read; "
                    "record omitted.",
                )

                warnings.append(warning)
                continue

            if b"\x00" in raw[:8192]:
                skipped += 1

                warning = ScanWarning(
                    "binary_file_skipped",
                    relative,
                    "Binary content is not indexed.",
                )

                warnings.append(warning)
                new_entries[relative] = _entry_for(
                    after_fingerprint,
                    warning=warning,
                )
                continue

            try:
                decoded = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                skipped += 1

                warning = ScanWarning(
                    "non_utf8_file_skipped",
                    relative,
                    "File is not valid UTF-8 text.",
                )

                warnings.append(warning)
                new_entries[relative] = _entry_for(
                    after_fingerprint,
                    warning=warning,
                )
                continue

            extension = candidate.suffix.casefold()

            record = FileRecord(
                path=relative,
                extension=extension,
                language=_LANGUAGE_BY_EXTENSION.get(extension, "text"),
                size_bytes=len(raw),
                line_count=len(decoded.splitlines()),
                sha256=hashlib.sha256(raw).hexdigest(),
            )

            records.append(record)
            new_entries[relative] = _entry_for(
                after_fingerprint,
                record=record,
            )

    records.sort(key=lambda item: item.path.casefold())
    warnings.sort(
        key=lambda item: (item.path.casefold(), item.code)
    )

    snapshot = RepositorySnapshot(
        schema_version=SCHEMA_VERSION,
        root_name=root_path.name or "repository",
        files=tuple(records),
        skipped_files=skipped,
        total_bytes=sum(item.size_bytes for item in records),
        warnings=tuple(warnings),
    )

    _write_cache(
        resolved_cache_path,
        root_path,
        selected_policy,
        new_entries,
    )

    stats = IncrementalScanStats(
        cache_state=cache_state,
        cache_reason=cache_reason,
        files_reused=files_reused,
        files_read=files_read,
        bytes_read=bytes_read,
        entries_written=len(new_entries),
        verification_mode=(
            "strict_content_verification"
            if verify_unchanged
            else "metadata_cache"
        ),
    )

    cache_display_path = (
        resolved_cache_path.relative_to(root_path).as_posix()
        if resolved_cache_path.is_relative_to(root_path)
        else str(resolved_cache_path)
    )

    return IncrementalScanResult(
        snapshot=snapshot,
        stats=stats,
        cache_path=cache_display_path,
    )
