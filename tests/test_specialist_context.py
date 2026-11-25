from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ai_dev_company.agent_loader import load_agent
from ai_dev_company.memory_store import AGENT_IDS
from company_os.context import (
    L2ContextCompilationError,
    L2SpecialistTaskOwnershipError,
    compile_l2_specialist_context,
    write_l2_context_packet,
)
from company_os.context.l2_cli import main as l2_cli_main
from company_os.foundation import FoundationService
from company_os.registry.catalog import DEFAULT_AGENTS


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _copy_agent_specs(destination: Path) -> None:
    for spec in DEFAULT_AGENTS:
        slug = spec["slug"]
        source = (
            REPOSITORY_ROOT
            / "agents"
            / slug
            / "agent.yaml"
        )
        target_dir = destination / "agents" / slug
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target_dir / "agent.yaml")


@pytest.fixture
def founded_project(tmp_path):
    root = tmp_path / "AI-Dev-Company"
    root.mkdir()

    foundation = FoundationService(root)
    foundation.bootstrap(
        owner_name="Test Owner",
        owner_email="owner@example.com",
        actor="test-suite",
        reason="L2 specialist fixture",
    )

    _copy_agent_specs(root)
    return root, foundation


def test_all_eight_specialist_manifests_match_the_canonical_catalog(
    founded_project,
):
    root, _ = founded_project

    assert len(AGENT_IDS) == 8

    loaded = [
        load_agent(root, agent_id)
        for agent_id in AGENT_IDS
    ]

    assert all(item["status"] == "ready_to_load" for item in loaded)
    assert all(
        item["missing_required_specifications"] == []
        for item in loaded
    )
    assert all(item["manifest_sha256"] for item in loaded)

    domains = {
        item["manifest"]["domain"]
        for item in loaded
    }
    missions = {
        item["manifest"]["mission"]
        for item in loaded
    }

    assert len(domains) == 8
    assert len(missions) == 8


def test_l2_context_contains_one_specialist_and_validated_l1_parent(
    founded_project,
):
    _, foundation = founded_project

    packet = compile_l2_specialist_context(
        foundation,
        "backend-developer",
    )

    specialist = packet["specialist"]

    assert packet["schema"] == "company-context.l2.v1"
    assert packet["level"] == "L2"
    assert packet["parent_context"]["level"] == "L1"
    assert specialist["identity"]["slug"] == "backend-developer"
    assert specialist["identity"]["display_name"] == "Backend Developer"
    assert specialist["specification"]["domain"] == "backend-engineering"
    assert specialist["specification"]["capabilities"] == [
        "api_implementation",
        "service_logic",
        "integration",
        "backend_testing",
    ]

    assert packet["execution_boundary"]["specialist_registered"] is True
    assert packet["execution_boundary"]["specification_validated"] is True
    assert packet["execution_boundary"]["runtime_implemented"] is False
    assert packet["execution_boundary"]["agent_active"] is False
    assert packet["execution_boundary"]["tool_access_granted"] is False


def test_l2_task_scope_includes_only_the_selected_agent_and_dependencies(
    founded_project,
):
    _, foundation = founded_project

    dependency = foundation.memory.add_task(
        title="Create backend contract",
        agent_id="backend-developer",
        acceptance_criteria=["API contract is versioned."],
    )
    task = foundation.memory.add_task(
        title="Implement backend endpoint",
        agent_id="backend-developer",
        depends_on=[dependency["task_id"]],
        acceptance_criteria=[
            "Endpoint follows the approved contract.",
            "Negative inputs are tested.",
        ],
    )

    packet = compile_l2_specialist_context(
        foundation,
        "backend-developer",
        task_id=task["task_id"],
    )

    scope = packet["specialist"]["task_scope"]

    assert scope["mode"] == "single_task"
    assert scope["selected_task"]["task_id"] == task["task_id"]
    assert scope["owned_task_count"] == 1
    assert len(scope["direct_dependencies"]) == 1
    assert scope["direct_dependencies"][0]["task_id"] == (
        dependency["task_id"]
    )


def test_l2_refuses_to_compile_a_task_owned_by_another_specialist(
    founded_project,
):
    _, foundation = founded_project

    task = foundation.memory.add_task(
        title="Design system architecture",
        agent_id="system-architect",
        acceptance_criteria=["Architecture decision is recorded."],
    )

    with pytest.raises(L2SpecialistTaskOwnershipError, match="belongs to"):
        compile_l2_specialist_context(
            foundation,
            "backend-developer",
            task_id=task["task_id"],
        )


def test_l2_specialist_queue_contains_only_its_assigned_tasks(
    founded_project,
):
    _, foundation = founded_project

    backend_task = foundation.memory.add_task(
        title="Backend-owned task",
        agent_id="backend-developer",
    )
    foundation.memory.add_task(
        title="Frontend-owned task",
        agent_id="frontend-developer",
    )

    packet = compile_l2_specialist_context(
        foundation,
        "backend-developer",
    )

    scope = packet["specialist"]["task_scope"]

    assert scope["mode"] == "specialist_queue"
    assert [
        item["task_id"]
        for item in scope["owned_tasks"]
    ] == [backend_task["task_id"]]


def test_l2_refuses_a_missing_specialist_manifest(founded_project):
    root, foundation = founded_project

    manifest = (
        root
        / "agents"
        / "devops-engineer"
        / "agent.yaml"
    )
    manifest.unlink()

    loaded = load_agent(root, "devops-engineer")
    assert loaded["status"] == "missing_specification"

    with pytest.raises(
        L2ContextCompilationError,
        match="not specification-ready",
    ):
        compile_l2_specialist_context(
            foundation,
            "devops-engineer",
        )


def test_l2_refuses_a_malformed_or_identity_tampered_manifest(
    founded_project,
):
    root, foundation = founded_project

    manifest_path = (
        root
        / "agents"
        / "system-architect"
        / "agent.yaml"
    )
    manifest = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )
    manifest["registry_agent_id"] = "agent_backend_developer"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    loaded = load_agent(root, "system-architect")
    assert loaded["status"] == "invalid_specification"

    with pytest.raises(
        L2ContextCompilationError,
        match="not specification-ready",
    ):
        compile_l2_specialist_context(
            foundation,
            "system-architect",
        )


def test_l2_compilation_is_deterministic_and_does_not_write_memory(
    founded_project,
):
    _, foundation = founded_project
    before = foundation.memory.list_events(limit=200)

    first = compile_l2_specialist_context(
        foundation,
        "cybersecurity-engineer",
    )
    second = compile_l2_specialist_context(
        foundation,
        "cybersecurity-engineer",
    )

    after = foundation.memory.list_events(limit=200)

    assert first == second
    assert before == after
    assert len(first["packet_sha256"]) == 64
    assert first["budget"]["truncated"] is False
    assert first["budget"]["omitted_sections"] == []


def test_l2_writer_checks_digest_and_writes_complete_packet(
    founded_project,
    tmp_path,
):
    _, foundation = founded_project

    packet = compile_l2_specialist_context(
        foundation,
        "qa-bug-hunter",
    )
    output = tmp_path / "runtime" / "l2-qa.json"

    written = write_l2_context_packet(packet, output)
    decoded = json.loads(written.read_text(encoding="utf-8"))

    assert written == output
    assert decoded == packet
    assert not list(output.parent.glob("*.tmp"))


def test_l2_writer_rejects_packet_modified_after_compilation(
    founded_project,
    tmp_path,
):
    _, foundation = founded_project

    packet = compile_l2_specialist_context(
        foundation,
        "database-administrator",
    )
    packet["specialist"]["specification"]["mission"] = (
        "Modified after compilation"
    )

    output = tmp_path / "tampered-l2.json"

    with pytest.raises(
        L2ContextCompilationError,
        match="digest does not match",
    ):
        write_l2_context_packet(packet, output)

    assert not output.exists()


def test_l2_rejects_invalid_token_budget_before_compilation(
    founded_project,
):
    _, foundation = founded_project

    with pytest.raises(
        L2ContextCompilationError,
        match="smaller than",
    ):
        compile_l2_specialist_context(
            foundation,
            "devops-engineer",
            max_context_tokens=100,
            reserved_output_tokens=100,
        )


def test_l2_cli_writes_context_inside_repository(founded_project):
    root, _ = founded_project
    output = ".ai-dev-company/context/backend-specialist.json"

    result = l2_cli_main([
        "--root",
        str(root),
        "--agent",
        "backend-developer",
        "--output",
        output,
    ])

    assert result == 0
    packet = json.loads(
        (root / output).read_text(encoding="utf-8")
    )
    assert packet["level"] == "L2"
    assert packet["specialist"]["identity"]["slug"] == (
        "backend-developer"
    )


def test_l2_cli_rejects_output_outside_repository(
    founded_project,
    tmp_path,
):
    root, _ = founded_project
    outside = tmp_path / "outside-l2.json"

    result = l2_cli_main([
        "--root",
        str(root),
        "--agent",
        "backend-developer",
        "--output",
        str(outside),
    ])

    assert result == 2
    assert not outside.exists()
