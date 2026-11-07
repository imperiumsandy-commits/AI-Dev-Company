"""Deterministic change-impact analysis over the static dependency graph.

The analyzer never imports or executes repository code. It uses only local
dependency edges already produced by the repository intelligence layer.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Iterable

from .dependency_mapper import DependencyReport


@dataclass(frozen=True)
class ImpactedFile:
    """A repository file affected by a changed file."""

    path: str
    distance: int
    direct: bool
    dependency_chain: tuple[str, ...]


@dataclass(frozen=True)
class ImpactReport:
    """Stable, machine-readable result of a change-impact analysis."""

    schema_version: str
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
        return {
            "schema_version": self.schema_version,
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
    """Validate and normalize a repository-relative POSIX path."""

    if not isinstance(value, str):
        raise TypeError("Changed file paths must be strings.")

    raw = value.strip().replace("\\", "/")

    if not raw:
        raise ValueError("Changed file path cannot be empty.")

    if raw.startswith("/") or PureWindowsPath(value).drive:
        raise ValueError(f"Absolute paths are not allowed: {value!r}")

    parts = raw.split("/")

    if any(part == ".." for part in parts):
        raise ValueError(f"Path traversal is not allowed: {value!r}")

    normalized = PurePosixPath(raw).as_posix()

    if normalized in {"", "."}:
        raise ValueError(f"Invalid repository-relative path: {value!r}")

    return normalized


def analyze_change_impact(
    report: DependencyReport,
    changed_files: Iterable[str],
) -> ImpactReport:
    """Find direct and transitive dependents of changed repository files.

    A dependency edge A -> B means that A imports B. Therefore, when B changes,
    A is potentially impacted.

    The result is deterministic:
    - only local, resolved dependency edges are traversed;
    - paths are repository-relative;
    - shortest dependency chains are preferred;
    - ties are resolved lexicographically;
    - cycles cannot cause infinite traversal.
    """

    if isinstance(changed_files, (str, bytes)):
        raise TypeError("changed_files must be an iterable of paths, not a string.")

    normalized_changes = tuple(
        sorted({_normalize_path(path) for path in changed_files})
    )

    if not normalized_changes:
        raise ValueError("At least one changed file is required.")

    # Reverse the graph: imported file -> files that depend on it.
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

    # Store the best chain for every impacted file.
    best: dict[str, tuple[str, ...]] = {}

    for changed_path in normalized_changes:
        queue = deque([(changed_path, (changed_path,))])
        visited: dict[str, int] = {changed_path: 0}

        while queue:
            current_path, chain = queue.popleft()
            next_distance = len(chain)

            for dependent in sorted(dependents.get(current_path, ())):
                if dependent in visited and visited[dependent] <= next_distance:
                    continue

                visited[dependent] = next_distance
                next_chain = chain + (dependent,)

                queue.append((dependent, next_chain))

                if dependent in changed_set:
                    continue

                previous = best.get(dependent)

                if previous is None or (
                    len(next_chain), next_chain
                ) < (
                    len(previous), previous
                ):
                    best[dependent] = next_chain

    impacted = tuple(
        ImpactedFile(
            path=path,
            distance=len(chain) - 1,
            direct=len(chain) == 2,
            dependency_chain=chain,
        )
        for path, chain in sorted(
            best.items(),
            key=lambda item: (
                len(item[1]) - 1,
                item[0],
                item[1],
            ),
        )
    )

    return ImpactReport(
        schema_version="1.0",
        changed_files=normalized_changes,
        impacted_files=impacted,
    )
