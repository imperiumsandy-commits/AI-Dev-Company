"""Project identity and lifecycle domain API."""
from __future__ import annotations

from typing import Any

from .core import RegistryStore


class ProjectRegistry:
    """Project-domain interface; all writes remain transactional and audited."""

    def __init__(self, store: RegistryStore):
        self.store = store

    def register(self, **fields: Any) -> dict[str, Any]:
        return self.store.register_project(**fields)

    def list_for_company(self, company_id: str) -> list[dict[str, Any]]:
        return self.store.list_projects(company_id)

    def transition_status(self, **fields: Any) -> dict[str, Any]:
        return self.store.transition_status(
            entity_type="project",
            **fields,
        )
