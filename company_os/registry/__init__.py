"""Public F01 registry API.

`RegistryStore` is always the hardened application service. The original
transactional SQLite adapter remains explicitly available as
`SQLiteRegistryStore` for controlled migrations, forensic checks and backwards
compatibility tests. Legacy imports from `company_os.registry.core` that ask
for `RegistryStore` are redirected to the hardened service after initialization.
"""
from . import core as _core
from .core import (
    AGENT_STATUSES,
    COMPANY_STATUSES,
    PROJECT_STATUSES,
    SCOPE_TYPES,
    RegistryError,
    ValidationError,
    NotFound,
    Conflict,
    IntegrityViolation,
)

# Preserve the raw adapter under an unambiguous name before loading the service.
SQLiteRegistryStore = getattr(
    _core,
    "SQLiteRegistryStore",
    _core.RegistryStore,
)
_core.SQLiteRegistryStore = SQLiteRegistryStore

from .service import RegistryStore  # noqa: E402

# Existing project modules import RegistryStore from .core. Keep those imports
# safe without requiring a risky edit to the integrated Foundation module.
_core.RegistryStore = RegistryStore

from .company_registry import CompanyRegistry  # noqa: E402
from .project_registry import ProjectRegistry  # noqa: E402
from .agent_registry import AgentRegistry  # noqa: E402

__all__ = [
    "AGENT_STATUSES",
    "COMPANY_STATUSES",
    "PROJECT_STATUSES",
    "SCOPE_TYPES",
    "RegistryStore",
    "SQLiteRegistryStore",
    "CompanyRegistry",
    "ProjectRegistry",
    "AgentRegistry",
    "RegistryError",
    "ValidationError",
    "NotFound",
    "Conflict",
    "IntegrityViolation",
]
