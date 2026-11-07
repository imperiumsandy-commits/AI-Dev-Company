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
    "ImpactedFile",
    "ImpactReport",
    "RepositorySnapshot",
    "ScanPolicy",
    "analyze_change_impact",
    "detect_git_changes",
    "map_python_dependencies",
    "scan_repository",
]
