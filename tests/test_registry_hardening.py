"""Acceptance tests for the public F01 registry contract and safety rules."""
from __future__ import annotations

import json
import sqlite3

import pytest

from company_os.registry import RegistryStore, ValidationError
from company_os.registry.catalog import DEFAULT_AGENTS


CANONICAL_COMPANY = {
    "company_id": "co_ai_dev_company",
    "slug": "ai-dev-company",
    "name": "AI Software Engineering Company",
    "owner_name": "Owner",
    "owner_email": "owner@example.com",
}
CANONICAL_PROJECT = {
    "project_id": "prj_ai_dev_company",
    "company_id": "co_ai_dev_company",
    "slug": "ai-dev-company",
    "name": "AI-Dev-Company",
    "repository_url": "https://github.com/imperiumsandy-commits/AI-Dev-Company",
    "default_branch": "main",
}


@pytest.fixture
def registry(tmp_path):
    return RegistryStore(tmp_path / "registry.sqlite3")


def bootstrap(registry):
    return registry.bootstrap(
        company=dict(CANONICAL_COMPANY),
        project=dict(CANONICAL_PROJECT),
        agents=DEFAULT_AGENTS,
        actor="owner:test",
        reason="registry hardening test",
    )


def _generic_agent_specs():
    result = []
    for index, source in enumerate(DEFAULT_AGENTS):
        item = dict(source)
        item.update(
            agent_id=f"agent_generic_{index}",
            slug=f"specialist-{index}",
            display_name=f"Specialist {index}",
            domain=f"domain-{index}",
            definition_path=f"agents/specialist-{index}/agent.yaml",
        )
        item["capabilities"] = [f"capability_{index}"]
        result.append(item)
    return result


def test_canonical_bootstrap_rejects_changed_specialist_contract(registry):
    changed = [dict(item) for item in DEFAULT_AGENTS]
    changed[0]["domain"] = "generic-domain"

    with pytest.raises(ValidationError, match="canonical eight-agent catalog"):
        registry.bootstrap(
            company=dict(CANONICAL_COMPANY),
            project=dict(CANONICAL_PROJECT),
            agents=changed,
            actor="owner:test",
            reason="reject altered catalog",
        )

    with sqlite3.connect(registry.path) as db:
        assert db.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM agents").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 0


def test_mid_transaction_bootstrap_failure_leaves_no_partial_records(registry):
    agents = _generic_agent_specs()
    agents[-1]["capabilities"] = []

    with pytest.raises(ValidationError, match="non-empty"):
        registry.bootstrap(
            company={
                "company_id": "co_atomic",
                "slug": "atomic-company",
                "name": "Atomic Company",
                "owner_name": "Owner",
                "owner_email": "owner@example.com",
            },
            project={
                "project_id": "prj_atomic",
                "company_id": "co_atomic",
                "slug": "atomic-project",
                "name": "Atomic Project",
                "repository_url": "https://github.com/example/atomic",
                "default_branch": "main",
            },
            agents=agents,
            actor="test-suite",
            reason="force final agent validation failure",
        )

    with sqlite3.connect(registry.path) as db:
        for table in ("companies", "projects", "agents", "audit_events"):
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_idempotent_bootstrap_preserves_agent_lifecycle_state(registry):
    bootstrap(registry)
    registry.transition_status(
        entity_type="agent",
        entity_id="agent_backend_developer",
        new_status="active",
        expected_version=1,
        actor="owner:test",
        reason="activation evaluation passed",
    )

    retry = bootstrap(registry)

    assert retry["idempotent"] is True
    agent = next(
        row for row in registry.list_agents("co_ai_dev_company")
        if row["agent_id"] == "agent_backend_developer"
    )
    assert agent["status"] == "active"
    assert agent["version"] == 2


def test_nested_secret_configuration_is_rejected_before_write(registry):
    registry.register_company(
        company_id="co_test",
        slug="test-company",
        name="Test Company",
        owner_name="Owner",
        owner_email="owner@example.com",
        actor="test",
        reason="fixture",
    )

    with pytest.raises(ValidationError, match="Credential-like data"):
        registry.set_configuration(
            scope_type="company",
            scope_id="co_test",
            config_key="provider_settings",
            value={"provider": {"api_key": "not-for-storage"}},
            actor="owner",
            reason="must reject nested credential field",
        )

    with sqlite3.connect(registry.path) as db:
        assert db.execute("SELECT COUNT(*) FROM configurations").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 1


def test_known_token_material_is_rejected_even_without_secret_key_name(registry):
    registry.register_company(
        company_id="co_test",
        slug="test-company",
        name="Test Company",
        owner_name="Owner",
        owner_email="owner@example.com",
        actor="test",
        reason="fixture",
    )

    with pytest.raises(ValidationError, match="Credential-like data"):
        registry.set_configuration(
            scope_type="company",
            scope_id="co_test",
            config_key="provider_settings",
            value="ghp_" + ("A" * 36),
            actor="owner",
            reason="must reject token-shaped value",
        )


def test_token_budget_is_not_mistaken_for_a_secret(registry):
    registry.register_company(
        company_id="co_test",
        slug="test-company",
        name="Test Company",
        owner_name="Owner",
        owner_email="owner@example.com",
        actor="test",
        reason="fixture",
    )

    saved = registry.set_configuration(
        scope_type="company",
        scope_id="co_test",
        config_key="token_budget",
        value={"max_tokens": 12000},
        actor="owner",
        reason="configure context budget",
    )

    assert saved["version"] == 1
    assert registry.get_configuration(
        scope_type="company",
        scope_id="co_test",
        config_key="token_budget",
    )["value"] == {"max_tokens": 12000}


def test_approved_secret_manager_reference_can_be_stored(registry):
    registry.register_company(
        company_id="co_test",
        slug="test-company",
        name="Test Company",
        owner_name="Owner",
        owner_email="owner@example.com",
        actor="test",
        reason="fixture",
    )

    saved = registry.set_configuration(
        scope_type="company",
        scope_id="co_test",
        config_key="provider_secret_ref",
        value="vault://company/provider/openai",
        actor="owner",
        reason="reference external secret manager",
    )

    assert saved["value"] == "vault://company/provider/openai"


def test_project_lifecycle_rejects_backward_transition(registry):
    registry.register_company(
        company_id="co_test",
        slug="test-company",
        name="Test Company",
        owner_name="Owner",
        owner_email="owner@example.com",
        actor="test",
        reason="fixture",
    )
    registry.register_project(
        project_id="prj_test",
        company_id="co_test",
        slug="test-project",
        name="Test Project",
        repository_url="https://github.com/example/test-project",
        default_branch="main",
        actor="test",
        reason="fixture",
    )
    registry.transition_status(
        entity_type="project",
        entity_id="prj_test",
        new_status="paused",
        expected_version=1,
        actor="owner",
        reason="pause project",
    )

    with pytest.raises(ValidationError, match="Illegal project transition"):
        registry.transition_status(
            entity_type="project",
            entity_id="prj_test",
            new_status="planned",
            expected_version=2,
            actor="owner",
            reason="invalid rollback",
        )

    assert registry.list_projects("co_test")[0]["status"] == "paused"


def test_agent_retirement_is_terminal(registry):
    registry.register_company(
        company_id="co_test",
        slug="test-company",
        name="Test Company",
        owner_name="Owner",
        owner_email="owner@example.com",
        actor="test",
        reason="fixture",
    )
    registry.register_agent(
        agent_id="agent_test",
        company_id="co_test",
        slug="test-agent",
        display_name="Test Agent",
        domain="testing",
        definition_path="agents/test/ROLE.md",
        role_version="1.0.0",
        capabilities=["test_execution"],
        actor="test",
        reason="fixture",
    )
    registry.transition_status(
        entity_type="agent",
        entity_id="agent_test",
        new_status="retired",
        expected_version=1,
        actor="owner",
        reason="retire agent",
    )

    with pytest.raises(ValidationError, match="Illegal agent transition"):
        registry.transition_status(
            entity_type="agent",
            entity_id="agent_test",
            new_status="active",
            expected_version=2,
            actor="owner",
            reason="cannot reactivate retired agent",
        )


def test_validator_checks_every_canonical_agent_field(registry):
    bootstrap(registry)
    with sqlite3.connect(registry.path) as db:
        db.execute(
            "UPDATE agents SET display_name=? WHERE agent_id=?",
            ("Generic Developer", "agent_backend_developer"),
        )

    report = registry.validate("co_ai_dev_company")

    assert report["valid"] is False
    assert report["contract_validation"]["canonical_catalog_valid"] is False
    assert any("display_name" in issue for issue in report["issues"])


def test_validator_detects_removed_append_only_trigger(registry):
    bootstrap(registry)
    with sqlite3.connect(registry.path) as db:
        db.execute("DROP TRIGGER audit_events_no_delete")

    report = registry.validate("co_ai_dev_company")

    assert report["valid"] is False
    assert any("append-only protection" in issue for issue in report["issues"])


def test_validator_detects_dangling_configuration_scope(registry):
    registry.register_company(
        company_id="co_test",
        slug="test-company",
        name="Test Company",
        owner_name="Owner",
        owner_email="owner@example.com",
        actor="test",
        reason="fixture",
    )
    with sqlite3.connect(registry.path) as db:
        db.execute(
            """INSERT INTO configurations
            VALUES('project','prj_missing','feature_flags','{}',1,'test','now')"""
        )

    report = registry.validate("co_test")

    assert report["valid"] is False
    assert report["contract_validation"]["configuration_scopes_valid"] is False


def test_validator_detects_invalid_configuration_json(registry):
    registry.register_company(
        company_id="co_test",
        slug="test-company",
        name="Test Company",
        owner_name="Owner",
        owner_email="owner@example.com",
        actor="test",
        reason="fixture",
    )
    registry.set_configuration(
        scope_type="company",
        scope_id="co_test",
        config_key="feature_flags",
        value={"safe": True},
        actor="owner",
        reason="fixture",
    )
    with sqlite3.connect(registry.path) as db:
        db.execute(
            "UPDATE configurations SET value_json='not-json' WHERE config_key='feature_flags'"
        )

    report = registry.validate("co_test")

    assert report["valid"] is False
    assert report["contract_validation"]["configuration_values_valid"] is False


def test_validator_detects_credentials_in_legacy_configuration(registry):
    registry.register_company(
        company_id="co_test",
        slug="test-company",
        name="Test Company",
        owner_name="Owner",
        owner_email="owner@example.com",
        actor="test",
        reason="fixture",
    )
    with sqlite3.connect(registry.path) as db:
        db.execute(
            """INSERT INTO configurations
            VALUES('company','co_test','provider_settings',?,?, 'test','now')""",
            (json.dumps({"api_key": "legacy-credential"}), 1),
        )

    report = registry.validate("co_test")

    assert report["valid"] is False
    assert report["contract_validation"]["configuration_values_valid"] is False


def test_validator_scans_legacy_audit_payloads_for_credentials(registry):
    from company_os.registry.core import RegistryStore as CoreRegistryStore

    legacy = CoreRegistryStore(registry.path)
    legacy.register_company(
        company_id="co_test",
        slug="test-company",
        name="Test Company",
        owner_name="Owner",
        owner_email="owner@example.com",
        actor="test",
        reason="fixture",
    )
    # The old adapter allowed nested credential fields and copied them into
    # the immutable audit payload. The hardened service must detect both.
    legacy.set_configuration(
        scope_type="company",
        scope_id="co_test",
        config_key="provider_settings",
        value={"provider": {"api_key": "legacy-credential"}},
        actor="owner",
        reason="legacy behaviour simulation",
    )

    report = registry.validate("co_test")

    assert report["valid"] is False
    assert any("audit history contains credential-like data" in issue for issue in report["issues"])


def test_validator_rejects_noop_trigger_with_expected_name(registry):
    bootstrap(registry)
    with sqlite3.connect(registry.path) as db:
        db.execute("DROP TRIGGER audit_events_no_delete")
        db.execute(
            """CREATE TRIGGER audit_events_no_delete
            BEFORE DELETE ON audit_events
            BEGIN SELECT 1; END"""
        )

    report = registry.validate("co_ai_dev_company")

    assert report["valid"] is False
    assert report["contract_validation"]["append_only_triggers_valid"] is False
