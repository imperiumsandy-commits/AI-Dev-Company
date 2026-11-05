"""Persistent project memory shared by all eight specialist agents.

This is local SQLite persistence, not a remote/cloud database.
No third-party Python package is required.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence


AGENT_IDS = (
    "business-analyst-pm",
    "system-architect",
    "backend-developer",
    "frontend-developer",
    "database-administrator",
    "cybersecurity-engineer",
    "qa-bug-hunter",
    "devops-engineer",
)

TASK_STATUSES = (
    "draft", "planned", "queued", "running", "blocked",
    "needs_review", "verified", "approved", "deployed",
    "failed", "cancelled", "done",
)

ALLOWED_TRANSITIONS = {
    "draft": {"planned", "cancelled"},
    "planned": {"queued", "blocked", "cancelled"},
    "queued": {"running", "blocked", "cancelled"},
    "running": {"needs_review", "blocked", "failed", "cancelled"},
    "needs_review": {"running", "verified", "blocked", "failed"},
    "verified": {"approved", "running", "done"},
    "approved": {"deployed", "done", "running"},
    "deployed": set(),
    "blocked": {"planned", "queued", "running", "cancelled"},
    "failed": {"queued", "running", "cancelled"},
    "cancelled": {"planned"},
    "done": set(),
}

SEED_MEMORIES = (
    (
        "project", "decision", "Eight independent specialist developers",
        "Build eight individually specialized AI developers. Each has its own "
        "architecture, workflow, tools, permissions, schemas, memory policy, "
        "evaluations and tests. Shared infrastructure coordinates them but "
        "does not collapse their specialist logic into one generic agent."
    ),
    (
        "project", "policy", "Quality before completion",
        "External AI output is a draft, not proof of correctness. Inspect, "
        "improve and verify relevant behaviour with evidence. Respect configured "
        "retry and budget limits. Never claim tests passed without running them."
    ),
    (
        "project", "decision", "GPT to PowerShell to Git workflow",
        "The operator wants complete source code and exact PowerShell commands "
        "in chat. PowerShell writes files, tests run, and only explicitly selected "
        "files are committed and pushed to the writable origin fork. Never push "
        "to upstream. Never use git add . as the default."
    ),
    (
        "project", "future_work", "Active memory and agent runtime",
        "Implement persistent state, task history, checkpoints and an agent loader "
        "that reads each specialist's existing instructions. Provider invocation, "
        "cloud-shared memory and autonomous execution require separate implementation "
        "and must not be assumed active until tested."
    ),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def from_json(value: str, fallback: Any = None) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


class MemoryStore:
    """SQLite-backed durable memory for project-wide and per-agent history."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root).resolve() if root else self._find_root()
        self.state_dir = self.root / ".ai-dev-company"
        self.db_path = self.state_dir / "project_memory.sqlite3"
        self.initialize()

    @staticmethod
    def _find_root() -> Path:
        env_root = os.environ.get("AI_DEV_COMPANY_ROOT")
        if env_root:
            candidate = Path(env_root).expanduser().resolve()
            if candidate.exists():
                return candidate
            raise RuntimeError(f"AI_DEV_COMPANY_ROOT does not exist: {candidate}")

        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(Path.cwd()),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip()).resolve()

        for candidate in (Path.cwd(), *Path.cwd().parents):
            if (candidate / ".git").exists():
                return candidate.resolve()
        raise RuntimeError(
            "Project root not found. Run this command inside the AI-Dev-Company repository."
        )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with self._connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS project_meta (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memories (
                    memory_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_memories_scope_time
                    ON memories(scope, created_at DESC);

                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    agent_id TEXT,
                    status TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    acceptance_json TEXT NOT NULL DEFAULT '[]',
                    depends_on_json TEXT NOT NULL DEFAULT '[]',
                    next_action TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_agent_status
                    ON tasks(agent_id, status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_time
                    ON events(event_id DESC);

                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._set_meta(conn, "project_name", "AI-Dev-Company")
            self._set_meta(conn, "schema_version", 1)

            seeded = conn.execute(
                "SELECT value_json FROM project_meta WHERE key='bootstrap_seeded'"
            ).fetchone()
            if seeded is None:
                now = utc_now()
                for scope, kind, title, content in SEED_MEMORIES:
                    conn.execute(
                        """INSERT INTO memories
                           (scope, kind, title, content, source, tags_json,
                            created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (scope, kind, title, content, "bootstrap", "[]", now, now),
                    )
                self._insert_event(
                    conn, "system", "memory_bootstrapped", "project",
                    "AI-Dev-Company", {"seed_memory_count": len(SEED_MEMORIES)}
                )
                self._set_meta(conn, "bootstrap_seeded", True)

    @staticmethod
    def _set_meta(conn: sqlite3.Connection, key: str, value: Any) -> None:
        conn.execute(
            """INSERT INTO project_meta(key, value_json, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                 value_json=excluded.value_json,
                 updated_at=excluded.updated_at""",
            (key, to_json(value), utc_now()),
        )

    @staticmethod
    def _insert_event(
        conn: sqlite3.Connection,
        actor: str,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: Any,
    ) -> None:
        conn.execute(
            """INSERT INTO events
               (occurred_at, actor, event_type, entity_type, entity_id, payload_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (utc_now(), actor, event_type, entity_type, entity_id, to_json(payload)),
        )

    def record_event(
        self,
        actor: str,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: Any,
    ) -> None:
        with self._connection() as conn:
            self._insert_event(
                conn, actor, event_type, entity_type, entity_id, payload
            )

    @staticmethod
    def _validate_scope(scope: str) -> None:
        if scope != "project" and scope not in AGENT_IDS:
            raise ValueError(
                f"Unknown memory scope '{scope}'. Use 'project' or a known agent ID."
            )

    def add_memory(
        self,
        scope: str,
        kind: str,
        title: str,
        content: str,
        source: str = "operator",
        tags: Optional[Sequence[str]] = None,
    ) -> dict[str, Any]:
        self._validate_scope(scope)
        if not title.strip() or not content.strip():
            raise ValueError("Memory title and content must not be empty.")

        now = utc_now()
        with self._connection() as conn:
            cursor = conn.execute(
                """INSERT INTO memories
                   (scope, kind, title, content, source, tags_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    scope, kind, title.strip(), content.strip(), source,
                    to_json(list(tags or [])), now, now
                ),
            )
            memory_id = int(cursor.lastrowid)
            self._insert_event(
                conn, source, "memory_added", "memory", str(memory_id),
                {"scope": scope, "kind": kind, "title": title.strip()}
            )
            return self._memory_dict(
                conn.execute(
                    "SELECT * FROM memories WHERE memory_id=?", (memory_id,)
                ).fetchone()
            )

    @staticmethod
    def _memory_dict(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["tags"] = from_json(item.pop("tags_json", "[]"), [])
        return item

    def list_memories(
        self, scope: Optional[str] = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        with self._connection() as conn:
            if scope:
                self._validate_scope(scope)
                rows = conn.execute(
                    """SELECT * FROM memories WHERE scope=? AND archived=0
                       ORDER BY memory_id DESC LIMIT ?""",
                    (scope, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM memories WHERE archived=0
                       ORDER BY memory_id DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
        return [self._memory_dict(row) for row in rows]

    @staticmethod
    def _task_dict(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["acceptance_criteria"] = from_json(item.pop("acceptance_json"), [])
        item["depends_on"] = from_json(item.pop("depends_on_json"), [])
        return item

    def add_task(
        self,
        title: str,
        description: str = "",
        agent_id: Optional[str] = None,
        priority: str = "normal",
        acceptance_criteria: Optional[Sequence[str]] = None,
        depends_on: Optional[Sequence[str]] = None,
        next_action: str = "",
    ) -> dict[str, Any]:
        if not title.strip():
            raise ValueError("Task title must not be empty.")
        if agent_id is not None and agent_id not in AGENT_IDS:
            raise ValueError(f"Unknown agent ID: {agent_id}")
        if priority not in {"critical", "high", "normal", "low"}:
            raise ValueError("Priority must be critical, high, normal, or low.")

        dependencies = list(depends_on or [])
        with self._connection() as conn:
            for dependency in dependencies:
                exists = conn.execute(
                    "SELECT 1 FROM tasks WHERE task_id=?", (dependency,)
                ).fetchone()
                if exists is None:
                    raise ValueError(f"Dependency task does not exist: {dependency}")

            task_id = "T-" + uuid.uuid4().hex[:10].upper()
            now = utc_now()
            conn.execute(
                """INSERT INTO tasks
                   (task_id, title, description, agent_id, status, priority,
                    acceptance_json, depends_on_json, next_action, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'planned', ?, ?, ?, ?, ?, ?)""",
                (
                    task_id, title.strip(), description.strip(), agent_id, priority,
                    to_json(list(acceptance_criteria or [])), to_json(dependencies),
                    next_action.strip(), now, now
                ),
            )
            self._insert_event(
                conn, "operator", "task_created", "task", task_id,
                {
                    "title": title.strip(), "agent_id": agent_id, "priority": priority,
                    "depends_on": dependencies,
                },
            )
            row = conn.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
        return self._task_dict(row)

    def list_tasks(
        self,
        agent_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if agent_id and agent_id not in AGENT_IDS:
            raise ValueError(f"Unknown agent ID: {agent_id}")
        if status and status not in TASK_STATUSES:
            raise ValueError(f"Unknown task status: {status}")
        limit = max(1, min(int(limit), 500))

        query = "SELECT * FROM tasks WHERE 1=1"
        params: list[Any] = []
        if agent_id:
            query += " AND agent_id=?"
            params.append(agent_id)
        if status:
            query += " AND status=?"
            params.append(status)
        query += " ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, updated_at DESC LIMIT ?"
        params.append(limit)

        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._task_dict(row) for row in rows]

    def update_task(
        self,
        task_id: str,
        status: Optional[str] = None,
        next_action: Optional[str] = None,
        note: Optional[str] = None,
    ) -> dict[str, Any]:
        if status is not None and status not in TASK_STATUSES:
            raise ValueError(f"Unknown task status: {status}")

        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Task not found: {task_id}")

            old_status = row["status"]
            new_status = status or old_status
            if new_status != old_status and new_status not in ALLOWED_TRANSITIONS[old_status]:
                raise ValueError(
                    f"Invalid state transition: {old_status} -> {new_status}. "
                    f"Allowed: {sorted(ALLOWED_TRANSITIONS[old_status])}"
                )

            new_next_action = (
                row["next_action"] if next_action is None else next_action.strip()
            )
            conn.execute(
                """UPDATE tasks SET status=?, next_action=?, updated_at=?
                   WHERE task_id=?""",
                (new_status, new_next_action, utc_now(), task_id),
            )
            self._insert_event(
                conn, "operator", "task_updated", "task", task_id,
                {
                    "old_status": old_status, "new_status": new_status,
                    "note": note, "next_action": new_next_action,
                },
            )
            updated = conn.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
        return self._task_dict(updated)

    def list_events(
        self, limit: int = 20, actor: Optional[str] = None
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        with self._connection() as conn:
            if actor:
                rows = conn.execute(
                    "SELECT * FROM events WHERE actor=? ORDER BY event_id DESC LIMIT ?",
                    (actor, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM events ORDER BY event_id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = from_json(item.pop("payload_json"), {})
            result.append(item)
        return result

    def summary(self) -> dict[str, Any]:
        with self._connection() as conn:
            meta_rows = conn.execute(
                "SELECT key, value_json FROM project_meta"
            ).fetchall()
            meta = {row["key"]: from_json(row["value_json"]) for row in meta_rows}

            count_rows = conn.execute(
                "SELECT status, COUNT(*) AS total FROM tasks GROUP BY status"
            ).fetchall()
            counts = {row["status"]: row["total"] for row in count_rows}

            task_rows = conn.execute(
                """SELECT * FROM tasks
                   WHERE status NOT IN ('done','deployed','cancelled')
                   ORDER BY updated_at DESC LIMIT 20"""
            ).fetchall()
            memory_rows = conn.execute(
                """SELECT * FROM memories WHERE archived=0
                   ORDER BY memory_id DESC LIMIT 12"""
            ).fetchall()
            event_rows = conn.execute(
                "SELECT * FROM events ORDER BY event_id DESC LIMIT 15"
            ).fetchall()

        events = []
        for row in event_rows:
            item = dict(row)
            item["payload"] = from_json(item.pop("payload_json"), {})
            events.append(item)

        return {
            "project": "AI-Dev-Company",
            "root": str(self.root),
            "memory_database": str(self.db_path),
            "meta": meta,
            "task_counts_by_status": counts,
            "open_tasks": [self._task_dict(row) for row in task_rows],
            "recent_memories": [self._memory_dict(row) for row in memory_rows],
            "recent_events": events,
        }

    def save_checkpoint(self, name: str, note: str = "") -> dict[str, Any]:
        if not name.strip():
            raise ValueError("Checkpoint name must not be empty.")
        snapshot = {"note": note, "project_summary": self.summary()}
        with self._connection() as conn:
            cursor = conn.execute(
                """INSERT INTO checkpoints(name, payload_json, created_at)
                   VALUES (?, ?, ?)""",
                (name.strip(), to_json(snapshot), utc_now()),
            )
            checkpoint_id = int(cursor.lastrowid)
            self._insert_event(
                conn, "runtime", "checkpoint_saved", "checkpoint",
                str(checkpoint_id), {"name": name.strip(), "note": note}
            )
            return {
                "checkpoint_id": checkpoint_id,
                "name": name.strip(),
                "created_at": utc_now(),
                "database": str(self.db_path),
            }

    def latest_checkpoint(self) -> Optional[dict[str, Any]]:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM checkpoints ORDER BY checkpoint_id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["payload"] = from_json(item.pop("payload_json"), {})
        return item
