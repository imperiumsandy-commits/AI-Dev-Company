from __future__ import annotations

import json

import pytest

from company_os.context import (
    ContextBudgetExceeded,
    L1ContextBudgetExceeded,
    L1ContextCompilationError,
    L1ContextSelectionLimitExceeded,
    L1ContextSensitiveDataError,
    compile_l1_project_context,
    write_l1_context_packet,
)
from company_os.context.l1_cli import main as l1_cli_main
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
        reason="L1 context fixture",
    )

    return root, foundation


def test_l1_includes_canonical_l0_and_all_seeded_project_knowledge(
    founded_project,
):
    _, foundation = founded_project

    packet = compile_l1_project_context(foundation)

    assert packet["schema"] == "company-context.l1.v1"
    assert packet["level"] == "L1"

    assert packet["parent_context"]["level"] == "L0"
    assert packet["parent_context"]["company"]["company_id"] == (
        "co_ai_dev_company"
    )
    assert packet["project"]["identity"]["project_id"] == (
        "prj_ai_dev_company"
    )

    knowledge = packet["project"]["knowledge"]

    assert knowledge["record_count"] == 4
    assert len(knowledge["by_kind"]["decision"]) == 1
    assert len(knowledge["by_kind"]["policy"]) == 2
    assert len(knowledge["by_kind"]["future_work"]) == 1

    decision = knowledge["by_kind"]["decision"][0]
    assert decision["title"] == "Eight independent specialist developers"

    assert packet["retrieval"]["complete"] is True
    assert packet["retrieval"]["omitted_records"] == 0
    assert packet["compiler_contract"]["memory_mutated"] is False


def test_l1_includes_new_requirements_and_task_acceptance_criteria(
    founded_project,
):
    _, foundation = founded_project

    foundation.memory.add_memory(
        scope="project",
        kind="requirement",
        title="Project continuity requirement",
        content=(
            "A new authorized development session must reconstruct "
            "the relevant project state from verified persistent records."
        ),
        source="owner",
        tags=["continuity", "foundation"],
    )

    task = foundation.memory.add_task(
        title="Implement project context compilation",
        description="Build the L1 context compiler.",
        agent_id="backend-developer",
        priority="high",
        acceptance_criteria=[
            "Include canonical project identity.",
            "Include project decisions and requirements.",
            "Reject incomplete retrieval.",
        ],
        next_action="Implement and run the L1 regression suite.",
    )

    packet = compile_l1_project_context(foundation)

    requirements = packet["project"]["knowledge"]["by_kind"]["requirement"]
    assert len(requirements) == 1
    assert requirements[0]["title"] == "Project continuity requirement"

    tasks = packet["project"]["task_backlog"]["tasks"]
    matching = [item for item in tasks if item["task_id"] == task["task_id"]]

    assert len(matching) == 1
    assert matching[0]["agent_id"] == "backend-developer"
    assert matching[0]["priority"] == "high"
    assert matching[0]["acceptance_criteria"] == [
        "Include canonical project identity.",
        "Include project decisions and requirements.",
        "Reject incomplete retrieval.",
    ]


def test_l1_is_deterministic_and_compilation_does_not_write_memory(
    founded_project,
):
    _, foundation = founded_project

    events_before = foundation.memory.list_events(limit=200)

    first = compile_l1_project_context(foundation)
    second = compile_l1_project_context(foundation)

    events_after = foundation.memory.list_events(limit=200)

    assert first == second
    assert events_before == events_after
    assert len(first["packet_sha256"]) == 64
    assert first["budget"]["truncated"] is False
    assert first["budget"]["omitted_sections"] == []
    assert first["budget"]["estimated_context_tokens"] <= (
        first["budget"]["available_context_tokens"]
    )


def test_l1_refuses_to_export_known_credential_patterns(founded_project):
    _, foundation = founded_project

    foundation.memory.add_memory(
        scope="project",
        kind="note",
        title="Unsafe diagnostic note",
        content="Temporary diagnostic value: ghp_" + ("A" * 36),
    )

    with pytest.raises(L1ContextSensitiveDataError) as error:
        compile_l1_project_context(foundation)

    assert "credential-like value" in str(error.value)
    assert "ghp_" not in str(error.value)


def test_l1_refuses_to_silently_truncate_project_memory(founded_project):
    _, foundation = founded_project

    for index in range(201):
        foundation.memory.add_memory(
            scope="project",
            kind="note",
            title=f"Project note {index:03d}",
            content=f"Persistent project note number {index}.",
        )

    with pytest.raises(
        L1ContextSelectionLimitExceeded,
        match="retrieval limit",
    ):
        compile_l1_project_context(foundation)


def test_l1_refuses_a_packet_that_exceeds_its_token_budget(founded_project):
    _, foundation = founded_project

    with pytest.raises(
        (
            L1ContextBudgetExceeded,
            ContextBudgetExceeded,
        )
    ):
        compile_l1_project_context(
            foundation,
            max_context_tokens=2000,
            reserved_output_tokens=1000,
        )


def test_l1_writer_validates_digest_and_writes_atomic_json(
    founded_project,
    tmp_path,
):
    _, foundation = founded_project

    packet = compile_l1_project_context(foundation)
    output = tmp_path / "runtime" / "l1-project-context.json"

    written = write_l1_context_packet(packet, output)
    decoded = json.loads(written.read_text(encoding="utf-8"))

    assert written == output
    assert decoded == packet
    assert not list(output.parent.glob("*.tmp"))


def test_l1_writer_rejects_modified_packet_digest(
    founded_project,
    tmp_path,
):
    _, foundation = founded_project

    packet = compile_l1_project_context(foundation)
    packet["project"]["identity"]["name"] = "Tampered project name"

    output = tmp_path / "tampered.json"

    with pytest.raises(
        L1ContextCompilationError,
        match="digest does not match",
    ):
        write_l1_context_packet(packet, output)

    assert not output.exists()


def test_l1_cli_writes_context_inside_repository(founded_project):
    root, _ = founded_project
    output = ".ai-dev-company/context/l1-project-context.json"

    result = l1_cli_main([
        "--root",
        str(root),
        "--output",
        output,
    ])

    assert result == 0

    packet_path = root / output
    packet = json.loads(packet_path.read_text(encoding="utf-8"))

    assert packet["level"] == "L1"
    assert packet["project"]["identity"]["project_id"] == (
        "prj_ai_dev_company"
    )


def test_l1_cli_rejects_output_outside_repository(
    founded_project,
    tmp_path,
):
    root, _ = founded_project
    outside = tmp_path / "outside-context.json"

    result = l1_cli_main([
        "--root",
        str(root),
        "--output",
        str(outside),
    ])

    assert result == 2
    assert not outside.exists()
