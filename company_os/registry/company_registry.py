"""Company identity domain API."""
from __future__ import annotations

from typing import Any

from .core import RegistryStore


class CompanyRegistry:
    """Narrow company-domain interface over the shared transactional store."""

    def __init__(self, store: RegistryStore):
        self.store = store

    def register(self, **fields: Any) -> dict[str, Any]:
        return self.store.register_company(**fields)

    def get(self, company_id: str) -> dict[str, Any]:
        return self.store.get_company(company_id)
