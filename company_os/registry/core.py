
"""F01 canonical registry: company, projects, specialist agents, config and audit.

SQLite is the local adapter. The public service contract is storage-neutral so a
PostgreSQL adapter can be introduced without changing callers. No model/provider
SDK is imported here: registry identity must remain model-independent.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

SCHEMA_VERSION = 1
COMPANY_STATUSES = {"active", "suspended", "archived"}
PROJECT_STATUSES = {"planned", "active", "paused", "archived"}
AGENT_STATUSES = {"planned", "registered", "active", "paused", "retired"}
SCOPE_TYPES = {"company", "project", "agent"}
_ID = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_SECRET_KEY = re.compile(
    r"(^|[._-])(password|secret|credential|api[_-]?key|private[_-]?key|access[_-]?token|refresh[_-]?token)([._-]|$)",
    re.I,
)
_GENESIS = "0" * 64


class RegistryError(Exception):
    """Base class for expected registry errors."""


class ValidationError(RegistryError):
    """An input violates a registry invariant."""


class NotFound(RegistryError):
    """A requested registry record does not exist."""


class Conflict(RegistryError):
    """An identity already exists or a write is based on stale state."""


class IntegrityViolation(RegistryError):
    """Persistent registry or audit-chain integrity is invalid."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations(
  version INTEGER PRIMARY KEY, name TEXT NOT NULL,
  checksum TEXT NOT NULL, applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS companies(
  company_id TEXT PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  owner_name TEXT NOT NULL,
  owner_email TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('active','suspended','archived')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL CHECK(version >= 1)
);

CREATE TABLE IF NOT EXISTS projects(
  project_id TEXT PRIMARY KEY,
  company_id TEXT NOT NULL REFERENCES companies(company_id) ON DELETE RESTRICT,
  slug TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  repository_url TEXT NOT NULL,
  default_branch TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('planned','active','paused','archived')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL CHECK(version >= 1),
  UNIQUE(company_id, slug),
  UNIQUE(company_id, repository_url)
);

CREATE TABLE IF NOT EXISTS agents(
  agent_id TEXT PRIMARY KEY,
  company_id TEXT NOT NULL REFERENCES companies(company_id) ON DELETE RESTRICT,
  slug TEXT NOT NULL,
  display_name TEXT NOT NULL,
  domain TEXT NOT NULL,
  definition_path TEXT NOT NULL,
  role_version TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('planned','registered','active','paused','retired')),
  capabilities_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL CHECK(version >= 1),
  UNIQUE(company_id, slug)
);

CREATE TABLE IF NOT EXISTS configurations(
  scope_type TEXT NOT NULL CHECK(scope_type IN ('company','project','agent')),
  scope_id TEXT NOT NULL,
  config_key TEXT NOT NULL,
  value_json TEXT NOT NULL,
  version INTEGER NOT NULL CHECK(version >= 1),
  updated_by TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(scope_type, scope_id, config_key)
);

CREATE TABLE IF NOT EXISTS audit_events(
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_uuid TEXT NOT NULL UNIQUE,
  company_id TEXT NOT NULL REFERENCES companies(company_id) ON DELETE RESTRICT,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  action TEXT NOT NULL,
  actor TEXT NOT NULL,
  reason TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  previous_hash TEXT NOT NULL,
  event_hash TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_projects_company_status
ON projects(company_id,status);

CREATE INDEX IF NOT EXISTS idx_agents_company_status
ON agents(company_id,status);

CREATE INDEX IF NOT EXISTS idx_audit_entity
ON audit_events(entity_type,entity_id,event_id);

CREATE TRIGGER IF NOT EXISTS audit_events_no_update
BEFORE UPDATE ON audit_events
BEGIN
  SELECT RAISE(ABORT,'audit_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
BEFORE DELETE ON audit_events
BEGIN
  SELECT RAISE(ABORT,'audit_events is append-only');
END;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def _json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            f"Value must be JSON-serializable and finite: {exc}"
        ) from exc


def _text(value: Any, field: str, limit: int = 240) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string")

    value = value.strip()

    if (
        not value
        or len(value) > limit
        or any(ord(c) < 32 for c in value)
    ):
        raise ValidationError(
            f"{field} must be non-empty text of at most {limit} characters"
        )

    return value


def _id(value: Any, field: str) -> str:
    value = _text(value, field, 100)

    if not _ID.fullmatch(value):
        raise ValidationError(
            f"{field} must be a stable lowercase ID with underscores"
        )

    return value


def _slug(value: Any) -> str:
    value = _text(value, "slug", 80)

    if not _SLUG.fullmatch(value):
        raise ValidationError(
            "slug must use lowercase letters, numbers and hyphens"
        )

    return value


def _actor(actor: Any, reason: Any) -> tuple[str, str]:
    return (
        _text(actor, "actor", 120),
        _text(reason, "reason", 1000),
    )


def _repo_url(value: Any) -> str:
    value = _text(value, "repository_url", 500)

    if not (
        value.startswith("https://")
        or value.startswith("ssh://")
        or value.startswith("git@")
    ):
        raise ValidationError(
            "repository_url must be an HTTPS or SSH Git URL"
        )

    return value


class RegistryStore:
    """Transactional F01 registry with optimistic versions and hash-chained events."""

    def __init__(self, database_path: str | Path):
        if str(database_path) == ":memory:":
            raise ValidationError(
                "F01 requires a durable file-backed SQLite database"
            )

        self.path = Path(database_path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(
            self.path,
            timeout=15,
            isolation_level=None,
        )
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=15000")
        db.execute("PRAGMA synchronous=FULL")
        return db

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        db = self._connect()

        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _initialize(self) -> None:
        db = self._connect()

        try:
            db.execute("PRAGMA journal_mode=WAL")

            version = db.execute(
                "PRAGMA user_version"
            ).fetchone()[0]

            if version > SCHEMA_VERSION:
                raise IntegrityViolation(
                    f"Database schema {version} is newer than supported {SCHEMA_VERSION}"
                )

            checksum = hashlib.sha256(
                _SCHEMA.encode()
            ).hexdigest()

            script = (
                "BEGIN IMMEDIATE;\n"
                + _SCHEMA
                + "\nINSERT OR IGNORE INTO schema_migrations "
                "VALUES(1,'f01_registry','"
                + checksum
                + "','"
                + _now()
                + "');"
                "\nPRAGMA user_version=1;\nCOMMIT;"
            )

            try:
                db.executescript(script)
            except Exception:
                if db.in_transaction:
                    db.rollback()
                raise

            applied = db.execute(
                "SELECT checksum FROM schema_migrations WHERE version=1"
            ).fetchone()

            if applied is None or applied["checksum"] != checksum:
                raise IntegrityViolation(
                    "F01 migration checksum mismatch; refusing to trust schema state"
                )

        finally:
            db.close()

    @staticmethod
    def _event(
        db: sqlite3.Connection,
        company_id: str,
        entity_type: str,
        entity_id: str,
        action: str,
        actor: str,
        reason: str,
        payload: Mapping[str, Any],
    ) -> None:

        last = db.execute(
            "SELECT event_hash FROM audit_events ORDER BY event_id DESC LIMIT 1"
        ).fetchone()

        previous = last["event_hash"] if last else _GENESIS

        event = {
            "event_uuid": str(uuid.uuid4()),
            "company_id": company_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": action,
            "actor": actor,
            "reason": reason,
            "recorded_at": _now(),
            "payload": dict(payload),
            "previous_hash": previous,
        }

        digest = hashlib.sha256(
            _json(event).encode("utf-8")
        ).hexdigest()

        db.execute(
            """INSERT INTO audit_events(
              event_uuid,company_id,entity_type,entity_id,action,actor,reason,
              recorded_at,payload_json,previous_hash,event_hash
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                event["event_uuid"],
                company_id,
                entity_type,
                entity_id,
                action,
                actor,
                reason,
                event["recorded_at"],
                _json(event["payload"]),
                previous,
                digest,
            ),
        )

    @staticmethod
    def _company(
        db: sqlite3.Connection,
        company_id: str,
    ) -> sqlite3.Row:

        row = db.execute(
            "SELECT * FROM companies WHERE company_id=?",
            (company_id,),
        ).fetchone()

        if row is None:
            raise NotFound(f"Company not found: {company_id}")

        return row

    def register_company(
        self,
        *,
        company_id: str,
        slug: str,
        name: str,
        owner_name: str,
        owner_email: str,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:

        company_id = _id(company_id, "company_id")
        slug = _slug(slug)
        name = _text(name, "name")
        owner_name = _text(owner_name, "owner_name")
        email = _text(owner_email, "owner_email", 254).lower()

        if not _EMAIL.fullmatch(email):
            raise ValidationError("owner_email is not a valid email address")

        actor, reason = _actor(actor, reason)
        now = _now()

        with self._write() as db:
            try:
                db.execute(
                    """INSERT INTO companies
                    VALUES(?,?,?,?,?,'active',?,?,1)""",
                    (
                        company_id, slug, name, owner_name,
                        email, now, now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise Conflict(
                    f"Company ID or slug already exists: {exc}"
                ) from exc

            self._event(
                db, company_id, "company", company_id,
                "company.registered", actor, reason,
                {
                    "slug": slug,
                    "name": name,
                    "owner_email": email,
                    "version": 1,
                },
            )

            return dict(
                db.execute(
                    "SELECT * FROM companies WHERE company_id=?",
                    (company_id,),
                ).fetchone()
            )

    def register_project(
        self,
        *,
        project_id: str,
        company_id: str,
        slug: str,
        name: str,
        repository_url: str,
        default_branch: str,
        actor: str,
        reason: str,
        description: str = "",
        status: str = "active",
    ) -> dict[str, Any]:

        project_id = _id(project_id, "project_id")
        company_id = _id(company_id, "company_id")
        slug = _slug(slug)
        name = _text(name, "name")
        url = _repo_url(repository_url)
        branch = _text(default_branch, "default_branch", 120)

        description = (
            _text(description, "description", 4000)
            if description else ""
        )

        if status not in PROJECT_STATUSES:
            raise ValidationError(
                f"project status must be one of {sorted(PROJECT_STATUSES)}"
            )

        actor, reason = _actor(actor, reason)
        now = _now()

        with self._write() as db:
            self._company(db, company_id)

            try:
                db.execute(
                    """INSERT INTO projects
                    VALUES(?,?,?,?,?,?,?,?,?,?,1)""",
                    (
                        project_id, company_id, slug, name, description,
                        url, branch, status, now, now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise Conflict(
                    f"Project ID, slug or repository already exists: {exc}"
                ) from exc

            self._event(
                db, company_id, "project", project_id,
                "project.registered", actor, reason,
                {
                    "slug": slug,
                    "name": name,
                    "repository_url": url,
                    "default_branch": branch,
                    "status": status,
                    "version": 1,
                },
            )

            return dict(
                db.execute(
                    "SELECT * FROM projects WHERE project_id=?",
                    (project_id,),
                ).fetchone()
            )

    def register_agent(
        self,
        *,
        agent_id: str,
        company_id: str,
        slug: str,
        display_name: str,
        domain: str,
        definition_path: str,
        role_version: str,
        capabilities: Sequence[str],
        actor: str,
        reason: str,
        status: str = "registered",
    ) -> dict[str, Any]:

        agent_id = _id(agent_id, "agent_id")
        company_id = _id(company_id, "company_id")
        slug = _slug(slug)
        display_name = _text(display_name, "display_name")
        domain = _text(domain, "domain")
        definition_path = _text(definition_path, "definition_path", 500)
        role_version = _text(role_version, "role_version", 40)

        if status not in AGENT_STATUSES:
            raise ValidationError(
                f"agent status must be one of {sorted(AGENT_STATUSES)}"
            )

        if (
            isinstance(capabilities, (str, bytes))
            or not isinstance(capabilities, Sequence)
        ):
            raise ValidationError(
                "capabilities must be a sequence of unique strings"
            )

        caps = sorted({
            _text(c, "capability", 100)
            for c in capabilities
        })

        if not caps or len(caps) != len(capabilities):
            raise ValidationError(
                "capabilities must be non-empty and unique"
            )

        actor, reason = _actor(actor, reason)
        now = _now()
        caps_json = _json(caps)

        with self._write() as db:
            self._company(db, company_id)

            try:
                db.execute(
                    """INSERT INTO agents
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,1)""",
                    (
                        agent_id, company_id, slug, display_name, domain,
                        definition_path, role_version, status,
                        caps_json, now, now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise Conflict(
                    f"Agent ID or slug already exists: {exc}"
                ) from exc

            self._event(
                db, company_id, "agent", agent_id,
                "agent.registered", actor, reason,
                {
                    "slug": slug,
                    "display_name": display_name,
                    "domain": domain,
                    "role_version": role_version,
                    "status": status,
                    "capabilities": caps,
                    "version": 1,
                },
            )

            row = dict(
                db.execute(
                    "SELECT * FROM agents WHERE agent_id=?",
                    (agent_id,),
                ).fetchone()
            )

            row["capabilities"] = json.loads(
                row.pop("capabilities_json")
            )

            return row

    def get_company(self, company_id: str) -> dict[str, Any]:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT * FROM companies WHERE company_id=?",
                (company_id,),
            ).fetchone()

        if row is None:
            raise NotFound(f"Company not found: {company_id}")

        return dict(row)

    def list_projects(self, company_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT * FROM projects WHERE company_id=? ORDER BY slug",
                (company_id,),
            ).fetchall()

        return [dict(row) for row in rows]

    def list_agents(self, company_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT * FROM agents WHERE company_id=? ORDER BY slug",
                (company_id,),
            ).fetchall()

        result = []

        for row in rows:
            item = dict(row)
            item["capabilities"] = json.loads(
                item.pop("capabilities_json")
            )
            result.append(item)

        return result

    def set_configuration(
        self,
        *,
        scope_type: str,
        scope_id: str,
        config_key: str,
        value: Any,
        actor: str,
        reason: str,
        expected_version: int = 0,
    ) -> dict[str, Any]:

        if scope_type not in SCOPE_TYPES:
            raise ValidationError(
                f"scope_type must be one of {sorted(SCOPE_TYPES)}"
            )

        scope_id = _id(scope_id, "scope_id")
        config_key = _text(config_key, "config_key", 160)

        if (
            _SECRET_KEY.search(config_key)
            or config_key.lower() in {"token", "api_token"}
        ):
            raise ValidationError(
                "Do not store secrets in registry config; store a secret-manager reference"
            )

        if not isinstance(expected_version, int) or expected_version < 0:
            raise ValidationError(
                "expected_version must be a non-negative integer"
            )

        actor, reason = _actor(actor, reason)
        now = _now()
        value_json = _json(value)

        with self._write() as db:
            table, key = {
                "company": ("companies", "company_id"),
                "project": ("projects", "project_id"),
                "agent": ("agents", "agent_id"),
            }[scope_type]

            scope = db.execute(
                f"SELECT * FROM {table} WHERE {key}=?",
                (scope_id,),
            ).fetchone()

            if scope is None:
                raise NotFound(f"{scope_type} not found: {scope_id}")

            current = db.execute(
                """SELECT version FROM configurations
                WHERE scope_type=? AND scope_id=? AND config_key=?""",
                (scope_type, scope_id, config_key),
            ).fetchone()

            actual = int(current["version"]) if current else 0

            if actual != expected_version:
                raise Conflict(
                    f"Stale config version: expected {expected_version}, current {actual}"
                )

            version = actual + 1

            db.execute(
                """INSERT INTO configurations
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(scope_type,scope_id,config_key)
                DO UPDATE SET
                    value_json=excluded.value_json,
                    version=excluded.version,
                    updated_by=excluded.updated_by,
                    updated_at=excluded.updated_at""",
                (
                    scope_type, scope_id, config_key,
                    value_json, version, actor, now,
                ),
            )

            company_id = (
                scope_id
                if scope_type == "company"
                else scope["company_id"]
            )

            self._event(
                db, company_id, scope_type, scope_id,
                "configuration.created" if actual == 0
                else "configuration.updated",
                actor, reason,
                {
                    "config_key": config_key,
                    "value": value,
                    "version": version,
                },
            )

        return {
            "scope_type": scope_type,
            "scope_id": scope_id,
            "config_key": config_key,
            "value": value,
            "version": version,
            "updated_by": actor,
            "updated_at": now,
        }

    def get_configuration(
        self,
        *,
        scope_type: str,
        scope_id: str,
        config_key: str,
    ) -> dict[str, Any]:

        if scope_type not in SCOPE_TYPES:
            raise ValidationError(
                f"scope_type must be one of {sorted(SCOPE_TYPES)}"
            )

        with closing(self._connect()) as db:
            row = db.execute(
                """SELECT * FROM configurations
                WHERE scope_type=? AND scope_id=? AND config_key=?""",
                (scope_type, scope_id, config_key),
            ).fetchone()

        if row is None:
            raise NotFound(
                f"Configuration not found: {scope_type}/{scope_id}/{config_key}"
            )

        result = dict(row)
        result["value"] = json.loads(result.pop("value_json"))
        return result

    def list_audit_events(
        self,
        *,
        company_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:

        if not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValidationError(
                "audit event limit must be between 1 and 1000"
            )

        with closing(self._connect()) as db:
            rows = db.execute(
                """SELECT * FROM audit_events
                WHERE company_id=?
                ORDER BY event_id DESC LIMIT ?""",
                (company_id, limit),
            ).fetchall()

        results = []

        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            results.append(item)

        return results

    def transition_status(
        self,
        *,
        entity_type: str,
        entity_id: str,
        new_status: str,
        expected_version: int,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:

        tables = {
            "project": ("projects", "project_id", PROJECT_STATUSES),
            "agent": ("agents", "agent_id", AGENT_STATUSES),
        }

        if entity_type not in tables:
            raise ValidationError(
                "Only project and agent lifecycle transitions are supported in F01"
            )

        table, key, allowed = tables[entity_type]

        if new_status not in allowed:
            raise ValidationError(
                f"status must be one of {sorted(allowed)}"
            )

        actor, reason = _actor(actor, reason)
        now = _now()

        with self._write() as db:
            row = db.execute(
                f"SELECT * FROM {table} WHERE {key}=?",
                (entity_id,),
            ).fetchone()

            if row is None:
                raise NotFound(
                    f"{entity_type} not found: {entity_id}"
                )

            if row["version"] != expected_version:
                raise Conflict(
                    f"Stale {entity_type} version: expected {expected_version}, current {row['version']}"
                )

            db.execute(
                f"""UPDATE {table}
                SET status=?,version=version+1,updated_at=?
                WHERE {key}=? AND version=?""",
                (new_status, now, entity_id, expected_version),
            )

            self._event(
                db, row["company_id"], entity_type, entity_id,
                f"{entity_type}.status_changed",
                actor, reason,
                {
                    "from": row["status"],
                    "to": new_status,
                    "version": expected_version + 1,
                },
            )

            updated = dict(
                db.execute(
                    f"SELECT * FROM {table} WHERE {key}=?",
                    (entity_id,),
                ).fetchone()
            )

        if entity_type == "agent":
            updated["capabilities"] = json.loads(
                updated.pop("capabilities_json")
            )

        return updated

    def bootstrap(
        self,
        *,
        company: Mapping[str, str],
        project: Mapping[str, str],
        agents: Sequence[Mapping[str, Any]],
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        """Atomically create company, initial project and exactly eight agents.

        Identical retries are safe. Existing records are never silently overwritten.
        Any mismatch rolls the complete transaction back.
        """

        actor, reason = _actor(actor, reason)

        if len(agents) != 8:
            raise ValidationError(
                "F01 bootstrap requires exactly eight specialist agent definitions"
            )

        cid = _id(company["company_id"], "company_id")
        cslug = _slug(company["slug"])
        cname = _text(company["name"], "company.name")
        owner = _text(company["owner_name"], "owner_name")
        email = _text(company["owner_email"], "owner_email", 254).lower()

        if not _EMAIL.fullmatch(email):
            raise ValidationError("owner_email is invalid")

        pid = _id(project["project_id"], "project_id")

        if _id(project["company_id"], "project.company_id") != cid:
            raise ValidationError(
                "bootstrap project must belong to the bootstrap company"
            )

        pslug = _slug(project["slug"])
        pname = _text(project["name"], "project.name")
        purl = _repo_url(project["repository_url"])
        branch = _text(
            project.get("default_branch", "main"),
            "default_branch",
            120,
        )

        description = str(project.get("description", ""))
        pstatus = project.get("status", "active")

        if pstatus not in PROJECT_STATUSES or len(description) > 4000:
            raise ValidationError(
                "project status or description is invalid"
            )

        now = _now()
        created = {
            "company": False,
            "project": False,
            "agents": 0,
        }

        with self._write() as db:

            existing = db.execute(
                "SELECT * FROM companies WHERE company_id=?",
                (cid,),
            ).fetchone()

            cvalues = (cslug, cname, owner, email)

            if existing is None:
                db.execute(
                    """INSERT INTO companies
                    VALUES(?,?,?,?,?,'active',?,?,1)""",
                    (cid, *cvalues, now, now),
                )

                self._event(
                    db, cid, "company", cid,
                    "company.registered", actor, reason,
                    {
                        "slug": cslug,
                        "name": cname,
                        "owner_email": email,
                        "version": 1,
                    },
                )

                created["company"] = True

            elif tuple(
                existing[k]
                for k in ("slug", "name", "owner_name", "owner_email")
            ) != cvalues:

                raise IntegrityViolation(
                    "Existing company differs; bootstrap refused to overwrite it"
                )

            old_project = db.execute(
                "SELECT * FROM projects WHERE project_id=?",
                (pid,),
            ).fetchone()

            pvalues = (
                cid, pslug, pname, description,
                purl, branch, pstatus,
            )

            if old_project is None:
                db.execute(
                    """INSERT INTO projects
                    VALUES(?,?,?,?,?,?,?,?,?,?,1)""",
                    (pid, *pvalues, now, now),
                )

                self._event(
                    db, cid, "project", pid,
                    "project.registered", actor, reason,
                    {
                        "slug": pslug,
                        "name": pname,
                        "repository_url": purl,
                        "default_branch": branch,
                        "status": pstatus,
                        "version": 1,
                    },
                )

                created["project"] = True

            elif tuple(
                old_project[k]
                for k in (
                    "company_id", "slug", "name", "description",
                    "repository_url", "default_branch", "status",
                )
            ) != pvalues:

                raise IntegrityViolation(
                    "Existing project differs; bootstrap refused to overwrite it"
                )

            ids, slugs = set(), set()

            for spec in agents:
                aid = _id(spec["agent_id"], "agent_id")
                aslug = _slug(spec["slug"])
                display = _text(spec["display_name"], "display_name")
                domain = _text(spec["domain"], "domain")
                path = _text(spec["definition_path"], "definition_path", 500)

                role = _text(
                    spec.get("role_version", "1.0.0"),
                    "role_version",
                    40,
                )

                status = spec.get("status", "registered")
                caps_in = spec["capabilities"]

                if (
                    status not in AGENT_STATUSES
                    or isinstance(caps_in, (str, bytes))
                    or not isinstance(caps_in, Sequence)
                ):
                    raise ValidationError(
                        "agent status or capabilities are invalid"
                    )

                caps = sorted({
                    _text(c, "capability", 100)
                    for c in caps_in
                })

                if (
                    not caps
                    or len(caps) != len(caps_in)
                    or aid in ids
                    or aslug in slugs
                ):
                    raise ValidationError(
                        "agent IDs/slugs and capabilities must be unique and non-empty"
                    )

                ids.add(aid)
                slugs.add(aslug)
                caps_json = _json(caps)

                old = db.execute(
                    "SELECT * FROM agents WHERE agent_id=?",
                    (aid,),
                ).fetchone()

                values = (
                    cid, aslug, display, domain,
                    path, role, status, caps_json,
                )

                if old is None:
                    db.execute(
                        """INSERT INTO agents
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,1)""",
                        (aid, *values, now, now),
                    )

                    self._event(
                        db, cid, "agent", aid,
                        "agent.registered", actor, reason,
                        {
                            "slug": aslug,
                            "display_name": display,
                            "domain": domain,
                            "role_version": role,
                            "status": status,
                            "capabilities": caps,
                            "version": 1,
                        },
                    )

                    created["agents"] += 1

                elif tuple(
                    old[k]
                    for k in (
                        "company_id", "slug", "display_name",
                        "domain", "definition_path", "role_version",
                        "status", "capabilities_json",
                    )
                ) != values:

                    raise IntegrityViolation(
                        f"Existing agent differs; bootstrap refused to overwrite {aid}"
                    )

        return {
            "company_id": cid,
            "project_id": pid,
            "agent_count": len(agents),
            "created": created,
            "idempotent": not (
                created["company"] or created["project"] or created["agents"]
            ),
        }

    def verify_audit_chain(self) -> dict[str, Any]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT * FROM audit_events ORDER BY event_id"
            ).fetchall()

        previous = _GENESIS

        for expected, row in enumerate(rows, 1):
            if (
                row["event_id"] != expected
                or row["previous_hash"] != previous
            ):
                return {
                    "valid": False,
                    "event_id": row["event_id"],
                    "reason": "sequence or previous-hash mismatch",
                }

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

            digest = hashlib.sha256(
                _json(event).encode()
            ).hexdigest()

            if digest != row["event_hash"]:
                return {
                    "valid": False,
                    "event_id": row["event_id"],
                    "reason": "event hash mismatch",
                }

            previous = row["event_hash"]

        return {
            "valid": True,
            "events_checked": len(rows),
            "head_hash": previous,
        }

    def validate(self, company_id: str) -> dict[str, Any]:
        with closing(self._connect()) as db:
            company = db.execute(
                "SELECT * FROM companies WHERE company_id=?",
                (company_id,),
            ).fetchone()

            if company is None:
                raise NotFound(f"Company not found: {company_id}")

            project_count = db.execute(
                "SELECT COUNT(*) FROM projects WHERE company_id=?",
                (company_id,),
            ).fetchone()[0]

            agent_count = db.execute(
                "SELECT COUNT(*) FROM agents WHERE company_id=?",
                (company_id,),
            ).fetchone()[0]

            fk_errors = db.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()

            sqlite_integrity = db.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0]

        chain = self.verify_audit_chain()
        issues = []

        if sqlite_integrity != "ok":
            issues.append(
                f"SQLite integrity check: {sqlite_integrity}"
            )

        if fk_errors:
            issues.append(
                f"Foreign-key violations: {len(fk_errors)}"
            )

        if not chain["valid"]:
            issues.append(
                f"Audit chain invalid: {chain.get('reason')}"
            )

        return {
            "valid": not issues,
            "company_id": company_id,
            "company_status": company["status"],
            "project_count": project_count,
            "agent_count": agent_count,
            "audit_events_checked": chain.get("events_checked", 0),
            "issues": issues,
        }
