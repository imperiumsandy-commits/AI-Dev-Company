"""Verify F01 public wiring and canonical bootstrap safety."""

import sqlite3

import pytest

import company_os.foundation as foundation_module
import company_os.registry.agent_registry as agent_module
import company_os.registry.cli as cli_module
import company_os.registry.company_registry as company_module
import company_os.registry.project_registry as project_module

from company_os.registry.catalog import DEFAULT_AGENTS
from company_os.registry.core import ValidationError
from company_os.registry.service import (
    CANONICAL_COMPANY_ID,
    RegistryStore as HardenedRegistryStore,
)


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


def test_all_public_entry_points_use_hardened_registry():
    assert foundation_module.RegistryStore is HardenedRegistryStore
    assert cli_module.RegistryStore is HardenedRegistryStore
    assert company_module.RegistryStore is HardenedRegistryStore
    assert project_module.RegistryStore is HardenedRegistryStore
    assert agent_module.RegistryStore is HardenedRegistryStore


def test_foundation_constructs_hardened_registry(tmp_path):
    foundation = foundation_module.FoundationService(tmp_path)

    assert isinstance(foundation.registry, HardenedRegistryStore)


def test_repeat_bootstrap_rejects_changed_canonical_roster(tmp_path):
    registry = HardenedRegistryStore(tmp_path / "registry.sqlite3")
    company, project = _canonical_records()

    registry.bootstrap(
        company=company,
        project=project,
        agents=DEFAULT_AGENTS,
        actor="owner:test",
        reason="initial canonical bootstrap",
    )

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

    registered = registry.list_agents(CANONICAL_COMPANY_ID)

    assert len(registered) == 8
    assert {
        item["agent_id"] for item in registered
    } == {
        item["agent_id"] for item in DEFAULT_AGENTS
    }


def test_normalized_canonical_company_id_cannot_bypass_roster_guard(
    tmp_path,
):
    registry = HardenedRegistryStore(tmp_path / "registry.sqlite3")
    company, project = _canonical_records()

    # The core adapter strips surrounding whitespace from IDs.
    # The hardened preflight must normalize before deciding this is
    # a non-canonical company.
    company["company_id"] = f" {CANONICAL_COMPANY_ID} "

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
            reason="reject normalized-ID roster bypass",
        )

    with sqlite3.connect(registry.path) as db:
        company_count = db.execute(
            "SELECT COUNT(*) FROM companies WHERE company_id=?",
            (CANONICAL_COMPANY_ID,),
        ).fetchone()[0]

    assert company_count == 0


def test_bootstrap_rejects_unapproved_existing_specialist(tmp_path):
    registry = HardenedRegistryStore(tmp_path / "registry.sqlite3")
    company, project = _canonical_records()

    registry.bootstrap(
        company=company,
        project=project,
        agents=DEFAULT_AGENTS,
        actor="owner:test",
        reason="initial canonical bootstrap",
    )

    registry.register_agent(
        agent_id="agent_unapproved_extension",
        company_id=CANONICAL_COMPANY_ID,
        slug="unapproved-extension",
        display_name="Unapproved Extension",
        domain="unapproved-domain",
        definition_path="agents/unapproved-extension/agent.yaml",
        role_version="1.0.0",
        capabilities=["custom_capability"],
        actor="owner:test",
        reason="simulate an unapproved extra specialist",
    )

    with pytest.raises(
        ValidationError,
        match="canonical eight-agent catalog",
    ):
        registry.bootstrap(
            company=company,
            project=project,
            agents=DEFAULT_AGENTS,
            actor="owner:test",
            reason="reject existing extra specialist",
        )

    # The rejected bootstrap must not delete or rewrite existing records.
    registered = registry.list_agents(CANONICAL_COMPANY_ID)

    assert len(registered) == 9
    assert any(
        item["agent_id"] == "agent_unapproved_extension"
        for item in registered
    )
