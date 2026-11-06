"""Specialist-agent identity, capability and lifecycle domain API."""
from __future__ import annotations

from typing import Any

from .core import RegistryStore


class AgentRegistry:
    """Agent-domain interface; model/provider bindings are intentionally absent."""

    def __init__(self, store: RegistryStore):
        self.store = store

    def register(self, **fields: Any) -> dict[str, Any]:
        return self.store.register_agent(**fields)

    def list_for_company(self, company_id: str) -> list[dict[str, Any]]:
        return self.store.list_agents(company_id)

    def transition_status(self, **fields: Any) -> dict[str, Any]:
        return self.store.transition_status(
            entity_type="agent",
            **fields,
        )
