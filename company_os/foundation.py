"""Integrated Company Foundation for AI-Dev-Company.

Coordinates the canonical company registry and persistent project memory.
The two SQLite databases remain separate; bootstrap is retry-safe rather than
pretending to provide a distributed transaction.

This module does not execute agents or call AI providers.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ai_dev_company.memory_store import AGENT_IDS, MemoryStore
from company_os.registry.catalog import DEFAULT_AGENTS
from company_os.registry.core import RegistryError, RegistryStore


COMPANY_ID = "co_ai_dev_company"
PROJECT_ID = "prj_ai_dev_company"
PROJECT_REPOSITORY = (
    "https://github.com/imperiumsandy-commits/AI-Dev-Company"
)

BACKUP_FORMAT = "ai-dev-company-state-backup"
BACKUP_VERSION = 1
FOUNDATION_SCHEMA_VERSION = 1
GENESIS_HASH = "0" * 64

CURRENT_DELIVERY_POLICY_TITLE = "GitHub-first source delivery policy"
LEGACY_DELIVERY_POLICY_TITLE = "GPT to PowerShell to Git workflow"

CURRENT_DELIVERY_POLICY = (
    "The GitHub repository is the source of truth for project code. "
    "The assistant provides complete repository-relative file contents "
    "directly in chat. The repository owner applies changes manually "
    "through the GitHub browser interface. The assistant does not write, "
    "commit, or push to GitHub. Local PC and PowerShell workflows are not "
    "required for normal project additions. Command-output snapshots are "
    "historical evidence, not implementation modules."
)

FOUNDATION_MIGRATION_V1 = (
    "v1: create foundation_bindings and foundation_migrations; "
    "archive the obsolete GPT-PowerShell-Git seed without deleting it; "
    "insert the current GitHub-first delivery policy; preserve all other "
    "memory, task, event and checkpoint records."
)


class FoundationError(RuntimeError):
    """Base error for integrated foundation operations."""


class FoundationConflict(FoundationError):
    """Existing foundation identity or binding conflicts with the request."""


class FoundationIntegrityError(FoundationError):
    """A database, migration, backup or cross-store invariant is invalid."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_integrity(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, "database file is missing"

    try:
        with sqlite3.connect(str(path), timeout=15) as db:
            result = db.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_key_errors = db.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()

        if result != "ok":
            return False, str(result)

        if foreign_key_errors:
            return False, f"{len(foreign_key_errors)} foreign-key violation(s)"

        return True, "ok"
    except sqlite3.Error as exc:
        return False, str(exc)


def _registry_chain_integrity(path: Path) -> tuple[bool, str]:
    """Verify the registry's complete append-only audit hash chain."""
    try:
        with sqlite3.connect(str(path), timeout=15) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT * FROM audit_events ORDER BY event_id"
            ).fetchall()

        previous = GENESIS_HASH

        for expected_id, row in enumerate(rows, start=1):
            if (
                row["event_id"] != expected_id
                or row["previous_hash"] != previous
            ):
                return False, "audit sequence or previous-hash mismatch"

            event = {
                "event_uuid": row["event_uuid"],
                "company_id": row["company_id"],
                "entity_type": row["entity_type"],
                "entity_id": row["entity_id"],
                "action": row["action"],
                "actor": row["actor"],
                "reason": row["reason"],
                "recorded_at": row["recorded_at"],
                "payload": json.loads(row["payload_json"]),
                "previous_hash": row["previous_hash"],
            }

            digest = hashlib.sha256(_json(event).encode("utf-8")).hexdigest()

            if digest != row["event_hash"]:
                return False, f"audit event hash mismatch at event {expected_id}"

            previous = row["event_hash"]

        return True, f"{len(rows)} audit event(s) verified"
    except (sqlite3.Error, KeyError, TypeError, ValueError) as exc:
        return False, str(exc)


class FoundationService:
    """Coordinates company identity, specialist identities and project memory.

    Registry and memory are deliberately separate SQLite stores. Registry
    bootstrap is transactional. Memory binding is a second idempotent
    transaction. A failed second step can safely be retried.
    """

    def __init__(
        self,
        root: str | Path,
        registry_path: str | Path | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

        self.state_dir = self.root / ".ai-dev-company"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.memory = MemoryStore(root=self.root)

        requested_registry_path = (
            Path(registry_path).expanduser().resolve()
            if registry_path is not None
            else self.state_dir / "company_registry.sqlite3"
        )

        try:
            self.registry_reference = (
                requested_registry_path.relative_to(self.root).as_posix()
            )
        except ValueError as exc:
            raise FoundationError(
                "The registry database must remain inside the project root "
                "so state backups can be restored safely."
            ) from exc

        self.registry_path = requested_registry_path
        self.registry = RegistryStore(self.registry_path)

        self._apply_memory_foundation_migration()

    @property
    def expected_agent_scope_map(self) -> dict[str, str]:
        return {
            spec["agent_id"]: spec["slug"]
            for spec in DEFAULT_AGENTS
        }

    def _expected_bindings(self) -> dict[str, str]:
        return {
            "company_id": COMPANY_ID,
            "project_id": PROJECT_ID,
            "registry_path": self.registry_reference,
            "agent_scope_map": _json(self.expected_agent_scope_map),
        }

    def _apply_memory_foundation_migration(self) -> dict[str, Any]:
        """Apply an independent, transactional integration migration.

        The existing MemoryStore schema and records are not replaced.
        The obsolete seed is archived, not deleted.
        """
        connection = sqlite3.connect(
            str(self.memory.db_path),
            timeout=15,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=15000")

        checksum = hashlib.sha256(
            FOUNDATION_MIGRATION_V1.encode("utf-8")
        ).hexdigest()

        try:
            connection.execute("BEGIN IMMEDIATE")

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS foundation_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                )
                """
            )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS foundation_bindings (
                    binding_key TEXT PRIMARY KEY,
                    binding_value TEXT NOT NULL,
                    version INTEGER NOT NULL CHECK(version >= 1),
                    updated_at TEXT NOT NULL
                )
                """
            )

            current = connection.execute(
                "SELECT MAX(version) FROM foundation_migrations"
            ).fetchone()[0] or 0

            if current > FOUNDATION_SCHEMA_VERSION:
                raise FoundationIntegrityError(
                    "Memory foundation schema is newer than this runtime."
                )

            if current == FOUNDATION_SCHEMA_VERSION:
                migration = connection.execute(
                    """
                    SELECT checksum FROM foundation_migrations
                    WHERE version=?
                    """,
                    (FOUNDATION_SCHEMA_VERSION,),
                ).fetchone()

                if migration is None or migration["checksum"] != checksum:
                    raise FoundationIntegrityError(
                        "Foundation migration checksum mismatch."
                    )

                connection.commit()
                return {"version": current, "applied": False}

            now = _utc_now()

            archived = connection.execute(
                """
                UPDATE memories
                SET archived=1, updated_at=?
                WHERE scope='project'
                  AND title=?
                  AND archived=0
                """,
                (now, LEGACY_DELIVERY_POLICY_TITLE),
            ).rowcount

            replacement = connection.execute(
                """
                SELECT 1 FROM memories
                WHERE scope='project'
                  AND title=?
                  AND archived=0
                LIMIT 1
                """,
                (CURRENT_DELIVERY_POLICY_TITLE,),
            ).fetchone()

            inserted_policy = False
            if replacement is None:
                connection.execute(
                    """
                    INSERT INTO memories(
                        scope,kind,title,content,source,tags_json,
                        created_at,updated_at,archived
                    )
                    VALUES(?,?,?,?,?,?,?,?,0)
                    """,
                    (
                        "project",
                        "policy",
                        CURRENT_DELIVERY_POLICY_TITLE,
                        CURRENT_DELIVERY_POLICY,
                        "foundation-migration-v1",
                        _json(["github", "source-of-truth", "delivery-policy"]),
                        now,
                        now,
                    ),
                )
                inserted_policy = True

            connection.execute(
                """
                INSERT INTO events(
                    occurred_at,actor,event_type,entity_type,entity_id,payload_json
                )
                VALUES(?,?,?,?,?,?)
                """,
                (
                    now,
                    "foundation-migration",
                    "foundation_memory_migrated",
                    "project",
                    "AI-Dev-Company",
                    _json({
                        "migration_version": FOUNDATION_SCHEMA_VERSION,
                        "legacy_policy_records_archived": archived,
                        "replacement_policy_inserted": inserted_policy,
                    }),
                ),
            )

            connection.execute(
                """
                INSERT INTO foundation_migrations(
                    version,name,checksum,applied_at
                )
                VALUES(?,?,?,?)
                """,
                (
                    FOUNDATION_SCHEMA_VERSION,
                    "integrated_foundation_bindings",
                    checksum,
                    now,
                ),
            )

            connection.commit()
            return {
                "version": FOUNDATION_SCHEMA_VERSION,
                "applied": True,
                "legacy_records_archived": archived,
                "replacement_policy_inserted": inserted_policy,
            }

        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def _bind_memory(self) -> dict[str, Any]:
        expected = self._expected_bindings()
        connection = sqlite3.connect(
            str(self.memory.db_path),
            timeout=15,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=15000")

        created: list[str] = []

        try:
            connection.execute("BEGIN IMMEDIATE")

            current_rows = connection.execute(
                "SELECT binding_key,binding_value FROM foundation_bindings"
            ).fetchall()
            current = {
                row["binding_key"]: row["binding_value"]
                for row in current_rows
            }

            # Validate every existing value before inserting anything.
            for key, value in expected.items():
                if key in current and current[key] != value:
                    raise FoundationConflict(
                        f"Memory binding '{key}' conflicts with the "
                        "requested company foundation. No binding was changed."
                    )

            now = _utc_now()

            for key, value in expected.items():
                if key not in current:
                    connection.execute(
                        """
                        INSERT INTO foundation_bindings(
                            binding_key,binding_value,version,updated_at
                        )
                        VALUES(?,?,1,?)
                        """,
                        (key, value, now),
                    )
                    created.append(key)

            if created:
                connection.execute(
                    """
                    INSERT INTO events(
                        occurred_at,actor,event_type,entity_type,entity_id,payload_json
                    )
                    VALUES(?,?,?,?,?,?)
                    """,
                    (
                        now,
                        "foundation-coordinator",
                        "foundation_memory_bound",
                        "project",
                        PROJECT_ID,
                        _json({
                            "company_id": COMPANY_ID,
                            "project_id": PROJECT_ID,
                            "created_bindings": created,
                        }),
                    ),
                )

            connection.commit()
            return {
                "valid": True,
                "created_bindings": created,
                "idempotent": not bool(created),
            }

        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def bootstrap(
        self,
        *,
        owner_name: str,
        owner_email: str,
        actor: str = "owner:imperiumsandy-commits",
        reason: str = "Integrated Company Foundation bootstrap",
    ) -> dict[str, Any]:
        """Create the canonical company/project/eight-agent registry and bind memory."""
        registry_result = self.registry.bootstrap(
            company={
                "company_id": COMPANY_ID,
                "slug": "ai-dev-company",
                "name": "AI Software Engineering Company",
                "owner_name": owner_name,
                "owner_email": owner_email,
            },
            project={
                "project_id": PROJECT_ID,
                "company_id": COMPANY_ID,
                "slug": "ai-dev-company",
                "name": "AI-Dev-Company",
                "repository_url": PROJECT_REPOSITORY,
                "default_branch": "main",
                "status": "active",
            },
            agents=DEFAULT_AGENTS,
            actor=actor,
            reason=reason,
        )

        # This second transaction is intentionally retry-safe. If it fails,
        # registry.bootstrap can be repeated without duplicating its records.
        memory_binding = self._bind_memory()
        validation = self.validate()

        if not validation["valid"]:
            raise FoundationIntegrityError(
                "Bootstrap completed with failed validation: "
                + "; ".join(validation["issues"])
            )

        return {
            "registry_bootstrap": registry_result,
            "memory_binding": memory_binding,
            "validation": validation,
        }

    def validate(self) -> dict[str, Any]:
        """Check both databases and the cross-store identity contract."""
        issues: list[str] = []
        registry_validation: dict[str, Any] | None = None
        actual_agent_ids: set[str] = set()
        actual_project_ids: set[str] = set()
        company_status: str | None = None

        try:
            registry_validation = self.registry.validate(COMPANY_ID)
            company = self.registry.get_company(COMPANY_ID)
            company_status = company["status"]

            projects = self.registry.list_projects(COMPANY_ID)
            actual_project_ids = {
                item["project_id"] for item in projects
            }

            agents = self.registry.list_agents(COMPANY_ID)
            actual_agent_ids = {
                item["agent_id"] for item in agents
            }

            expected_agent_ids = {
                spec["agent_id"] for spec in DEFAULT_AGENTS
            }

            if company_status != "active":
                issues.append(f"Company status is '{company_status}', not active.")

            if PROJECT_ID not in actual_project_ids:
                issues.append("The canonical project is missing from the registry.")

            if actual_agent_ids != expected_agent_ids:
                issues.append(
                    "Registered specialist identities do not match the "
                    "canonical eight-agent catalog."
                )

            if not registry_validation["valid"]:
                issues.extend(registry_validation.get("issues", []))

        except RegistryError as exc:
            issues.append(f"Registry validation failed: {exc}")

        memory_info: dict[str, Any] = {
            "integrity": "not checked",
            "memory_count": 0,
            "task_count": 0,
            "event_count": 0,
            "checkpoint_count": 0,
            "foundation_migration_version": 0,
            "bindings_valid": False,
        }

        try:
            with sqlite3.connect(
                str(self.memory.db_path), timeout=15
            ) as db:
                integrity = db.execute(
                    "PRAGMA integrity_check"
                ).fetchone()[0]
                fk_errors = db.execute(
                    "PRAGMA foreign_key_check"
                ).fetchall()

                if integrity != "ok":
                    issues.append(f"Memory SQLite integrity check: {integrity}")

                if fk_errors:
                    issues.append(
                        f"Memory database has {len(fk_errors)} foreign-key violation(s)."
                    )

                memory_info["integrity"] = integrity
                memory_info["memory_count"] = db.execute(
                    "SELECT COUNT(*) FROM memories WHERE archived=0"
                ).fetchone()[0]
                memory_info["task_count"] = db.execute(
                    "SELECT COUNT(*) FROM tasks"
                ).fetchone()[0]
                memory_info["event_count"] = db.execute(
                    "SELECT COUNT(*) FROM events"
                ).fetchone()[0]
                memory_info["checkpoint_count"] = db.execute(
                    "SELECT COUNT(*) FROM checkpoints"
                ).fetchone()[0]

                migration = db.execute(
                    """
                    SELECT MAX(version) FROM foundation_migrations
                    """
                ).fetchone()[0] or 0
                memory_info["foundation_migration_version"] = migration

                rows = db.execute(
                    """
                    SELECT binding_key,binding_value
                    FROM foundation_bindings
                    """
                ).fetchall()
                bindings = dict(rows)

            expected_bindings = self._expected_bindings()
            bindings_valid = all(
                bindings.get(key) == value
                for key, value in expected_bindings.items()
            )
            memory_info["bindings_valid"] = bindings_valid

            if migration != FOUNDATION_SCHEMA_VERSION:
                issues.append("Memory foundation migration is not at the supported version.")

            if not bindings_valid:
                issues.append("Registry and memory identity bindings are missing or inconsistent.")

            memory_scopes = set(AGENT_IDS)
            expected_scopes = set(self.expected_agent_scope_map.values())
            if memory_scopes != expected_scopes:
                issues.append("Memory specialist scopes do not match the registry catalog.")

        except (sqlite3.Error, KeyError) as exc:
            issues.append(f"Memory validation failed: {exc}")

        return {
            "valid": not issues,
            "company_id": COMPANY_ID,
            "project_id": PROJECT_ID,
            "company_status": company_status,
            "registered_agent_count": len(actual_agent_ids),
            "registered_project_count": len(actual_project_ids),
            "registry_validation": registry_validation,
            "memory": memory_info,
            "database_paths": {
                "registry": str(self.registry_path),
                "memory": str(self.memory.db_path),
            },
            "storage_contract": (
                "Two local SQLite databases coordinated through immutable "
                "company/project bindings and retry-safe bootstrap; not a "
                "distributed atomic transaction."
            ),
            "issues": issues,
        }

    @staticmethod
    def _backup_sqlite(source: Path, destination: Path) -> None:
        source_db = sqlite3.connect(str(source), timeout=15)
        target_db = sqlite3.connect(str(destination), timeout=15)

        try:
            source_db.backup(target_db)
            integrity = target_db.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0]

            if integrity != "ok":
                raise FoundationIntegrityError(
                    f"Backup integrity check failed for {source.name}: {integrity}"
                )
        finally:
            target_db.close()
            source_db.close()

    @classmethod
    def _verify_backup_registry_chain(cls, path: Path) -> None:
        valid, detail = _registry_chain_integrity(path)
        if not valid:
            raise FoundationIntegrityError(
                f"Backup registry audit chain is invalid: {detail}"
            )

    @classmethod
    def verify_backup(cls, backup_path: str | Path) -> dict[str, Any]:
        """Verify backup manifest, file hashes, SQLite integrity and audit chain."""
        directory = Path(backup_path).expanduser().resolve()
        manifest_path = directory / "manifest.json"

        if not manifest_path.is_file():
            raise FoundationIntegrityError("Backup manifest is missing.")

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FoundationIntegrityError(
                f"Backup manifest cannot be read: {exc}"
            ) from exc

        if (
            manifest.get("format") != BACKUP_FORMAT
            or manifest.get("version") != BACKUP_VERSION
        ):
            raise FoundationIntegrityError(
                "Unsupported backup format or version."
            )

        expected_names = {
            "company_registry.sqlite3",
            "project_memory.sqlite3",
        }
        database_metadata = manifest.get("databases", {})

        if set(database_metadata) != expected_names:
            raise FoundationIntegrityError(
                "Backup must contain exactly the registry and memory databases."
            )

        for name in sorted(expected_names):
            # File names are fixed to prevent path traversal from a manifest.
            path = directory / name
            metadata = database_metadata[name]

            if not path.is_file():
                raise FoundationIntegrityError(f"Backup file is missing: {name}")

            if path.stat().st_size != metadata.get("size_bytes"):
                raise FoundationIntegrityError(f"Backup size mismatch: {name}")

            if _sha256(path) != metadata.get("sha256"):
                raise FoundationIntegrityError(f"Backup checksum mismatch: {name}")

            valid, detail = _sqlite_integrity(path)
            if not valid:
                raise FoundationIntegrityError(
                    f"Backup database is invalid ({name}): {detail}"
                )

        registry_path = directory / "company_registry.sqlite3"
        memory_path = directory / "project_memory.sqlite3"

        cls._verify_backup_registry_chain(registry_path)

        with sqlite3.connect(str(memory_path), timeout=15) as db:
            migration = db.execute(
                "SELECT MAX(version) FROM foundation_migrations"
            ).fetchone()[0] or 0

            binding_rows = db.execute(
                """
                SELECT binding_key,binding_value
                FROM foundation_bindings
                """
            ).fetchall()
            bindings = dict(binding_rows)

        if migration != FOUNDATION_SCHEMA_VERSION:
            raise FoundationIntegrityError(
                "Backup memory database has an unsupported foundation migration."
            )

        if bindings.get("company_id") != manifest.get("company_id"):
            raise FoundationIntegrityError(
                "Backup company identity does not match its manifest."
            )

        if bindings.get("project_id") != manifest.get("project_id"):
            raise FoundationIntegrityError(
                "Backup project identity does not match its manifest."
            )

        return {
            "verified": True,
            "backup_path": str(directory),
            "company_id": manifest["company_id"],
            "project_id": manifest["project_id"],
            "databases": sorted(expected_names),
            "created_at": manifest["created_at"],
        }

    def create_backup(self, destination: str | Path) -> dict[str, Any]:
        """Create and verify a state-only backup without copying source code."""
        validation = self.validate()
        if not validation["valid"]:
            raise FoundationIntegrityError(
                "Backup refused because foundation validation failed: "
                + "; ".join(validation["issues"])
            )

        target = Path(destination).expanduser().resolve()

        if target.exists():
            raise FoundationConflict(
                f"Backup destination already exists: {target}"
            )

        if target == self.state_dir or self.state_dir in target.parents:
            raise FoundationConflict(
                "Backup destination cannot be inside the live state directory."
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
        staging.mkdir()

        try:
            registry_copy = staging / "company_registry.sqlite3"
            memory_copy = staging / "project_memory.sqlite3"

            self._backup_sqlite(self.registry_path, registry_copy)
            self._backup_sqlite(self.memory.db_path, memory_copy)

            manifest = {
                "format": BACKUP_FORMAT,
                "version": BACKUP_VERSION,
                "created_at": _utc_now(),
                "company_id": COMPANY_ID,
                "project_id": PROJECT_ID,
                "scope": "runtime-state-only",
                "source_code": (
                    "Not included. GitHub remains the source of truth for code."
                ),
                "databases": {
                    "company_registry.sqlite3": {
                        "size_bytes": registry_copy.stat().st_size,
                        "sha256": _sha256(registry_copy),
                    },
                    "project_memory.sqlite3": {
                        "size_bytes": memory_copy.stat().st_size,
                        "sha256": _sha256(memory_copy),
                    },
                },
            }

            (staging / "manifest.json").write_text(
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )

            self.verify_backup(staging)
            os.replace(staging, target)

            return {
                "created": True,
                "verified": True,
                "backup_path": str(target),
                "manifest": manifest,
            }

        except Exception:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise

    @classmethod
    def restore_backup(
        cls,
        backup_path: str | Path,
        target_root: str | Path,
    ) -> dict[str, Any]:
        """Restore state into an empty project state directory.

        Existing state is never overwritten. Restore to a separate project
        checkout or an empty .ai-dev-company directory, then validate it.
        """
        verified = cls.verify_backup(backup_path)
        root = Path(target_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)

        state_dir = root / ".ai-dev-company"

        if state_dir.exists() and any(state_dir.iterdir()):
            raise FoundationConflict(
                "Restore refused: target .ai-dev-company directory is not empty. "
                "Existing databases will not be overwritten."
            )

        staging = root / f".ai-dev-company.restore-{uuid.uuid4().hex}"
        staging.mkdir()

        try:
            source_dir = Path(backup_path).expanduser().resolve()

            shutil.copy2(
                source_dir / "company_registry.sqlite3",
                staging / "company_registry.sqlite3",
            )
            shutil.copy2(
                source_dir / "project_memory.sqlite3",
                staging / "project_memory.sqlite3",
            )

            for name in (
                "company_registry.sqlite3",
                "project_memory.sqlite3",
            ):
                valid, detail = _sqlite_integrity(staging / name)
                if not valid:
                    raise FoundationIntegrityError(
                        f"Restored database failed verification ({name}): {detail}"
                    )

            cls._verify_backup_registry_chain(
                staging / "company_registry.sqlite3"
            )

            if state_dir.exists():
                state_dir.rmdir()

            os.replace(staging, state_dir)

            return {
                "restored": True,
                "verified_backup": True,
                "target_state_directory": str(state_dir),
                "company_id": verified["company_id"],
                "project_id": verified["project_id"],
                "overwrite_performed": False,
            }

        except Exception:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise
