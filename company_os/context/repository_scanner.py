"""Deterministic, content-free repository inventory for Company OS.

The scanner records metadata and SHA-256 digests only. It never executes
repository code and deliberately excludes common secret and runtime paths.
"""
from __future__ import annotations

import fnmatch
import hashlib
import os
import stat
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

SCHEMA_VERSION = "1.0"

DEFAULT_EXTENSIONS = frozenset({
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".java", ".go", ".rs", ".cs", ".c", ".h", ".cc", ".cpp", ".hpp",
    ".swift", ".kt", ".kts", ".rb", ".php", ".sh", ".ps1", ".sql",
    ".html", ".htm", ".css", ".scss", ".sass", ".less", ".vue", ".svelte",
    ".json", ".jsonc", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".xml", ".md", ".rst", ".txt", ".lock", ".properties",
})
SPECIAL_TEXT_FILES = frozenset({
    ".gitignore", ".gitattributes", ".dockerignore", ".editorconfig",
    "dockerfile", "makefile", "procfile", "license", "notice",
    "requirements.txt", "pipfile", "poetry.lock", "uv.lock", ".env.example",
})
DEFAULT_EXCLUDED_DIRS = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "env", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".nox",
    "node_modules", "dist", "build", "site-packages", ".next", ".nuxt",
    ".idea", ".vscode", ".ai-dev-company",
})
DEFAULT_EXCLUDED_PATTERNS = (
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "*.jks",
    "*.sqlite", "*.sqlite3", "*.db", "*.log", "*ps-output*",
    "*ps output*", "*ps_output*", "*.pyc", "*.pyo",
)

_LANGUAGE_BY_EXTENSION = {
    ".py": "python", ".pyi": "python", ".js": "javascript", ".jsx": "javascript",
    ".mjs": "javascript", ".cjs": "javascript", ".ts": "typescript", ".tsx": "typescript",
    ".java": "java", ".go": "go", ".rs": "rust", ".cs": "csharp",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp",
    ".swift": "swift", ".kt": "kotlin", ".kts": "kotlin", ".rb": "ruby",
    ".php": "php", ".sh": "shell", ".ps1": "powershell", ".sql": "sql",
    ".html": "html", ".htm": "html", ".css": "css", ".scss": "scss",
    ".sass": "sass", ".less": "less", ".vue": "vue", ".svelte": "svelte",
    ".json": "json", ".jsonc": "jsonc", ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".ini": "ini", ".cfg": "config", ".xml": "xml",
    ".md": "markdown", ".rst": "restructuredtext", ".txt": "text",
    ".lock": "lockfile", ".properties": "properties",
}


@dataclass(frozen=True)
class ScanPolicy:
    """Controls what the inventory is permitted to inspect."""

    extensions: frozenset[str] = DEFAULT_EXTENSIONS
    excluded_dirs: frozenset[str] = DEFAULT_EXCLUDED_DIRS
    excluded_patterns: tuple[str, ...] = DEFAULT_EXCLUDED_PATTERNS
    max_file_bytes: int = 2 * 1024 * 1024
    include_hidden_files: bool = True

    def __post_init__(self) -> None:
        if self.max_file_bytes < 1:
            raise ValueError("max_file_bytes must be greater than zero")
        normalized = frozenset(
            ext.lower() if ext.startswith(".") else f".{ext.lower()}"
            for ext in self.extensions
        )
        object.__setattr__(self, "extensions", normalized)
        object.__setattr__(self, "excluded_dirs", frozenset(x.casefold() for x in self.excluded_dirs))
        object.__setattr__(self, "excluded_patterns", tuple(x.casefold() for x in self.excluded_patterns))


@dataclass(frozen=True)
class FileRecord:
    path: str
    extension: str
    language: str
    size_bytes: int
    line_count: int
    sha256: str


@dataclass(frozen=True)
class ScanWarning:
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class RepositorySnapshot:
    schema_version: str
    root_name: str
    files: tuple[FileRecord, ...]
    skipped_files: int
    total_bytes: int
    warnings: tuple[ScanWarning, ...] = field(default_factory=tuple)

    @property
    def snapshot_sha256(self) -> str:
        digest = hashlib.sha256()
        for record in self.files:
            digest.update(record.path.encode("utf-8"))
            digest.update(b"\0")
            digest.update(record.sha256.encode("ascii"))
            digest.update(b"\n")
        return digest.hexdigest()

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "root_name": self.root_name,
            "snapshot_sha256": self.snapshot_sha256,
            "file_count": len(self.files),
            "skipped_files": self.skipped_files,
            "total_bytes": self.total_bytes,
            "files": [asdict(record) for record in self.files],
            "warnings": [asdict(warning) for warning in self.warnings],
        }


def _is_excluded_name(name: str, patterns: Iterable[str]) -> bool:
    lowered = name.casefold()
    if lowered == ".env.example":
        return False
    return any(fnmatch.fnmatchcase(lowered, pattern) for pattern in patterns)


def _is_supported_file(path: Path, policy: ScanPolicy) -> bool:
    lowered_name = path.name.casefold()
    return path.suffix.casefold() in policy.extensions or lowered_name in SPECIAL_TEXT_FILES


def scan_repository(root: str | os.PathLike[str], policy: ScanPolicy | None = None) -> RepositorySnapshot:
    """Scan a repository without executing code or persisting file contents.

    Paths in the output are repository-relative POSIX paths. Ordering and
    output are deterministic for an unchanged repository and policy.
    """
    selected_policy = policy or ScanPolicy()
    root_path = Path(root).expanduser().resolve()
    if not root_path.exists() or not root_path.is_dir():
        raise ValueError(f"Repository root is not an existing directory: {root}")

    records: list[FileRecord] = []
    warnings: list[ScanWarning] = []
    skipped = 0

    def walk_error(error: OSError) -> None:
        nonlocal skipped
        skipped += 1
        raw_error_path = getattr(error, "filename", None) or "."
        try:
            error_path = Path(raw_error_path).resolve().relative_to(root_path).as_posix()
        except (OSError, ValueError):
            error_path = "."
        warnings.append(ScanWarning("directory_read_error", error_path, str(error)))

    for current_root, directory_names, file_names in os.walk(
        root_path, topdown=True, followlinks=False, onerror=walk_error
    ):
        current = Path(current_root)
        kept_directories: list[str] = []
        for directory_name in sorted(directory_names, key=str.casefold):
            candidate = current / directory_name
            if directory_name.casefold() in selected_policy.excluded_dirs or candidate.is_symlink():
                continue
            if not selected_policy.include_hidden_files and directory_name.startswith("."):
                continue
            kept_directories.append(directory_name)
        directory_names[:] = kept_directories

        for file_name in sorted(file_names, key=str.casefold):
            candidate = current / file_name
            relative = candidate.relative_to(root_path).as_posix()
            if candidate.is_symlink():
                skipped += 1
                warnings.append(ScanWarning("symlink_skipped", relative, "Symbolic links are not followed."))
                continue
            if not selected_policy.include_hidden_files and file_name.startswith("."):
                skipped += 1
                continue
            if _is_excluded_name(file_name, selected_policy.excluded_patterns):
                skipped += 1
                continue
            if not _is_supported_file(candidate, selected_policy):
                skipped += 1
                continue

            try:
                before = candidate.lstat()
                if not stat.S_ISREG(before.st_mode):
                    skipped += 1
                    continue
                if before.st_size > selected_policy.max_file_bytes:
                    skipped += 1
                    warnings.append(ScanWarning(
                        "file_too_large", relative,
                        f"File is {before.st_size} bytes; limit is {selected_policy.max_file_bytes} bytes.",
                    ))
                    continue
                raw = candidate.read_bytes()
                after = candidate.lstat()
            except OSError as exc:
                skipped += 1
                warnings.append(ScanWarning("file_read_error", relative, str(exc)))
                continue

            if not stat.S_ISREG(after.st_mode) or before.st_size != after.st_size or len(raw) != after.st_size:
                skipped += 1
                warnings.append(ScanWarning(
                    "file_changed_during_scan", relative,
                    "File metadata changed while it was being read; record omitted.",
                ))
                continue
            if b"\x00" in raw[:8192]:
                skipped += 1
                warnings.append(ScanWarning("binary_file_skipped", relative, "Binary content is not indexed."))
                continue
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                skipped += 1
                warnings.append(ScanWarning("non_utf8_file_skipped", relative, "File is not valid UTF-8 text."))
                continue

            extension = candidate.suffix.casefold()
            language = _LANGUAGE_BY_EXTENSION.get(extension, "text")
            records.append(FileRecord(
                path=relative,
                extension=extension,
                language=language,
                size_bytes=len(raw),
                line_count=len(text.splitlines()),
                sha256=hashlib.sha256(raw).hexdigest(),
            ))

    records.sort(key=lambda item: item.path.casefold())
    warnings.sort(key=lambda item: (item.path.casefold(), item.code))
    return RepositorySnapshot(
        schema_version=SCHEMA_VERSION,
        root_name=root_path.name or "repository",
        files=tuple(records),
        skipped_files=skipped,
        total_bytes=sum(item.size_bytes for item in records),
        warnings=tuple(warnings),
    )
