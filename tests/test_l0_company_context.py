from __future__ import annotations

import json
import sqlite3

import pytest

from company_os.context import (
    COMPANY_OPERATING_POLICIES,
    ContextBudgetExceeded,
    ContextCompilationError,
    compile_l0_company_context,
    validate_policy_catalog,
    write_context_packet,
)
from company_os.context.l0_cli import main as l0_cli_main
from company_os.foundation import FoundationService


@pytest.fixture
def founded_project(tmp_path):
    root = tmp_path / "AI-Dev-Company"
    root.mkdir()
    foundation = FoundationService(root)
    foundation.bootstrap(
        owner_name="Test Owner",
        owner_email="owner@example.com",
        actor="test-suite",
        reason="L0 context fixture",
    )
    return root, foundation


def test_l0_contains_canonical_company_project_and_exact_eight_specialists(
    founded_project,
):
    _, foundation = founded_project

    packet = compile_l0_company_context(foundation)

    assert packet["schema"] == "company-context.l0.v1"
    assert packet["level"] == "L0"
    assert packet["company"] == {
        "company_id": "co_ai_dev_company",
        "slug": "ai-dev-company",
        "name": "AI Software Engineering Company",
        "status": "active",
    }
    assert packet["primary_project"]["project_id"] == "prj_ai_dev_company"
    assert packet["primary_project"]["repository_url"] == (
        "https://github.com/imperiumsandy-commits/AI-Dev-Company"
    )
    assert packet["primary_project"]["default_branch"] == "main"
    assert packet["specialists"]["registered_count"] == 8
    assert [agent["agent_id"] for agent in packet["specialists"]["registered_agents"]] == [
        "agent_business_analyst_pm",
        "agent_system_architect",
        "agent_backend_developer",
        "agent_frontend_developer",
        "agent_database_administrator",
        "agent_cybersecurity_engineer",
        "agent_qa_bug_hunter",
        "agent_devops_engineer",
    ]


def test_l0_does_not_expose_owner_email_or_owner_contact_data(founded_project):
    _, foundation = founded_project

    packet = compile_l0_company_context(foundation)
    serialized = json.dumps(packet, sort_keys=True)

    assert "owner@example.com" not in serialized
    assert "owner_email" not in serialized


def test_policy_catalog_is_specific_ordered_and_discloses_enforcement_limits():
    validate_policy_catalog()

    policies = sorted(COMPANY_OPERATING_POLICIES, key=lambda item: item.priority)
    ids = [policy.policy_id for policy in policies]

    assert len(ids) == len(set(ids))
    assert "company.specialist_independence" in ids
    assert "delivery.github_is_source_of_truth" in ids
    assert "security.credential_boundary" in ids
    assert "governance.high_risk_owner_approval" in ids
    assert "repository.command_output_is_not_source" in ids
    assert all(policy.rule and policy.enforcement_state and policy.limitation for policy in policies)


def test_l0_reports_registry_registration_separately_from_specification_readiness(
    founded_project,
):
    _, foundation = founded_project

    packet = compile_l0_company_context(foundation)
    specifications = packet["specialists"]["specification_readiness"]

    assert len(specifications) == 8
    assert all(item["status"] == "missing_specification" for item in specifications)
    assert all("ROLE.md" in item["missing_required_specifications"] for item in specifications)
    assert "not necessarily specification-ready" in packet["specialists"]["activation_rule"]


def test_l0_compilation_is_deterministic_and_has_a_digest(founded_project):
    _, foundation = founded_project

    first = compile_l0_company_context(foundation)
    second = compile_l0_company_context(foundation)

    assert first == second
    assert len(first["packet_sha256"]) == 64
    assert first["budget"]["truncated"] is False
    assert first["budget"]["omitted_sections"] == []
    assert first["budget"]["estimated_context_tokens"] <= (
        first["budget"]["available_context_tokens"]
    )


def test_l0_compilation_does_not_append_memory_events(founded_project):
    _, foundation = founded_project
    before = foundation.memory.list_events(limit=200)

    compile_l0_company_context(foundation)

    after = foundation.memory.list_events(limit=200)
    assert after == before


def test_l0_refuses_to_compile_when_foundation_integrity_fails(founded_project):
    _, foundation = founded_project

    with sqlite3.connect(foundation.registry_path) as db:
        db.execute("DROP TRIGGER audit_events_no_update")
        db.execute(
            "UPDATE audit_events SET reason='tampered' WHERE event_id=1"
        )

    with pytest.raises(ContextCompilationError, match="foundation is invalid"):
        compile_l0_company_context(foundation)


def test_l0_refuses_an_empty_unbootstrapped_registry(tmp_path):
    root = tmp_path / "empty-project"
    root.mkdir()
    foundation = FoundationService(root)

    with pytest.raises(ContextCompilationError, match="foundation is invalid"):
        compile_l0_company_context(foundation)


def test_l0_never_silently_truncates_required_identity_or_policies(founded_project):
    _, foundation = founded_project

    with pytest.raises(ContextBudgetExceeded) as error:
        compile_l0_company_context(
            foundation,
            max_context_tokens=250,
            reserved_output_tokens=100,
        )

    assert error.value.estimated_tokens > error.value.available_tokens
    assert "not truncated" in str(error.value)


def test_l0_rejects_invalid_token_budget(founded_project):
    _, foundation = founded_project

    with pytest.raises(ContextCompilationError, match="smaller than"):
        compile_l0_company_context(
            foundation,
            max_context_tokens=100,
            reserved_output_tokens=100,
        )

    with pytest.raises(ContextCompilationError, match="must be an integer"):
        compile_l0_company_context(foundation, max_context_tokens=True)


def test_l0_packet_writer_is_valid_json_and_replaces_atomically(founded_project, tmp_path):
    _, foundation = founded_project
    packet = compile_l0_company_context(foundation)
    output = tmp_path / "runtime" / "l0-context.json"

    written = write_context_packet(packet, output)
    decoded = json.loads(written.read_text(encoding="utf-8"))

    assert written == output
    assert decoded == packet
    assert not list(output.parent.glob("*.tmp"))


def test_l0_writer_rejects_wrong_schema_or_missing_digest(tmp_path):
    output = tmp_path / "invalid.json"

    with pytest.raises(ContextCompilationError, match="unsupported L0 schema"):
        write_context_packet({"schema": "other"}, output)

    with pytest.raises(ContextCompilationError, match="without its integrity digest"):
        write_context_packet({"schema": "company-context.l0.v1"}, output)

    assert not output.exists()


def test_l0_writer_rejects_a_modified_packet_digest(founded_project, tmp_path):
    _, foundation = founded_project
    packet = compile_l0_company_context(foundation)
    packet["company"]["name"] = "Modified after compilation"
    output = tmp_path / "tampered.json"

    with pytest.raises(ContextCompilationError, match="digest does not match"):
        write_context_packet(packet, output)

    assert not output.exists()


def test_l0_cli_writes_context_packet_inside_repository(founded_project):
    root, _ = founded_project
    output = ".ai-dev-company/context/l0-company-context.json"

    result = l0_cli_main(["--root", str(root), "--output", output])

    assert result == 0
    packet_path = root / output
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    assert packet["level"] == "L0"
    assert packet["specialists"]["registered_count"] == 8


def test_l0_cli_rejects_output_outside_repository(founded_project, tmp_path):
    root, _ = founded_project
    outside = tmp_path / "outside.json"

    result = l0_cli_main(["--root", str(root), "--output", str(outside)])

    assert result == 2
    assert not outside.exists()
