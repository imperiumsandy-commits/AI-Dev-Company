"""Hardened F01 registry service over the SQLite storage adapter.

The SQLite adapter owns schema, transactions and the audit hash chain. This
service owns the public F01 contract: canonical company/project identities,
the exact eight-specialist roster, lifecycle transitions, configuration
secret guardrails, and deep integrity reporting.

This module does not call model providers or execute agents.
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

# The package initializer publishes the raw adapter under this stable name
# before importing this module. The service must always inherit that raw class,
# never the public compatibility alias installed after this module loads.
_BASE_REGISTRY_STORE = getattr(_core, "SQLiteRegistryStore", _core.RegistryStore)

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
    "planned": frozenset({"active", "paused", "archived"}),
    "active": frozenset({"paused", "archived"}),
    "paused": frozenset({"active", "archived"}),
    "archived": frozenset(),
}
_AGENT_TRANSITIONS = {
    "planned": frozenset({"registered", "retired"}),
    "registered": frozenset({"active", "paused", "retired"}),
    "active": frozenset({"paused", "retired"}),
    "paused": frozenset({"active", "retired"}),
    "retired": frozenset(),
}

# These are conservative detectors, not a universal secret classifier. They
# catch common credential formats and secret-bearing field names. Arbitrary
# opaque strings still require a real secret manager and data-handling policy.
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
_SECRET_FIELD_MARKERS = (
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
    "tokenvalue",
    "tokensecret",
    "tokenkey",
    "tokenmaterial",
)
_SECRET_FIELD_EXACT = frozenset({
    "secret",
    "token",
    "authorization",
    "credentials",
    "password",
    "passwd",
})
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
    if key in {
        "tokenbudget",
        "maxtokens",
        "inputtokenbudget",
        "outputtokenbudget",
    }:
        return False

    return (
        key in _SECRET_FIELD_EXACT
        or any(marker in key for marker in _SECRET_FIELD_MARKERS)
        or key.endswith("token")
        or "tokenref" in key
        or "tokenreference" in key
    )


def _is_safe_secret_reference(key: Any, value: Any) -> bool:
    normalised = _normalise_key(key)
    is_reference_key = (
        normalised.endswith("ref")
        or normalised.endswith("reference")
    )
    if not is_reference_key or not isinstance(value, str):
        return False

    reference = value.strip()
    lowered = reference.lower()
    if any(char.isspace() for char in reference):
        return False

    # A scheme without a resource identifier is not a usable secret reference.
    for scheme in _SAFE_REFERENCE_SCHEMES:
        if lowered.startswith(scheme):
            resource = reference[len(scheme):].strip("/")
            return bool(resource)

    return False


def _find_secret(value: Any, path: str = "value") -> str | None:
    """Return the first suspicious field path without returning secret data."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if _is_secret_field(key) and not _is_safe_secret_reference(
                key, child
            ):
                return child_path

            finding = _find_secret(child, child_path)
            if finding:
                return finding
        return None

    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
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
        "display_name": _core._text(
            spec.get("display_name"), "display_name"
        ),
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
    return (
        project.get("company_id"),
        project.get("slug"),
        project.get("name"),
        project.get("description", ""),
        project.get("repository_url"),
        project.get("default_branch", CANONICAL_DEFAULT_BRANCH),
    )


def _stored_project_static_fields(
    project: Mapping[str, Any],
) -> tuple[Any, ...]:
    return (
        project["company_id"],
        project["slug"],
        project["name"],
        project["description"],
        project["repository_url"],
        project["default_branch"],
    )


def _agent_static_fields(agent: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        agent.get("slug"),
        agent.get("display_name"),
        agent.get("domain"),
        agent.get("definition_path"),
        agent.get("role_version", "1.0.0"),
        tuple(sorted(agent.get("capabilities") or [])),
    )


def _normalise_trigger_sql(sql: str | None) -> str:
    return re.sub(r"\s+", " ", (sql or "").strip()).rstrip(";").lower()


class RegistryStore(_BASE_REGISTRY_STORE):
    """Public F01 registry with canonical contracts and security guardrails."""

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
        normalized_id = _core._id(company_id, "company_id")
        if normalized_id == CANONICAL_COMPANY_ID and (
            slug != CANONICAL_COMPANY_SLUG
            or name != CANONICAL_COMPANY_NAME
        ):
            raise _core.ValidationError(
                "Canonical company identity does not match the F01 contract"
            )

        return super().register_company(
            company_id=normalized_id,
            slug=slug,
            name=name,
            owner_name=owner_name,
            owner_email=owner_email,
            actor=actor,
            reason=reason,
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
        normalized_company_id = _core._id(company_id, "company_id")

        if normalized_company_id == CANONICAL_COMPANY_ID:
            if status != "registered":
                raise _core.ValidationError(
                    "Canonical specialists must enter the registry as registered"
                )

            supplied = _expected_agent_fields({
                "agent_id": agent_id,
                "slug": slug,
                "display_name": display_name,
                "domain": domain,
                "definition_path": definition_path,
                "role_version": role_version,
                "capabilities": capabilities,
            })
            expected = {
                item["agent_id"]: _expected_agent_fields(item)
                for item in DEFAULT_AGENTS
            }
            if expected.get(supplied["agent_id"]) != supplied:
                raise _core.ValidationError(
                    "Canonical company accepts only the eight catalog specialists"
                )

        return super().register_agent(
            agent_id=agent_id,
            company_id=normalized_company_id,
            slug=slug,
            display_name=display_name,
            domain=domain,
            definition_path=definition_path,
            role_version=role_version,
            capabilities=capabilities,
            actor=actor,
            reason=reason,
            status=status,
        )

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
        if (
            not isinstance(scope_type, str)
            or scope_type not in _core.SCOPE_TYPES
        ):
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
                "Credential-like data is not allowed in registry configuration "
                f"({finding})"
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
                raise _core.NotFound(
                    f"{scope_type} not found: {scope_id}"
                )

            current = db.execute(
                """SELECT version FROM configurations
                WHERE scope_type=? AND scope_id=? AND config_key=?""",
                (scope_type, scope_id, config_key),
            ).fetchone()
            actual_version = int(current["version"]) if current else 0

            if actual_version != expected_version:
                raise _core.Conflict(
                    f"Stale config version: expected {expected_version}, "
                    f"current {actual_version}"
                )

            version = actual_version + 1
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
                    scope_type,
                    scope_id,
                    config_key,
                    value_json,
                    version,
                    actor,
                    now,
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
                "configuration.created" if actual_version == 0
                else "configuration.updated",
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

    def get_configuration(
        self,
        *,
        scope_type: str,
        scope_id: str,
        config_key: str,
    ) -> dict[str, Any]:
        scope_id = _core._id(scope_id, "scope_id")
        config_key = _core._text(config_key, "config_key", 160)
        return super().get_configuration(
            scope_type=scope_type,
            scope_id=scope_id,
            config_key=config_key,
        )

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
        if not isinstance(entity_type, str) or entity_type not in rules:
            raise _core.ValidationError(
                "Only project and agent lifecycle transitions are supported in F01"
            )

        entity_id = _core._id(entity_id, "entity_id")
        new_status = _core._text(new_status, "new_status", 40)
        if (
            not isinstance(expected_version, int)
            or isinstance(expected_version, bool)
            or expected_version < 1
        ):
            raise _core.ValidationError(
                "expected_version must be a positive integer"
            )

        table, key, transitions = rules[entity_type]
        with closing(self._connect()) as db:
            current = db.execute(
                f"SELECT status,version FROM {table} WHERE {key}=?",
                (entity_id,),
            ).fetchone()

        if current is None:
            raise _core.NotFound(
                f"{entity_type} not found: {entity_id}"
            )
        if current["version"] != expected_version:
            raise _core.Conflict(
                f"Stale {entity_type} version: expected {expected_version}, "
                f"current {current['version']}"
            )

        allowed = transitions.get(current["status"], frozenset())
        if new_status not in allowed:
            raise _core.ValidationError(
                f"Illegal {entity_type} transition: "
                f"{current['status']} -> {new_status}"
            )

        # The base adapter repeats the version check inside BEGIN IMMEDIATE.
        # A concurrent transition between the read and write fails as Conflict.
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
    ) -> str:
        if not isinstance(company, Mapping) or not isinstance(project, Mapping):
            raise _core.ValidationError(
                "company and project definitions must be objects"
            )

        normalized_company_id = _core._id(
            company.get("company_id"), "company_id"
        )
        if (
            isinstance(agents, (str, bytes, bytearray))
            or not isinstance(agents, Sequence)
            or len(agents) != 8
        ):
            raise _core.ValidationError(
                "F01 bootstrap requires exactly eight specialist agent definitions"
            )
        if any(not isinstance(item, Mapping) for item in agents):
            raise _core.ValidationError(
                "Every specialist definition must be an object"
            )
        if normalized_company_id != CANONICAL_COMPANY_ID:
            return normalized_company_id

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
        for key, expected_value in expected_project.items():
            actual = project.get(
                key,
                CANONICAL_DEFAULT_BRANCH if key == "default_branch" else None,
            )
            if actual != expected_value:
                raise _core.ValidationError(
                    f"Canonical project field '{key}' does not match the F01 contract"
                )

        if project.get("description", "") != "":
            raise _core.ValidationError(
                "Canonical project description must remain empty "
                "until explicitly specified"
            )
        if project.get("status", "active") != "active":
            raise _core.ValidationError(
                "Canonical project bootstrap status must be active"
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
                "Specialist definitions do not exactly match "
                "the canonical eight-agent catalog"
            )

        return normalized_company_id

    def bootstrap(
        self,
        *,
        company: Mapping[str, str],
        project: Mapping[str, str],
        agents: Sequence[Mapping[str, Any]],
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        normalized_company_id = self._validate_canonical_bootstrap(
            company, project, agents
        )

        company_payload = dict(company)
        project_payload = dict(project)
        company_payload["company_id"] = normalized_company_id
        project_payload["company_id"] = _core._id(
            project_payload.get("company_id"), "project.company_id"
        )

        effective_agents = [dict(item) for item in agents]
        if normalized_company_id == CANONICAL_COMPANY_ID:
            # Reads happen before the adapter transaction. The base adapter
            # re-checks every existing record atomically before committing.
            existing_agents = {
                row["agent_id"]: row
                for row in self.list_agents(CANONICAL_COMPANY_ID)
            }
            expected_agent_ids = {
                item["agent_id"] for item in DEFAULT_AGENTS
            }
            unexpected_agent_ids = set(existing_agents) - expected_agent_ids
            if unexpected_agent_ids:
                unexpected = ", ".join(sorted(unexpected_agent_ids))
                raise _core.ValidationError(
                    "Existing specialists fall outside the canonical eight-agent "
                    f"catalog: {unexpected}"
                )

            existing_projects = {
                row["project_id"]: row
                for row in self.list_projects(CANONICAL_COMPANY_ID)
            }
            previous_project = existing_projects.get(CANONICAL_PROJECT_ID)
            if previous_project is not None and (
                _stored_project_static_fields(previous_project)
                == _project_static_fields(project_payload)
            ):
                project_payload["status"] = previous_project["status"]

            for spec in effective_agents:
                previous = existing_agents.get(spec["agent_id"])
                if previous is not None and (
                    _agent_static_fields(previous) == _agent_static_fields(spec)
                ):
                    # Idempotent bootstrap must never downgrade a specialist.
                    spec["status"] = previous["status"]

        return super().bootstrap(
            company=company_payload,
            project=project_payload,
            agents=effective_agents,
            actor=actor,
            reason=reason,
        )

    def validate(self, company_id: str) -> dict[str, Any]:
        """Verify database integrity, audit protections and the F01 contract."""
        company_id = _core._id(company_id, "company_id")
        try:
            result = super().validate(company_id)
        except (
            _core.RegistryError,
            sqlite3.Error,
            ValueError,
            TypeError,
            KeyError,
        ) as exc:
            return {
                "valid": False,
                "company_id": company_id,
                "project_count": 0,
                "agent_count": 0,
                "audit_events_checked": 0,
                "issues": [f"Registry validation could not complete: {exc}"],
                "contract_validation": {
                    "schema_version_valid": False,
                    "append_only_triggers_valid": False,
                    "configuration_scopes_valid": False,
                    "configuration_values_valid": False,
                    "audit_chain_valid": False,
                    "canonical_catalog_valid": (
                        False if company_id == CANONICAL_COMPANY_ID else None
                    ),
                },
            }

        issues = list(result.get("issues", []))
        contracts: dict[str, Any] = {
            "schema_version_valid": False,
            "append_only_triggers_valid": False,
            "configuration_scopes_valid": True,
            "configuration_values_valid": True,
            "audit_chain_valid": False,
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
                    issues.append(
                        "Registry schema migration/version checksum is invalid."
                    )

                trigger_rows = db.execute(
                    "SELECT name,sql FROM sqlite_master WHERE type='trigger'"
                ).fetchall()
                trigger_sql = {
                    row["name"]: _normalise_trigger_sql(row["sql"])
                    for row in trigger_rows
                }
                expected_triggers = {
                    "audit_events_no_update": (
                        "create trigger audit_events_no_update before update "
                        "on audit_events begin select raise(abort,"
                        "'audit_events is append-only'); end"
                    ),
                    "audit_events_no_delete": (
                        "create trigger audit_events_no_delete before delete "
                        "on audit_events begin select raise(abort,"
                        "'audit_events is append-only'); end"
                    ),
                }
                contracts["append_only_triggers_valid"] = (
                    set(trigger_sql) == set(expected_triggers)
                    and all(
                        trigger_sql.get(name) == expected_sql
                        for name, expected_sql in expected_triggers.items()
                    )
                )
                if not contracts["append_only_triggers_valid"]:
                    issues.append(
                        "Registry audit append-only protection is missing, altered, "
                        "or contains an unapproved trigger."
                    )

                scope_tables = {
                    "company": ("companies", "company_id"),
                    "project": ("projects", "project_id"),
                    "agent": ("agents", "agent_id"),
                }
                configurations = db.execute(
                    """SELECT scope_type,scope_id,config_key,value_json
                    FROM configurations ORDER BY scope_type,scope_id,config_key"""
                ).fetchall()
                for row in configurations:
                    scope = scope_tables.get(row["scope_type"])
                    if scope is None:
                        contracts["configuration_scopes_valid"] = False
                        issues.append(
                            "Registry contains a configuration with an invalid scope type."
                        )
                        continue

                    table, key = scope
                    owner_column = (
                        "company_id"
                        if row["scope_type"] != "company"
                        else key
                    )
                    scope_row = db.execute(
                        f"SELECT {owner_column} AS owner_id "
                        f"FROM {table} WHERE {key}=?",
                        (row["scope_id"],),
                    ).fetchone()
                    if scope_row is None:
                        contracts["configuration_scopes_valid"] = False
                        issues.append(
                            f"Registry configuration references a missing "
                            f"{row['scope_type']} scope."
                        )

                    try:
                        config_key = _core._text(
                            row["config_key"], "config_key", 160
                        )
                        value = json.loads(row["value_json"])
                        _core._json(value)
                    except (
                        _core.RegistryError,
                        TypeError,
                        ValueError,
                        json.JSONDecodeError,
                    ):
                        contracts["configuration_values_valid"] = False
                        issues.append(
                            "Registry contains a configuration with invalid key or JSON data."
                        )
                        continue

                    finding = _find_secret(value, "configuration")
                    if finding or (
                        _is_secret_field(config_key)
                        and not _is_safe_secret_reference(config_key, value)
                    ):
                        contracts["configuration_values_valid"] = False
                        issues.append(
                            "Registry configuration contains credential-like data "
                            "that must be migrated to a secret manager."
                        )

                audit_rows = db.execute(
                    "SELECT payload_json FROM audit_events ORDER BY event_id"
                ).fetchall()
                for event_row in audit_rows:
                    try:
                        payload = json.loads(event_row["payload_json"])
                    except (TypeError, ValueError, json.JSONDecodeError):
                        # The base audit verifier reports malformed event payloads.
                        continue

                    finding = _find_secret(payload, "audit_payload")
                    if isinstance(payload, Mapping):
                        config_key = payload.get("config_key")
                        config_value = payload.get("value")
                        if (
                            _is_secret_field(config_key)
                            and not _is_safe_secret_reference(
                                config_key, config_value
                            )
                        ):
                            finding = finding or "audit_payload.configuration"

                    if finding:
                        contracts["configuration_values_valid"] = False
                        issues.append(
                            "Registry audit history contains credential-like data "
                            "that must be migrated to a secret manager."
                        )

        except sqlite3.Error as exc:
            contracts["schema_version_valid"] = False
            contracts["append_only_triggers_valid"] = False
            contracts["configuration_scopes_valid"] = False
            contracts["configuration_values_valid"] = False
            issues.append(f"Registry contract inspection failed: {exc}")

        try:
            chain = self.verify_audit_chain()
            contracts["audit_chain_valid"] = bool(chain.get("valid"))
            if not contracts["audit_chain_valid"]:
                issues.append(
                    "Registry audit hash chain is invalid: "
                    f"{chain.get('reason', 'unknown verification failure')}"
                )
        except (sqlite3.Error, ValueError, TypeError, KeyError) as exc:
            issues.append(
                f"Registry audit hash chain verification failed: {exc}"
            )

        if company_id == CANONICAL_COMPANY_ID:
            canonical_issues: list[str] = []
            try:
                company = self.get_company(company_id)
                if (
                    company["slug"] != CANONICAL_COMPANY_SLUG
                    or company["name"] != CANONICAL_COMPANY_NAME
                ):
                    canonical_issues.append(
                        "Canonical company identity fields do not match the F01 contract."
                    )

                projects = {
                    item["project_id"]: item
                    for item in self.list_projects(company_id)
                }
                project = projects.get(CANONICAL_PROJECT_ID)
                if project is None:
                    canonical_issues.append(
                        "Canonical AI-Dev-Company project record is missing."
                    )
                else:
                    expected_project = {
                        "company_id": CANONICAL_COMPANY_ID,
                        "slug": CANONICAL_COMPANY_SLUG,
                        "name": CANONICAL_PROJECT_NAME,
                        "description": "",
                        "repository_url": CANONICAL_REPOSITORY_URL,
                        "default_branch": CANONICAL_DEFAULT_BRANCH,
                    }
                    for key, expected_value in expected_project.items():
                        if project.get(key) != expected_value:
                            canonical_issues.append(
                                f"Canonical project field '{key}' "
                                "does not match the F01 contract."
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
                        "Registered specialist identities do not exactly match "
                        "the canonical eight-agent catalog."
                    )

                for agent_id, expected_fields in expected_specs.items():
                    actual = actual_agents.get(agent_id)
                    if actual is None:
                        continue

                    actual_fields = _expected_agent_fields(actual)
                    if actual_fields != expected_fields:
                        changed = [
                            key for key in expected_fields
                            if actual_fields.get(key) != expected_fields[key]
                        ]
                        canonical_issues.append(
                            f"Specialist '{agent_id}' fields differ from the "
                            f"canonical catalog: {', '.join(changed)}."
                        )

            except (
                _core.RegistryError,
                sqlite3.Error,
                ValueError,
                TypeError,
                KeyError,
            ) as exc:
                canonical_issues.append(
                    f"Canonical company contract could not be validated: {exc}"
                )

            contracts["canonical_catalog_valid"] = not canonical_issues
            issues.extend(canonical_issues)

        issues = list(dict.fromkeys(issues))
        return {
            **result,
            "valid": not issues,
            "issues": issues,
            "contract_validation": contracts,
        }
