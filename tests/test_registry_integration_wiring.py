"""Verify every public F01 entry point uses the hardened registry service."""
import pytest

import company_os.foundation as foundation_module
import company_os.registry.agent_registry as agent_module
import company_os.registry.cli as cli_module
import company_os.registry.company_registry as company_module
import company_os.registry.project_registry as project_module

from company_os.registry.catalog import DEFAULT_AGENTS
from company_os.registry.core import ValidationError
from company_os.registry.service import RegistryStore as HardenedRegistryStore


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

    company = {
        "company_id": "co_ai_dev_company",
        "slug": "ai-dev-company",
        "name": "AI Software Engineering Company",
        "owner_name": "Owner",
        "owner_email": "owner@example.com",
    }
    project = {
        "project_id": "prj_ai_dev_company",
        "company_id": "co_ai_dev_company",
        "slug": "ai-dev-company",
        "name": "AI-Dev-Company",
        "repository_url": (
            "https://github.com/imperiumsandy-commits/AI-Dev-Company"
        ),
        "default_branch": "main",
    }

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

    registered = registry.list_agents("co_ai_dev_company")

    assert len(registered) == 8
    assert {
        item["agent_id"] for item in registered
    } == {
        item["agent_id"] for item in DEFAULT_AGENTS
    }
