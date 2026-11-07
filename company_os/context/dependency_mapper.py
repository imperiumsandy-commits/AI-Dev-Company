"""Static Python import graph builder for Company OS repository intelligence."""
from __future__ import annotations

import ast
import hashlib
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .repository_scanner import RepositorySnapshot, ScanWarning, scan_repository

SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class DependencyEdge:
    source_file: str
    source_module: str
    imported_module: str
    import_kind: str
    line: int
    classification: str
    resolved_file: str | None = None


@dataclass(frozen=True)
class ParseIssue:
    path: str
    line: int | None
    message: str


@dataclass(frozen=True)
class DependencyReport:
    schema_version: str
    snapshot_sha256: str
    files_analyzed: int
    edges: tuple[DependencyEdge, ...]
    parse_issues: tuple[ParseIssue, ...] = field(default_factory=tuple)
    warnings: tuple[ScanWarning, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        counts = {"local": 0, "stdlib": 0, "external": 0, "unresolved": 0}
        for edge in self.edges:
            counts[edge.classification] = counts.get(edge.classification, 0) + 1
        return {
            "schema_version": self.schema_version,
            "snapshot_sha256": self.snapshot_sha256,
            "files_analyzed": self.files_analyzed,
            "edge_count": len(self.edges),
            "classification_counts": counts,
            "edges": [asdict(edge) for edge in self.edges],
            "parse_issues": [asdict(issue) for issue in self.parse_issues],
            "warnings": [asdict(warning) for warning in self.warnings],
        }


def _module_name(relative_path: str) -> str | None:
    path = Path(relative_path)
    if path.suffix != ".py":
        return None
    parts = list(path.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    if not parts or any(not part.isidentifier() for part in parts):
        return None
    return ".".join(parts)


def _relative_base(source_module: str, source_path: str, level: int, module: str | None) -> str | None:
    source_parts = source_module.split(".") if source_module else []
    is_package_init = Path(source_path).name == "__init__.py"
    package_parts = source_parts if is_package_init else source_parts[:-1]
    keep = len(package_parts) - (level - 1)
    if keep < 0:
        return None
    base_parts = package_parts[:keep]
    if module:
        base_parts.extend(module.split("."))
    return ".".join(base_parts)


def _resolve_local(candidate: str, module_index: dict[str, str]) -> tuple[str, str] | None:
    if not candidate:
        return None
    parts = candidate.split(".")
    for end in range(len(parts), 0, -1):
        prefix = ".".join(parts[:end])
        if prefix in module_index:
            return prefix, module_index[prefix]
    return None


def map_python_dependencies(
    root: str | Path,
    snapshot: RepositorySnapshot | None = None,
) -> DependencyReport:
    """Build static import edges from a repository snapshot.

    This function parses Python syntax only. It does not import or execute any
    repository modules. Files changed since the snapshot are skipped.
    """
    root_path = Path(root).expanduser().resolve()
    selected_snapshot = snapshot or scan_repository(root_path)
    module_index: dict[str, str] = {}
    warnings: list[ScanWarning] = []

    for record in selected_snapshot.files:
        if record.language != "python" or not record.path.endswith(".py"):
            continue
        module = _module_name(record.path)
        if module is None:
            warnings.append(ScanWarning(
                "invalid_python_module_path", record.path,
                "Path cannot be represented as a conventional Python module; imports from it are not indexed.",
            ))
            continue
        if module in module_index:
            warnings.append(ScanWarning(
                "duplicate_python_module", record.path,
                f"Module name {module!r} is already mapped to {module_index[module]!r}; first path retained.",
            ))
            continue
        module_index[module] = record.path

    edges: list[DependencyEdge] = []
    parse_issues: list[ParseIssue] = []
    stdlib = getattr(sys, "stdlib_module_names", frozenset())
    analyzed = 0

    for record in selected_snapshot.files:
        if record.language != "python" or not record.path.endswith(".py"):
            continue
        source_module = _module_name(record.path)
        if source_module is None:
            continue
        untrusted_path = root_path / Path(record.path)
        try:
            if untrusted_path.is_symlink():
                raise ValueError("Symbolic links are not followed.")
            file_path = untrusted_path.resolve()
            file_path.relative_to(root_path)
            raw = file_path.read_bytes()
        except (OSError, ValueError) as exc:
            warnings.append(ScanWarning("dependency_read_error", record.path, str(exc)))
            continue
        if hashlib.sha256(raw).hexdigest() != record.sha256:
            warnings.append(ScanWarning(
                "source_changed_after_scan", record.path,
                "File hash no longer matches the repository snapshot; dependency analysis skipped.",
            ))
            continue
        try:
            tree = ast.parse(raw.decode("utf-8-sig"), filename=record.path)
        except (UnicodeDecodeError, SyntaxError) as exc:
            line = getattr(exc, "lineno", None)
            parse_issues.append(ParseIssue(record.path, line, str(exc)))
            continue
        analyzed += 1

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = alias.name
                    local = _resolve_local(target, module_index)
                    if local:
                        classification, resolved = "local", local[1]
                    elif target.split(".", 1)[0] in stdlib:
                        classification, resolved = "stdlib", None
                    else:
                        classification, resolved = "external", None
                    edges.append(DependencyEdge(
                        record.path, source_module, target, "import", node.lineno,
                        classification, resolved,
                    ))
            elif isinstance(node, ast.ImportFrom):
                base = _relative_base(source_module, record.path, node.level, node.module) if node.level else (node.module or "")
                targets: list[str] = []
                for alias in node.names:
                    if alias.name == "*":
                        targets.append(base)
                        continue
                    candidate = f"{base}.{alias.name}" if base else alias.name
                    local_candidate = _resolve_local(candidate, module_index)
                    if (node.level or node.module) and local_candidate:
                        targets.append(local_candidate[0])
                    else:
                        targets.append(base or candidate)
                for target in dict.fromkeys(targets):
                    local = _resolve_local(target, module_index)
                    if local:
                        classification, resolved = "local", local[1]
                    elif node.level:
                        classification, resolved = "unresolved", None
                    elif target.split(".", 1)[0] in stdlib:
                        classification, resolved = "stdlib", None
                    else:
                        classification, resolved = "external", None
                    edges.append(DependencyEdge(
                        record.path, source_module, target, "from", node.lineno,
                        classification, resolved,
                    ))

    edges.sort(key=lambda item: (
        item.source_file.casefold(), item.line, item.imported_module.casefold(), item.import_kind
    ))
    parse_issues.sort(key=lambda item: (item.path.casefold(), item.line or 0))
    warnings.sort(key=lambda item: (item.path.casefold(), item.code))
    return DependencyReport(
        schema_version=SCHEMA_VERSION,
        snapshot_sha256=selected_snapshot.snapshot_sha256,
        files_analyzed=analyzed,
        edges=tuple(edges),
        parse_issues=tuple(parse_issues),
        warnings=tuple(warnings),
    )
