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
from .incremental_scanner import (
    IncrementalScanResult,
    IncrementalScanStats,
    scan_repository_incremental,
)
from .repository_scanner import (
    FileRecord,
    RepositorySnapshot,
    ScanPolicy,
    ScanWarning,
    scan_repository,
)

__all__ = [
    "DependencyReport",
    "FileRecord",
    "GitChange",
    "GitChangeError",
    "GitChangeReport",
    "GitRevisionDependencySnapshot",
    "GitRevisionSnapshotError",
    "ImpactReport",
    "ImpactedFile",
    "IncrementalScanResult",
    "IncrementalScanStats",
    "RepositorySnapshot",
    "ScanPolicy",
    "ScanWarning",
    "analyze_change_impact",
    "detect_git_changes",
    "load_git_revision_dependencies",
    "map_python_dependencies",
    "scan_repository",
    "scan_repository_incremental",
]
