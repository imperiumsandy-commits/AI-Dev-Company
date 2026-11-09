"""Verify the complete F01 public wiring and canonical bootstrap boundaries."""
from __future__ import annotations

import sqlite3

import pytest

import company_os.foundation as foundation_module
import company_os.registry.agent_registry as agent_module
import company_os.registry.cli as cli_module
import company_os.registry.company_registry as company_module
import company_os.registry.project_registry as project_module

from company_os.registry import (
    RegistryStore,
    SQLiteRegistryStore,
    ValidationError,
)
from company_os.registry.catalog import DEFAULT_AGENTS
from company_os.registry.service import CANONICAL_COMPANY_ID


def _canonical_records():
    company = {
        "company_id": CANONICAL_COMPANY_ID,
        "slug": "ai-dev-company",
        "name": "AI Software Engineering Company",
        "owner_name": "Owner",
        "owner_email": "owner@example.com",
    }
    project = {
        "project_id": "prj_ai_dev_company",
        "company_id": CANONICAL_COMPANY_ID,
        "slug": "ai-dev-company",
        "name": "AI-Dev-Company",
        "repository_url": (
            "https://github.com/imperiumsandy-commits/AI-Dev-Company"
        ),
        "default_branch": "main",
    }
    return company, project


def test_all_legacy_entry_points_resolve_to_hardened_registry():
    from company_os.registry.core import RegistryStore as LegacyImport

    assert foundation_module.RegistryStore is RegistryStore
    assert cli_module.RegistryStore is RegistryStore
    assert company_module.RegistryStore is RegistryStore
    assert project_module.RegistryStore is RegistryStore
    assert agent_module.RegistryStore is RegistryStore
    assert LegacyImport is RegistryStore
    assert SQLiteRegistryStore is not RegistryStore


def test_foundation_constructs_hardened_registry(tmp_path):
    foundation = foundation_module.FoundationService(tmp_path)

    assert isinstance(foundation.registry, RegistryStore)


def test_changed_roster_is_rejected_without_partial_bootstrap(tmp_path):
    registry = RegistryStore(tmp_path / "registry.sqlite3")
    company, project = _canonical_records()
    changed_agents = [dict(item) for item in DEFAULT_AGENTS]
    changed_agents[-1].update(
        agent_id="agent_unapproved_specialist",
        slug="unapproved-specialist",
        display_name="Unapproved Specialist",
        domain="unapproved-domain",
        definition_path="agents/unapproved-specialist/agent.yaml",
    )

    with pytest.raises(
        ValidationError,
        match="canonical eight-agent catalog",
    ):
        registry.bootstrap(
            company=company,
            project=project,
            agents=changed_agents,
            actor="owner:test",
            reason="reject changed roster",
        )

    with sqlite3.connect(registry.path) as db:
        for table in ("companies", "projects", "agents", "audit_events"):
            assert db.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0] == 0


def test_retry_rejects_existing_unapproved_agent_and_preserves_history(
    tmp_path,
):
    registry = RegistryStore(tmp_path / "registry.sqlite3")
    company, project = _canonical_records()
    registry.bootstrap(
        company=company,
        project=project,
        agents=DEFAULT_AGENTS,
        actor="owner:test",
        reason="initial canonical bootstrap",
    )

    legacy = SQLiteRegistryStore(registry.path)
    legacy.register_agent(
        agent_id="agent_unapproved_extension",
        company_id=CANONICAL_COMPANY_ID,
        slug="unapproved-extension",
        display_name="Unapproved Extension",
        domain="unapproved-domain",
        definition_path="agents/unapproved-extension/agent.yaml",
        role_version="1.0.0",
        capabilities=["custom_capability"],
        actor="legacy-test",
        reason="simulate old adapter bypass",
    )

    with pytest.raises(
        ValidationError,
        match="fall outside the canonical eight-agent",
    ):
        registry.bootstrap(
            company=company,
            project=project,
            agents=DEFAULT_AGENTS,
            actor="owner:test",
            reason="reject unapproved existing agent",
        )

    agents = registry.list_agents(CANONICAL_COMPANY_ID)
    assert len(agents) == 9
    assert any(
        item["agent_id"] == "agent_unapproved_extension"
        for item in agents
    )
