
import sqlite3
import pytest

from company_os.registry import (
    AgentRegistry,
    CompanyRegistry,
    ProjectRegistry,
    RegistryStore,
    Conflict,
    IntegrityViolation,
    NotFound,
    ValidationError,
)
from company_os.registry.catalog import DEFAULT_AGENTS


@pytest.fixture
def registry(tmp_path):
    return RegistryStore(tmp_path / "registry.sqlite3")


def company(registry):
    return registry.register_company(
        company_id="co_test",
        slug="test-company",
        name="Test Company",
        owner_name="Owner",
        owner_email="owner@example.com",
        actor="test-suite",
        reason="fixture",
    )


def bootstrap(registry):
    return registry.bootstrap(
        company={
            "company_id": "co_ai_dev_company",
            "slug": "ai-dev-company",
            "name": "AI Software Engineering Company",
            "owner_name": "Sandip",
            "owner_email": "imperium.sandy@gmail.com",
        },
        project={
            "project_id": "prj_ai_dev_company",
            "company_id": "co_ai_dev_company",
            "slug": "ai-dev-company",
            "name": "AI-Dev-Company",
            "repository_url": "https://github.com/imperiumsandy-commits/AI-Dev-Company",
            "default_branch": "main",
        },
        agents=DEFAULT_AGENTS,
        actor="owner:imperiumsandy-commits",
        reason="initial bootstrap",
    )


def test_company_registration_and_read(registry):
    assert company(registry)["version"] == 1
    assert registry.get_company("co_test")["owner_email"] == "owner@example.com"


def test_duplicate_company_identity_rejected(registry):
    company(registry)
    with pytest.raises(Conflict):
        company(registry)


def test_invalid_company_id_rejected(registry):
    with pytest.raises(ValidationError):
        registry.register_company(
            company_id="Bad ID",
            slug="test",
            name="Test",
            owner_name="Owner",
            owner_email="owner@example.com",
            actor="test",
            reason="invalid id",
        )


def test_project_requires_existing_company(registry):
    with pytest.raises(NotFound):
        registry.register_project(
            project_id="prj_missing",
            company_id="co_missing",
            slug="missing",
            name="Missing",
            repository_url="https://github.com/example/missing",
            default_branch="main",
            actor="test",
            reason="no parent",
        )


def test_project_registration_and_listing(registry):
    company(registry)
    registry.register_project(
        project_id="prj_one",
        company_id="co_test",
        slug="one",
        name="One",
        repository_url="https://github.com/example/one",
        default_branch="main",
        actor="test",
        reason="create",
    )
    assert registry.list_projects("co_test")[0]["project_id"] == "prj_one"


def test_agent_registration_and_capability_serialization(registry):
    company(registry)
    agent = registry.register_agent(
        agent_id="agent_backend",
        company_id="co_test",
        slug="backend",
        display_name="Backend Developer",
        domain="backend",
        definition_path="agents/backend/agent.yaml",
        role_version="1.0.0",
        capabilities=["api", "testing"],
        actor="test",
        reason="register",
    )
    assert agent["capabilities"] == ["api", "testing"]
    assert registry.list_agents("co_test")[0]["agent_id"] == "agent_backend"


def test_duplicate_agent_capability_rejected(registry):
    company(registry)
    with pytest.raises(ValidationError):
        registry.register_agent(
            agent_id="agent_backend",
            company_id="co_test",
            slug="backend",
            display_name="Backend",
            domain="backend",
            definition_path="agents/backend/agent.yaml",
            role_version="1.0.0",
            capabilities=["api", "api"],
            actor="test",
            reason="duplicate",
        )


def test_config_create_and_versioned_update(registry):
    company(registry)
    first = registry.set_configuration(
        scope_type="company",
        scope_id="co_test",
        config_key="token_budget",
        value={"max_tokens": 12000},
        actor="owner",
        reason="initial",
        expected_version=0,
    )
    second = registry.set_configuration(
        scope_type="company",
        scope_id="co_test",
        config_key="token_budget",
        value={"max_tokens": 9000},
        actor="owner",
        reason="reduced",
        expected_version=1,
    )
    assert (first["version"], second["version"]) == (1, 2)


def test_stale_config_update_rejected(registry):
    company(registry)
    registry.set_configuration(
        scope_type="company",
        scope_id="co_test",
        config_key="mode",
        value="safe",
        actor="owner",
        reason="create",
        expected_version=0,
    )
    with pytest.raises(Conflict):
        registry.set_configuration(
            scope_type="company",
            scope_id="co_test",
            config_key="mode",
            value="unsafe",
            actor="owner",
            reason="stale",
            expected_version=0,
        )


def test_secret_like_config_key_rejected(registry):
    company(registry)
    with pytest.raises(ValidationError):
        registry.set_configuration(
            scope_type="company",
            scope_id="co_test",
            config_key="provider.api_key",
            value="must-not-be-stored",
            actor="owner",
            reason="secret policy",
        )


def test_project_status_transition_uses_versions(registry):
    company(registry)
    registry.register_project(
        project_id="prj_one",
        company_id="co_test",
        slug="one",
        name="One",
        repository_url="https://github.com/example/one",
        default_branch="main",
        actor="test",
        reason="create",
    )
    updated = registry.transition_status(
        entity_type="project",
        entity_id="prj_one",
        new_status="paused",
        expected_version=1,
        actor="owner",
        reason="maintenance",
    )
    assert updated["version"] == 2

    with pytest.raises(Conflict):
        registry.transition_status(
            entity_type="project",
            entity_id="prj_one",
            new_status="active",
            expected_version=1,
            actor="owner",
            reason="stale",
        )


def test_bootstrap_registers_eight_specialists_atomically(registry):
    result = bootstrap(registry)
    assert result["created"] == {
        "company": True,
        "project": True,
        "agents": 8,
    }
    assert len(registry.list_agents("co_ai_dev_company")) == 8
    assert registry.validate("co_ai_dev_company")["valid"] is True


def test_bootstrap_identical_retry_is_idempotent(registry):
    bootstrap(registry)
    result = bootstrap(registry)
    assert result["idempotent"] is True
    assert result["created"] == {
        "company": False,
        "project": False,
        "agents": 0,
    }


def test_bootstrap_mismatch_rolls_back(registry):
    bootstrap(registry)

    with pytest.raises(IntegrityViolation):
        registry.bootstrap(
            company={
                "company_id": "co_ai_dev_company",
                "slug": "ai-dev-company",
                "name": "Wrong Name",
                "owner_name": "Sandip",
                "owner_email": "imperium.sandy@gmail.com",
            },
            project={
                "project_id": "prj_ai_dev_company",
                "company_id": "co_ai_dev_company",
                "slug": "ai-dev-company",
                "name": "AI-Dev-Company",
                "repository_url": "https://github.com/imperiumsandy-commits/AI-Dev-Company",
                "default_branch": "main",
            },
            agents=DEFAULT_AGENTS,
            actor="owner:test",
            reason="mismatch",
        )

    assert registry.get_company("co_ai_dev_company")["name"] == (
        "AI Software Engineering Company"
    )


def test_audit_chain_and_append_only_triggers(registry):
    company(registry)
    assert registry.verify_audit_chain()["valid"] is True

    with sqlite3.connect(registry.path) as db:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute(
                "UPDATE audit_events SET reason='tampered' WHERE event_id=1"
            )

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute(
                "DELETE FROM audit_events WHERE event_id=1"
            )


def test_hash_chain_detects_tampering_if_trigger_is_removed(registry):
    company(registry)

    with sqlite3.connect(registry.path) as db:
        db.execute("DROP TRIGGER audit_events_no_update")
        db.execute(
            "UPDATE audit_events SET reason='tampered' WHERE event_id=1"
        )

    result = registry.verify_audit_chain()
    assert result["valid"] is False
    assert result["reason"] == "event hash mismatch"


def test_mutations_require_actor_and_reason(registry):
    with pytest.raises(ValidationError):
        registry.register_company(
            company_id="co_test",
            slug="test",
            name="Test",
            owner_name="Owner",
            owner_email="owner@example.com",
            actor=" ",
            reason="invalid actor",
        )


def test_configuration_read_returns_decoded_value(registry):
    company(registry)
    registry.set_configuration(
        scope_type="company",
        scope_id="co_test",
        config_key="limits",
        value={"max_tasks": 5},
        actor="owner",
        reason="set limits",
        expected_version=0,
    )

    result = registry.get_configuration(
        scope_type="company",
        scope_id="co_test",
        config_key="limits",
    )
    assert result["value"] == {"max_tasks": 5}
    assert result["version"] == 1


def test_audit_event_listing_is_scoped_and_decodes_payload(registry):
    company(registry)
    events = registry.list_audit_events(company_id="co_test")

    assert len(events) == 1
    assert events[0]["action"] == "company.registered"
    assert events[0]["payload"]["slug"] == "test-company"


def test_domain_registry_facades_share_the_store(registry):
    companies = CompanyRegistry(registry)
    projects = ProjectRegistry(registry)
    agents = AgentRegistry(registry)

    companies.register(
        company_id="co_facade",
        slug="facade-company",
        name="Facade Company",
        owner_name="Owner",
        owner_email="owner@example.com",
        actor="test",
        reason="facade test",
    )

    projects.register(
        project_id="prj_facade",
        company_id="co_facade",
        slug="facade-project",
        name="Facade Project",
        repository_url="https://github.com/example/facade",
        default_branch="main",
        actor="test",
        reason="facade project",
    )

    agents.register(
        agent_id="agent_facade",
        company_id="co_facade",
        slug="facade-agent",
        display_name="Facade Agent",
        domain="testing",
        definition_path="agents/facade/agent.yaml",
        role_version="1.0.0",
        capabilities=["test_execution"],
        actor="test",
        reason="facade agent",
    )

    assert companies.get("co_facade")["name"] == "Facade Company"
    assert projects.list_for_company("co_facade")[0]["project_id"] == "prj_facade"
    assert agents.list_for_company("co_facade")[0]["agent_id"] == "agent_facade"
