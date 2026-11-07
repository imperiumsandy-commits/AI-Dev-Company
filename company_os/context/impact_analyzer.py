"""Deterministic change-impact analysis over a static dependency graph.

The analyzer does not import, execute, or inspect repository source code.
It consumes a DependencyReport produced by the repository intelligence layer.

An edge A -> B means that source file A imports dependency B. If B changes,
A is potentially impacted. The analyzer reverses those edges and performs
a deterministic multi-source shortest-path traversal.
"""

from __future__ import annotations

import heapq

from dataclasses import asdict, dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Iterable

from .dependency_mapper import DependencyReport

IMPACT_SCHEMA_VERSION = "1.1"


@dataclass(frozen=True)
class ImpactedFile:
    """A repository file potentially affected by a changed file."""

    path: str
    distance: int
    direct: bool
    dependency_chain: tuple[str, ...]


@dataclass(frozen=True)
class ImpactReport:
    """Impact results bound to the exact dependency snapshot used."""

    schema_version: str
    snapshot_sha256: str
    changed_files: tuple[str, ...]
    impacted_files: tuple[ImpactedFile, ...]

    @property
    def impacted_count(self) -> int:
        return len(self.impacted_files)

    @property
    def direct_count(self) -> int:
        return sum(item.direct for item in self.impacted_files)

    @property
    def transitive_count(self) -> int:
        return self.impacted_count - self.direct_count

    def to_dict(self) -> dict:
        """Return a JSON-serializable representation."""

        return {
            "schema_version": self.schema_version,
            "snapshot_sha256": self.snapshot_sha256,
            "changed_files": list(self.changed_files),
            "impacted_count": self.impacted_count,
            "direct_count": self.direct_count,
            "transitive_count": self.transitive_count,
            "impacted_files": [
                {
                    **asdict(item),
                    "dependency_chain": list(item.dependency_chain),
                }
                for item in self.impacted_files
            ],
        }


def _normalize_path(value: str) -> str:
    """Validate and canonicalize a repository-relative path."""

    if not isinstance(value, str):
        raise TypeError("Changed file paths must be strings.")

    raw = value.strip().replace("\\", "/")

    if not raw:
        raise ValueError("Changed file path cannot be empty.")

    if any(ord(character) < 32 for character in raw):
        raise ValueError("Changed file paths cannot contain control characters.")

    if raw.startswith("/") or PureWindowsPath(raw).drive:
        raise ValueError(f"Absolute paths are not allowed: {value!r}")

    if any(part == ".." for part in raw.split("/")):
        raise ValueError(f"Path traversal is not allowed: {value!r}")

    normalized = PurePosixPath(raw).as_posix()

    if normalized in {"", "."}:
        raise ValueError(f"Invalid repository-relative path: {value!r}")

    return normalized


def analyze_change_impact(
    report: DependencyReport,
    changed_files: Iterable[str],
) -> ImpactReport:
    """Find direct and transitive dependents of one or more changed files.

    Rules:
    - Only local, resolved dependency edges are traversed.
    - Paths are canonical repository-relative POSIX paths.
    - Each impacted file is reported once.
    - The shortest path from any changed file is selected.
    - Equal-length paths are resolved lexicographically.
    - Changed files are not reported as impacted files.
    - Cycles cannot cause infinite traversal.
    - The output records the dependency snapshot fingerprint.

    This is a static Python-import impact analysis. It does not claim to
    detect runtime reflection, dynamic imports, configuration dependencies,
    generated-code relationships, or non-Python dependency relationships.
    """

    if not isinstance(report, DependencyReport):
        raise TypeError("report must be a DependencyReport instance.")

    if isinstance(changed_files, (str, bytes)):
        raise TypeError(
            "changed_files must be an iterable of paths, not a string."
        )

    try:
        raw_paths = tuple(changed_files)
    except TypeError as exc:
        raise TypeError(
            "changed_files must be an iterable of repository-relative paths."
        ) from exc

    normalized_changes = tuple(
        sorted({_normalize_path(path) for path in raw_paths})
    )

    if not normalized_changes:
        raise ValueError("At least one changed file is required.")

    # Reverse A -> B import edges into B -> A dependent edges.
    dependents: dict[str, set[str]] = {}

    for edge in report.edges:
        if edge.classification != "local" or not edge.resolved_file:
            continue

        dependency = _normalize_path(edge.resolved_file)
        dependent = _normalize_path(edge.source_file)

        if dependency == dependent:
            continue

        dependents.setdefault(dependency, set()).add(dependent)

    changed_set = set(normalized_changes)

    # best[path] = (distance, path chain)
    # All changed files are roots with distance zero. This makes the
    # traversal multi-source and avoids one full graph walk per changed file.
    best: dict[str, tuple[int, tuple[str, ...]]] = {}
    frontier: list[tuple[int, tuple[str, ...], str]] = []

    for changed_path in normalized_changes:
        chain = (changed_path,)
        best[changed_path] = (0, chain)
        heapq.heappush(frontier, (0, chain, changed_path))

    while frontier:
        distance, chain, current_path = heapq.heappop(frontier)

        # Ignore obsolete heap entries after a better path was discovered.
        if best.get(current_path) != (distance, chain):
            continue

        for dependent in sorted(dependents.get(current_path, ())):
            # Changed nodes are already independent traversal roots. Do not
            # let another changed node become an intermediate path segment.
            if dependent in changed_set:
                continue

            candidate_distance = distance + 1
            candidate_chain = chain + (dependent,)
            candidate = (candidate_distance, candidate_chain)

            previous = best.get(dependent)

            # Tuple comparison gives shortest distance first, then the
            # lexicographically smallest full path for deterministic ties.
            if previous is not None and candidate >= previous:
                continue

            best[dependent] = candidate
            heapq.heappush(
                frontier,
                (
                    candidate_distance,
                    candidate_chain,
                    dependent,
                ),
            )

    impacted_files = tuple(
        ImpactedFile(
            path=path,
            distance=distance,
            direct=distance == 1,
            dependency_chain=chain,
        )
        for path, (distance, chain) in sorted(
            best.items(),
            key=lambda item: (
                item[1][0],
                item[0],
                item[1][1],
            ),
        )
        if path not in changed_set
    )

    return ImpactReport(
        schema_version=IMPACT_SCHEMA_VERSION,
        snapshot_sha256=report.snapshot_sha256,
        changed_files=normalized_changes,
        impacted_files=impacted_files,
    )
