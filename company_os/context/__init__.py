"""Repository intelligence primitives for the Company OS foundation."""

from .dependency_mapper import (
    DependencyReport,
    map_python_dependencies,
)
from .git_changes import (
    GitChange,
    GitChangeError,
    GitChangeReport,
    detect_git_changes,
)
from .git_snapshot import (
    GitRevisionDependencySnapshot,
    GitRevisionSnapshotError,
    load_git_revision_dependencies,
)
from .impact_analyzer import (
    ImpactedFile,
    ImpactReport,
    analyze_change_impact,
)
from .repository_scanner import (
    RepositorySnapshot,
    ScanPolicy,
    scan_repository,
)

__all__ = [
    "DependencyReport",
    "GitChange",
    "GitChangeError",
    "GitChangeReport",
    "GitRevisionDependencySnapshot",
    "GitRevisionSnapshotError",
    "ImpactedFile",
    "ImpactReport",
    "RepositorySnapshot",
    "ScanPolicy",
    "analyze_change_impact",
    "detect_git_changes",
    "load_git_revision_dependencies",
    "map_python_dependencies",
    "scan_repository",
]
