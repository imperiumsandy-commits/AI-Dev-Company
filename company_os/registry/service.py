"""Application-level F01 registry contract and safety enforcement.

The SQLite implementation in :mod:`company_os.registry.core` remains the
storage adapter. This service adds the company-specific canonical roster,
configuration secret guardrails, lifecycle transition rules, and integrity
checks required by the public registry API.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from typing import Any, Mapping, Sequence

from . import core as _core
from .catalog import DEFAULT_AGENTS


_BASE_REGISTRY_STORE = _core.RegistryStore

CANONICAL_COMPANY_ID = "co_ai_dev_company"
CANONICAL_COMPANY_SLUG = "ai-dev-company"
CANONICAL_COMPANY_NAME = "AI Software Engineering Company"
CANONICAL_PROJECT_ID = "prj_ai_dev_company"
CANONICAL_PROJECT_NAME = "AI-Dev-Company"
CANONICAL_REPOSITORY_URL = (
    "https://github.com/imperiumsandy-commits/AI-Dev-Company"
)
CANONICAL_DEFAULT_BRANCH = "main"

_PROJECT_TRANSITIONS = {
    "planned": {"active", "paused", "archived"},
    "active": {"paused", "archived"},
    "paused": {"active", "archived"},
    "archived": set(),
}
_AGENT_TRANSITIONS = {
    "planned": {"registered", "retired"},
    "registered": {"active", "paused", "retired"},
    "active": {"paused", "retired"},
    "paused": {"active", "retired"},
    "retired": set(),
}

_SECRET_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.I),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bxai-[A-Za-z0-9_-]{20,}\b", re.I),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b", re.I),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b", re.I),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}\b", re.I),
)
_SECRET_FIELD_PARTS = (
    "password",
    "passwd",
    "credential",
    "secret",
    "apikey",
    "privatekey",
    "clientsecret",
    "authheader",
    "accesstoken",
    "refreshtoken",
    "authtoken",
    "bearertoken",
)
_SECRET_FIELD_EXACT = {
    "secret",
    "token",
    "authorization",
    "credentials",
}
_SAFE_REFERENCE_SCHEMES = (
    "env://",
    "vault://",
    "secret://",
    "aws-secretsmanager://",
    "gcp-secret://",
    "azure-keyvault://",
)


def _normalise_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _is_secret_field(value: Any) -> bool:
    key = _normalise_key(value)
    return (
        key in _SECRET_FIELD_EXACT
        or any(part in key for part in _SECRET_FIELD_PARTS)
        or key.endswith("token")
        or any(
            marker in key
            for marker in ("tokenvalue", "tokensecret", "tokenkey", "tokenmaterial")
        )
    )


def _is_safe_secret_reference(key: Any, value: Any) -> bool:
    normalised = _normalise_key(key)
    is_reference = normalised.endswith("ref") or normalised.endswith("reference")
    return (
        is_reference
        and isinstance(value, str)
        and value.strip().lower().startswith(_SAFE_REFERENCE_SCHEMES)
    )


def _find_secret(value: Any, path: str = "value") -> str | None:
    """Return a safe field path when a likely credential is found."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if _is_secret_field(key) and not _is_safe_secret_reference(key, child):
                return child_path
            finding = _find_secret(child, child_path)
            if finding:
                return finding
        return None

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            finding = _find_secret(child, f"{path}[{index}]")
            if finding:
                return finding
        return None

    if isinstance(value, str):
        for pattern in _SECRET_VALUE_PATTERNS:
            if pattern.search(value):
                return path

    return None


def _expected_agent_fields(spec: Mapping[str, Any]) -> dict[str, Any]:
    capabilities = spec.get("capabilities")
    if (
        isinstance(capabilities, (str, bytes, bytearray))
        or not isinstance(capabilities, Sequence)
    ):
        raise _core.ValidationError(
            "Canonical specialist capabilities must be a sequence of strings"
        )

    values = [
        _core._text(item, "capability", 100)
        for item in capabilities
    ]
    if not values or len(values) != len(set(values)):
        raise _core.ValidationError(
            "Canonical specialist capabilities must be non-empty and unique"
        )

    return {
        "agent_id": _core._id(spec.get("agent_id"), "agent_id"),
        "slug": _core._slug(spec.get("slug")),
        "display_name": _core._text(spec.get("display_name"), "display_name"),
        "domain": _core._text(spec.get("domain"), "domain"),
        "definition_path": _core._text(
            spec.get("definition_path"), "definition_path", 500
        ),
        "role_version": _core._text(
            spec.get("role_version", "1.0.0"), "role_version", 40
        ),
        "capabilities": sorted(values),
    }


def _project_static_fields(project: Mapping[str, Any]) -> tuple[Any, ...]:
    description = project.get("description", "")
    return (
        project.get("company_id"),
        project.get("slug"),
        project.get("name"),
        description,
        project.get("repository_url"),
        project.get("default_branch", "main"),
    )


def _stored_project_static_fields(project: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        project["company_id"],
        project["slug"],
        project["name"],
        project["description"],
        project["repository_url"],
        project["default_branch"],
    )


def _agent_static_fields(agent: Mapping[str, Any]) -> tuple[Any, ...]:
    capabilities = agent.get("capabilities", [])
    if isinstance(capabilities, str):
        capabilities = []
    return (
        agent.get("slug"),
        agent.get("display_name"),
        agent.get("domain"),
        agent.get("definition_path"),
        agent.get("role_version", "1.0.0"),
        tuple(sorted(capabilities)),
    )


class RegistryStore(_BASE_REGISTRY_STORE):
    """Hardened public registry service over the transactional SQLite adapter."""

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
        if scope_type not in _core.SCOPE_TYPES:
            raise _core.ValidationError(
                f"scope_type must be one of {sorted(_core.SCOPE_TYPES)}"
            )

        scope_id = _core._id(scope_id, "scope_id")
        config_key = _core._text(config_key, "config_key", 160)
        if _is_secret_field(config_key) and not _is_safe_secret_reference(
            config_key, value
        ):
            raise _core.ValidationError(
                "Do not store credentials in registry configuration; "
                "store an approved secret-manager reference instead"
            )

        finding = _find_secret(value)
        if finding:
            raise _core.ValidationError(
                f"Credential-like data is not allowed in registry configuration ({finding})"
            )

        if (
            not isinstance(expected_version, int)
            or isinstance(expected_version, bool)
            or expected_version < 0
        ):
            raise _core.ValidationError(
                "expected_version must be a non-negative integer"
            )

        actor, reason = _core._actor(actor, reason)
        now = _core._now()
        value_json = _core._json(value)
        tables = {
            "company": ("companies", "company_id"),
            "project": ("projects", "project_id"),
            "agent": ("agents", "agent_id"),
        }
        table, key = tables[scope_type]

        with self._write() as db:
            scope = db.execute(
                f"SELECT * FROM {table} WHERE {key}=?",
                (scope_id,),
            ).fetchone()
            if scope is None:
                raise _core.NotFound(f"{scope_type} not found: {scope_id}")

            current = db.execute(
                """SELECT version FROM configurations
                WHERE scope_type=? AND scope_id=? AND config_key=?""",
                (scope_type, scope_id, config_key),
            ).fetchone()
            actual = int(current["version"]) if current else 0
            if actual != expected_version:
                raise _core.Conflict(
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
                scope_id if scope_type == "company" else scope["company_id"]
            )
            self._event(
                db,
                company_id,
                scope_type,
                scope_id,
                "configuration.created" if actual == 0 else "configuration.updated",
                actor,
                reason,
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
        rules = {
            "project": ("projects", "project_id", _PROJECT_TRANSITIONS),
            "agent": ("agents", "agent_id", _AGENT_TRANSITIONS),
        }
        if entity_type not in rules:
            return super().transition_status(
                entity_type=entity_type,
                entity_id=entity_id,
                new_status=new_status,
                expected_version=expected_version,
                actor=actor,
                reason=reason,
            )

        table, key, transitions = rules[entity_type]
        with closing(self._connect()) as db:
            current = db.execute(
                f"SELECT status,version FROM {table} WHERE {key}=?",
                (entity_id,),
            ).fetchone()

        if current is None:
            raise _core.NotFound(f"{entity_type} not found: {entity_id}")
        if current["version"] != expected_version:
            raise _core.Conflict(
                f"Stale {entity_type} version: expected {expected_version}, current {current['version']}"
            )
        allowed = transitions.get(current["status"], set())
        if new_status not in allowed:
            raise _core.ValidationError(
                f"Illegal {entity_type} transition: "
                f"{current['status']} -> {new_status}"
            )

        return super().transition_status(
            entity_type=entity_type,
            entity_id=entity_id,
            new_status=new_status,
            expected_version=expected_version,
            actor=actor,
            reason=reason,
        )

    def _validate_canonical_bootstrap(
        self,
        company: Mapping[str, Any],
        project: Mapping[str, Any],
        agents: Sequence[Mapping[str, Any]],
    ) -> None:
        if company.get("company_id") != CANONICAL_COMPANY_ID:
            return

        # Existing records are compared inside the adapter's single write
        # transaction so callers retain the established IntegrityViolation
        # contract and no partial state can escape. Strict preflight validation
        # is applied only to the first bootstrap.
        with closing(self._connect()) as db:
            existing_company = db.execute(
                "SELECT 1 FROM companies WHERE company_id=?",
                (CANONICAL_COMPANY_ID,),
            ).fetchone()
        if existing_company is not None:
            return

        if (
            company.get("slug") != CANONICAL_COMPANY_SLUG
            or company.get("name") != CANONICAL_COMPANY_NAME
        ):
            raise _core.ValidationError(
                "Canonical company identity does not match the F01 contract"
            )

        expected_project = {
            "project_id": CANONICAL_PROJECT_ID,
            "company_id": CANONICAL_COMPANY_ID,
            "slug": CANONICAL_COMPANY_SLUG,
            "name": CANONICAL_PROJECT_NAME,
            "repository_url": CANONICAL_REPOSITORY_URL,
            "default_branch": CANONICAL_DEFAULT_BRANCH,
        }
        for key, expected in expected_project.items():
            actual = project.get(key, "main" if key == "default_branch" else None)
            if actual != expected:
                raise _core.ValidationError(
                    f"Canonical project field '{key}' does not match the F01 contract"
                )
        if project.get("description", "") != "":
            raise _core.ValidationError(
                "Canonical project description must remain empty until explicitly specified"
            )

        if (
            isinstance(agents, (str, bytes, bytearray))
            or not isinstance(agents, Sequence)
            or len(agents) != len(DEFAULT_AGENTS)
        ):
            raise _core.ValidationError(
                "Canonical F01 bootstrap requires exactly the eight catalog specialists"
            )

        expected = {
            item["agent_id"]: _expected_agent_fields(item)
            for item in DEFAULT_AGENTS
        }
        actual: dict[str, dict[str, Any]] = {}
        slugs: set[str] = set()
        for item in agents:
            if not isinstance(item, Mapping):
                raise _core.ValidationError(
                    "Every canonical specialist definition must be an object"
                )
            fields = _expected_agent_fields(item)
            if fields["agent_id"] in actual or fields["slug"] in slugs:
                raise _core.ValidationError(
                    "Canonical specialist IDs and slugs must be unique"
                )
            if item.get("status", "registered") != "registered":
                raise _core.ValidationError(
                    "Agents must be registered, not activated by bootstrap"
                )
            actual[fields["agent_id"]] = fields
            slugs.add(fields["slug"])

        if actual != expected:
            raise _core.ValidationError(
                "Specialist definitions do not exactly match the canonical eight-agent catalog"
            )

    def bootstrap(
        self,
        *,
        company: Mapping[str, str],
        project: Mapping[str, str],
        agents: Sequence[Mapping[str, Any]],
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        self._validate_canonical_bootstrap(company, project, agents)

        if company.get("company_id") == CANONICAL_COMPANY_ID:
            effective_project = dict(project)
            effective_agents = [dict(item) for item in agents]

            existing_projects = {
                row["project_id"]: row
                for row in self.list_projects(CANONICAL_COMPANY_ID)
            }
            previous_project = existing_projects.get(CANONICAL_PROJECT_ID)
            if previous_project is not None and (
                _stored_project_static_fields(previous_project)
                == _project_static_fields(effective_project)
            ):
                # Bootstrap retry must preserve an operational lifecycle state.
                effective_project["status"] = previous_project["status"]

            existing_agents = {
                row["agent_id"]: row
                for row in self.list_agents(CANONICAL_COMPANY_ID)
            }
            for spec in effective_agents:
                previous = existing_agents.get(spec["agent_id"])
                if previous is not None and (
                    _agent_static_fields(previous) == _agent_static_fields(spec)
                ):
                    # Bootstrap retry must not reset a specialist's lifecycle.
                    spec["status"] = previous["status"]

            project = effective_project
            agents = effective_agents

        return super().bootstrap(
            company=company,
            project=project,
            agents=agents,
            actor=actor,
            reason=reason,
        )

    def validate(self, company_id: str) -> dict[str, Any]:
        try:
            result = super().validate(company_id)
        except (sqlite3.Error, ValueError, TypeError, KeyError) as exc:
            return {
                "valid": False,
                "company_id": company_id,
                "project_count": 0,
                "agent_count": 0,
                "audit_events_checked": 0,
                "issues": [f"Registry validation could not complete: {exc}"],
            }

        issues = list(result.get("issues", []))
        contracts: dict[str, Any] = {
            "schema_version_valid": False,
            "append_only_triggers_valid": False,
            "configuration_scopes_valid": True,
            "configuration_values_valid": True,
            "canonical_catalog_valid": None,
        }

        try:
            with closing(self._connect()) as db:
                schema_version = db.execute(
                    "PRAGMA user_version"
                ).fetchone()[0]
                migration = db.execute(
                    "SELECT checksum FROM schema_migrations WHERE version=?",
                    (_core.SCHEMA_VERSION,),
                ).fetchone()
                expected_checksum = hashlib.sha256(
                    _core._SCHEMA.encode("utf-8")
                ).hexdigest()
                contracts["schema_version_valid"] = (
                    schema_version == _core.SCHEMA_VERSION
                    and migration is not None
                    and migration["checksum"] == expected_checksum
                )
                if not contracts["schema_version_valid"]:
                    issues.append("Registry schema migration/version checksum is invalid.")

                trigger_rows = db.execute(
                    "SELECT name,sql FROM sqlite_master WHERE type='trigger'"
                ).fetchall()
                triggers = {row["name"]: row["sql"] for row in trigger_rows}
                expected_trigger_sql = {
                    "audit_events_no_update": (
                        "create trigger audit_events_no_update before update on audit_events "
                        "begin select raise(abort,'audit_events is append-only'); end"
                    ),
                    "audit_events_no_delete": (
                        "create trigger audit_events_no_delete before delete on audit_events "
                        "begin select raise(abort,'audit_events is append-only'); end"
                    ),
                }
                actual_trigger_sql = {
                    name: re.sub(r"\s+", " ", (sql or "").strip()).rstrip(";").lower()
                    for name, sql in triggers.items()
                }
                contracts["append_only_triggers_valid"] = all(
                    actual_trigger_sql.get(name) == expected_sql
                    for name, expected_sql in expected_trigger_sql.items()
                )
                if not contracts["append_only_triggers_valid"]:
                    issues.append("Registry audit append-only protection is incomplete.")

                scope_tables = {
                    "company": ("companies", "company_id"),
                    "project": ("projects", "project_id"),
                    "agent": ("agents", "agent_id"),
                }
                configurations = db.execute(
                    "SELECT scope_type,scope_id,config_key,value_json FROM configurations"
                ).fetchall()
                for row in configurations:
                    scope = scope_tables.get(row["scope_type"])
                    if scope is None:
                        contracts["configuration_scopes_valid"] = False
                        issues.append("Registry contains a configuration with an invalid scope type.")
                        continue
                    table, key = scope
                    exists = db.execute(
                        f"SELECT 1 FROM {table} WHERE {key}=?",
                        (row["scope_id"],),
                    ).fetchone()
                    if exists is None:
                        contracts["configuration_scopes_valid"] = False
                        issues.append(
                            f"Registry configuration references a missing {row['scope_type']} scope."
                        )
                    try:
                        value = json.loads(row["value_json"])
                        _core._json(value)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        contracts["configuration_values_valid"] = False
                        issues.append("Registry contains a configuration with invalid JSON data.")
                        continue
                    finding = _find_secret(value, "configuration")
                    if finding or (
                        _is_secret_field(row["config_key"])
                        and not _is_safe_secret_reference(row["config_key"], value)
                    ):
                        contracts["configuration_values_valid"] = False
                        issues.append(
                            "Registry configuration contains credential-like data "
                            "that must be migrated to a secret manager."
                        )

                audit_rows = db.execute(
                    "SELECT event_id,payload_json FROM audit_events ORDER BY event_id"
                ).fetchall()
                for event_row in audit_rows:
                    try:
                        payload = json.loads(event_row["payload_json"])
                    except json.JSONDecodeError:
                        # The base audit-chain verification reports malformed
                        # payload JSON; keep this contract check independently safe.
                        continue
                    finding = _find_secret(payload, "audit_payload")
                    if isinstance(payload, Mapping):
                        config_key = payload.get("config_key")
                        config_value = payload.get("value")
                        if (
                            _is_secret_field(config_key)
                            and not _is_safe_secret_reference(config_key, config_value)
                        ) or _find_secret(config_value, "audit_payload.value"):
                            finding = finding or "audit_payload.configuration"
                    if finding:
                        contracts["configuration_values_valid"] = False
                        issues.append(
                            "Registry audit history contains credential-like data "
                            "that must be migrated to a secret manager."
                        )

        except sqlite3.Error as exc:
            issues.append(f"Registry contract inspection failed: {exc}")

        if company_id == CANONICAL_COMPANY_ID:
            canonical_issues: list[str] = []
            try:
                company = self.get_company(company_id)
                if (
                    company["slug"] != CANONICAL_COMPANY_SLUG
                    or company["name"] != CANONICAL_COMPANY_NAME
                ):
                    canonical_issues.append("Canonical company identity fields do not match the F01 contract.")

                projects = {
                    row["project_id"]: row
                    for row in self.list_projects(company_id)
                }
                project = projects.get(CANONICAL_PROJECT_ID)
                if project is None:
                    canonical_issues.append("Canonical AI-Dev-Company project record is missing.")
                else:
                    expected_project = {
                        "company_id": CANONICAL_COMPANY_ID,
                        "slug": CANONICAL_COMPANY_SLUG,
                        "name": CANONICAL_PROJECT_NAME,
                        "description": "",
                        "repository_url": CANONICAL_REPOSITORY_URL,
                        "default_branch": CANONICAL_DEFAULT_BRANCH,
                    }
                    for key, expected in expected_project.items():
                        if project[key] != expected:
                            canonical_issues.append(
                                f"Canonical project field '{key}' does not match the F01 contract."
                            )

                expected_specs = {
                    item["agent_id"]: _expected_agent_fields(item)
                    for item in DEFAULT_AGENTS
                }
                actual_agents = {
                    item["agent_id"]: item
                    for item in self.list_agents(company_id)
                }
                if set(actual_agents) != set(expected_specs):
                    canonical_issues.append(
                        "Registered specialist identities do not exactly match the canonical eight-agent catalog."
                    )
                for agent_id, expected in expected_specs.items():
                    actual = actual_agents.get(agent_id)
                    if actual is None:
                        continue
                    for key in (
                        "slug",
                        "display_name",
                        "domain",
                        "definition_path",
                        "role_version",
                        "capabilities",
                    ):
                        actual_value = actual.get(key)
                        if key == "capabilities":
                            actual_value = sorted(actual_value or [])
                        if actual_value != expected[key]:
                            canonical_issues.append(
                                f"Specialist '{agent_id}' field '{key}' does not match the canonical catalog."
                            )
            except (sqlite3.Error, ValueError, TypeError, KeyError) as exc:
                canonical_issues.append(
                    f"Canonical company contract could not be validated: {exc}"
                )

            contracts["canonical_catalog_valid"] = not canonical_issues
            issues.extend(canonical_issues)

        # Keep the report deterministic and avoid repeating the same finding.
        issues = list(dict.fromkeys(issues))
        return {
            **result,
            "valid": not issues,
            "issues": issues,
            "contract_validation": contracts,
        }
