import sqlite3

import pytest

from ai_dev_company.memory_store import MemoryStore
from company_os.foundation import (
    CURRENT_DELIVERY_POLICY_TITLE,
    LEGACY_DELIVERY_POLICY_TITLE,
    COMPANY_ID,
    PROJECT_ID,
    FoundationConflict,
    FoundationIntegrityError,
    FoundationService,
)


@pytest.fixture
def project_root(tmp_path):
    root = tmp_path / "AI-Dev-Company"
    root.mkdir()
    return root


def bootstrap(service):
    return service.bootstrap(
        owner_name="Test Owner",
        owner_email="owner@example.com",
        actor="test-suite",
        reason="integration test",
    )


def test_legacy_memory_migration_archives_old_policy_without_deleting_it(
    project_root,
):
    legacy_store = MemoryStore(root=project_root)

    with sqlite3.connect(legacy_store.db_path) as db:
        old_before = db.execute(
            """
            SELECT content,source,archived
            FROM memories
            WHERE title=?
            """,
            (LEGACY_DELIVERY_POLICY_TITLE,),
        ).fetchone()

    assert old_before is not None
    assert old_before[2] == 0

    service = FoundationService(project_root)

    with sqlite3.connect(service.memory.db_path) as db:
        old_after = db.execute(
            """
            SELECT content,source,archived
            FROM memories
            WHERE title=?
            """,
            (LEGACY_DELIVERY_POLICY_TITLE,),
        ).fetchone()

        replacement_count = db.execute(
            """
            SELECT COUNT(*)
            FROM memories
            WHERE title=? AND archived=0
            """,
            (CURRENT_DELIVERY_POLICY_TITLE,),
        ).fetchone()[0]

        migration_version = db.execute(
            "SELECT MAX(version) FROM foundation_migrations"
        ).fetchone()[0]

    assert old_after is not None
    assert old_after[0] == old_before[0]
    assert old_after[1] == old_before[1]
    assert old_after[2] == 1
    assert replacement_count == 1
    assert migration_version == 1


def test_memory_foundation_migration_is_idempotent(project_root):
    first = FoundationService(project_root)
    second = FoundationService(project_root)

    with sqlite3.connect(first.memory.db_path) as db:
        replacement_count = db.execute(
            """
            SELECT COUNT(*)
            FROM memories
            WHERE title=? AND archived=0
            """,
            (CURRENT_DELIVERY_POLICY_TITLE,),
        ).fetchone()[0]

        migration_count = db.execute(
            "SELECT COUNT(*) FROM foundation_migrations WHERE version=1"
        ).fetchone()[0]

    assert replacement_count == 1
    assert migration_count == 1
    assert second.validate()["memory"]["foundation_migration_version"] == 1


def test_bootstrap_integrates_company_project_and_eight_specialists(
    project_root,
):
    service = FoundationService(project_root)

    result = bootstrap(service)

    assert result["validation"]["valid"] is True
    assert result["registry_bootstrap"]["company_id"] == COMPANY_ID
    assert result["registry_bootstrap"]["project_id"] == PROJECT_ID
    assert result["validation"]["registered_agent_count"] == 8
    assert result["memory_binding"]["valid"] is True

    registry_agents = service.registry.list_agents(COMPANY_ID)
    registered_ids = {agent["agent_id"] for agent in registry_agents}

    assert len(registered_ids) == 8
    assert registered_ids == {
        "agent_business_analyst_pm",
        "agent_system_architect",
        "agent_backend_developer",
        "agent_frontend_developer",
        "agent_database_administrator",
        "agent_cybersecurity_engineer",
        "agent_qa_bug_hunter",
        "agent_devops_engineer",
    }


def test_repeated_bootstrap_is_idempotent(project_root):
    service = FoundationService(project_root)

    first = bootstrap(service)
    second = bootstrap(service)

    assert first["validation"]["valid"] is True
    assert second["validation"]["valid"] is True
    assert second["registry_bootstrap"]["idempotent"] is True
    assert second["memory_binding"]["idempotent"] is True

    assert len(service.registry.list_agents(COMPANY_ID)) == 8
    assert len(service.registry.list_projects(COMPANY_ID)) == 1


def test_partial_bootstrap_can_be_retried_after_binding_conflict(project_root):
    service = FoundationService(project_root)

    with sqlite3.connect(service.memory.db_path) as db:
        db.execute(
            """
            INSERT INTO foundation_bindings(
                binding_key,binding_value,version,updated_at
            )
            VALUES('company_id','co_wrong',1,'test')
            """
        )

    with pytest.raises(FoundationConflict):
        bootstrap(service)

    # The registry's first transaction remains complete and valid.
    assert service.registry.get_company(COMPANY_ID)["company_id"] == COMPANY_ID
    assert len(service.registry.list_agents(COMPANY_ID)) == 8

    # Correct the conflicting value without deleting unrelated memory.
    with sqlite3.connect(service.memory.db_path) as db:
        db.execute(
            """
            UPDATE foundation_bindings
            SET binding_value=?
            WHERE binding_key='company_id'
            """,
            (COMPANY_ID,),
        )

    retry = bootstrap(service)

    assert retry["validation"]["valid"] is True
    assert retry["registry_bootstrap"]["idempotent"] is True


def test_conflicting_project_binding_is_not_silently_overwritten(
    project_root,
):
    service = FoundationService(project_root)

    with sqlite3.connect(service.memory.db_path) as db:
        db.execute(
            """
            INSERT INTO foundation_bindings(
                binding_key,binding_value,version,updated_at
            )
            VALUES('project_id','prj_other',1,'test')
            """
        )

    with pytest.raises(FoundationConflict):
        bootstrap(service)

    with sqlite3.connect(service.memory.db_path) as db:
        value = db.execute(
            """
            SELECT binding_value
            FROM foundation_bindings
            WHERE binding_key='project_id'
            """
        ).fetchone()[0]

    assert value == "prj_other"


def test_memory_tasks_and_decisions_survive_integrated_restart(project_root):
    service = FoundationService(project_root)
    bootstrap(service)

    service.memory.add_memory(
        scope="project",
        kind="decision",
        title="Integrated decision",
        content="Keep registry identity and memory history linked.",
    )

    task = service.memory.add_task(
        title="Verify integrated company foundation",
        agent_id="qa-bug-hunter",
        priority="high",
        acceptance_criteria=[
            "Registry contains eight specialists",
            "Memory identity bindings are valid",
        ],
    )

    service.memory.update_task(
        task_id=task["task_id"],
        status="queued",
        note="Ready for verification",
    )

    reopened = FoundationService(project_root)
    validation = reopened.validate()

    assert validation["valid"] is True

    tasks = reopened.memory.list_tasks(agent_id="qa-bug-hunter")
    assert any(
        item["task_id"] == task["task_id"]
        and item["status"] == "queued"
        for item in tasks
    )

    memories = reopened.memory.list_memories(scope="project", limit=100)
    assert any(item["title"] == "Integrated decision" for item in memories)


def test_checkpoint_and_event_history_remain_available(project_root):
    service = FoundationService(project_root)
    bootstrap(service)

    checkpoint = service.memory.save_checkpoint(
        "layer-1-checkpoint",
        "Integrated foundation verification",
    )

    reopened = FoundationService(project_root)

    latest = reopened.memory.latest_checkpoint()
    events = reopened.memory.list_events(limit=100)

    assert latest is not None
    assert latest["checkpoint_id"] == checkpoint["checkpoint_id"]
    assert any(
        event["event_type"] == "foundation_memory_bound"
        for event in events
    )
    assert any(
        event["event_type"] == "checkpoint_saved"
        for event in events
    )


def test_validation_detects_registry_audit_tampering(project_root):
    service = FoundationService(project_root)
    bootstrap(service)

    with sqlite3.connect(service.registry_path) as db:
        db.execute("DROP TRIGGER audit_events_no_update")
        db.execute(
            """
            UPDATE audit_events
            SET reason='tampered'
            WHERE event_id=1
            """
        )

    result = service.validate()

    assert result["valid"] is False
    assert any(
        "Audit chain invalid" in issue
        for issue in result["issues"]
    )


def test_verified_backup_can_be_restored_without_overwriting(
    project_root,
    tmp_path,
):
    service = FoundationService(project_root)
    bootstrap(service)

    service.memory.add_memory(
        scope="project",
        kind="decision",
        title="Backup round-trip decision",
        content="This record must survive backup and restore.",
    )

    service.memory.save_checkpoint(
        "before-backup",
        "Backup acceptance test",
    )

    backup_dir = tmp_path / "backups" / "foundation-001"
    backup_result = service.create_backup(backup_dir)

    assert backup_result["created"] is True
    assert backup_result["verified"] is True

    verification = FoundationService.verify_backup(backup_dir)
    assert verification["verified"] is True

    restored_root = tmp_path / "restored-project"
    restore_result = FoundationService.restore_backup(
        backup_dir,
        restored_root,
    )

    assert restore_result["restored"] is True
    assert restore_result["overwrite_performed"] is False

    restored = FoundationService(restored_root)
    validation = restored.validate()

    assert validation["valid"] is True

    memories = restored.memory.list_memories(scope="project", limit=100)
    assert any(
        item["title"] == "Backup round-trip decision"
        for item in memories
    )

    latest = restored.memory.latest_checkpoint()
    assert latest is not None
    assert latest["name"] == "before-backup"


def test_backup_checksum_detects_modified_database(project_root, tmp_path):
    service = FoundationService(project_root)
    bootstrap(service)

    backup_dir = tmp_path / "backups" / "tamper-test"
    service.create_backup(backup_dir)

    memory_copy = backup_dir / "project_memory.sqlite3"
    with memory_copy.open("ab") as handle:
        handle.write(b"tamper")

    with pytest.raises(FoundationIntegrityError, match="checksum mismatch"):
        FoundationService.verify_backup(backup_dir)


def test_restore_refuses_to_overwrite_existing_state(project_root, tmp_path):
    service = FoundationService(project_root)
    bootstrap(service)

    backup_dir = tmp_path / "backups" / "safe-restore"
    service.create_backup(backup_dir)

    target_root = tmp_path / "existing-project"
    state_dir = target_root / ".ai-dev-company"
    state_dir.mkdir(parents=True)
    sentinel = state_dir / "keep-this.txt"
    sentinel.write_text("existing state", encoding="utf-8")

    with pytest.raises(FoundationConflict, match="not empty"):
        FoundationService.restore_backup(backup_dir, target_root)

    assert sentinel.read_text(encoding="utf-8") == "existing state"
