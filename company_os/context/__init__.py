"""Repository intelligence and bounded company-context primitives."""

from .company_policies import (
    COMPANY_OPERATING_POLICIES,
    POLICY_CATALOG_VERSION,
    OperatingPolicy,
    validate_policy_catalog,
)
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
from .l0_company_context import (
    ContextBudgetExceeded,
    ContextCompilationError,
    compile_l0_company_context,
    write_context_packet,
)
from .repository_scanner import (
    FileRecord,
    RepositorySnapshot,
    ScanPolicy,
    ScanWarning,
    scan_repository,
)

__all__ = [
    "COMPANY_OPERATING_POLICIES",
    "ContextBudgetExceeded",
    "ContextCompilationError",
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
    "OperatingPolicy",
    "POLICY_CATALOG_VERSION",
    "RepositorySnapshot",
    "ScanPolicy",
    "ScanWarning",
    "analyze_change_impact",
    "compile_l0_company_context",
    "detect_git_changes",
    "load_git_revision_dependencies",
    "map_python_dependencies",
    "scan_repository",
    "scan_repository_incremental",
    "validate_policy_catalog",
    "write_context_packet",
]
