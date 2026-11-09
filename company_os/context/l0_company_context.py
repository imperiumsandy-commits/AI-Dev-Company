"""Compile a validated L0 company identity and operating-policy context.

L0 contains only company-wide identity and operating rules. It deliberately
excludes project requirements, specialist architecture, source files, task
history, and deep audit evidence, which belong to later context levels.

The compiler reads an already-created FoundationService. It does not write
memory, register agents, call model providers, or execute tools.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Mapping

from ai_dev_company.agent_loader import list_agents as list_agent_specifications
from company_os.foundation import (
    COMPANY_ID,
    PROJECT_ID,
    FoundationError,
    FoundationService,
)
from company_os.registry.catalog import DEFAULT_AGENTS
from company_os.registry.core import RegistryError

from .company_policies import (
    COMPANY_OPERATING_POLICIES,
    POLICY_CATALOG_SOURCE,
    POLICY_CATALOG_VERSION,
    validate_policy_catalog,
)


L0_CONTEXT_SCHEMA = "company-context.l0.v1"
DEFAULT_MAX_CONTEXT_TOKENS = 6000
DEFAULT_RESERVED_OUTPUT_TOKENS = 1200
_TOKEN_ESTIMATION_METHOD = "ceil(UTF-8 serialized bytes / 3); heuristic, not provider-tokenizer exact"


class ContextCompilationError(ValueError):
    """The canonical foundation cannot safely produce a company context."""


class ContextBudgetExceeded(ContextCompilationError):
    """The complete required L0 packet does not fit the available context."""

    def __init__(self, estimated_tokens: int, available_tokens: int) -> None:
        self.estimated_tokens = estimated_tokens
        self.available_tokens = available_tokens
        super().__init__(
            "Complete L0 context exceeds the available token budget: "
            f"estimated={estimated_tokens}, available={available_tokens}. "
            "Required identity and operating policies were not truncated."
        )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _estimate_tokens(value: Any) -> int:
    byte_count = len(_canonical_json(value).encode("utf-8"))
    return max(1, math.ceil(byte_count / 3))


def _positive_integer(value: int, field: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContextCompilationError(f"{field} must be an integer.")
    minimum = 0 if allow_zero else 1
    if value < minimum:
        raise ContextCompilationError(
            f"{field} must be greater than or equal to {minimum}."
        )
    return value


def _public_company(company: Mapping[str, Any]) -> dict[str, Any]:
    """Return only company identity fields; owner contact details are excluded."""
    return {
        "company_id": company["company_id"],
        "slug": company["slug"],
        "name": company["name"],
        "status": company["status"],
    }


def _public_project(project: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "project_id": project["project_id"],
        "company_id": project["company_id"],
        "slug": project["slug"],
        "name": project["name"],
        "repository_url": project["repository_url"],
        "default_branch": project["default_branch"],
        "status": project["status"],
    }


def _public_agent(agent: Mapping[str, Any]) -> dict[str, Any]:
    capabilities = agent.get("capabilities", [])
    if not isinstance(capabilities, list):
        raise ContextCompilationError(
            f"Specialist '{agent.get('agent_id', '<unknown>')}' has invalid capabilities."
        )

    return {
        "agent_id": agent["agent_id"],
        "slug": agent["slug"],
        "display_name": agent["display_name"],
        "domain": agent["domain"],
        "definition_path": agent["definition_path"],
        "role_version": agent["role_version"],
        "capabilities": sorted(set(str(item) for item in capabilities)),
        "status": agent["status"],
    }


def _agent_specification_status(root: Path) -> list[dict[str, Any]]:
    loaded = list_agent_specifications(root)
    expected_by_slug = {item["slug"]: item for item in DEFAULT_AGENTS}
    by_slug = {item["agent_id"]: item for item in loaded}

    if set(by_slug) != set(expected_by_slug):
        raise ContextCompilationError(
            "Agent specification loader does not cover the canonical eight specialists."
        )

    result: list[dict[str, Any]] = []
    for spec in DEFAULT_AGENTS:
        agent_id = spec["agent_id"]
        slug = spec["slug"]
        item = by_slug[slug]
        folder = item.get("folder")
        relative_folder = None
        if folder:
            try:
                relative_folder = Path(folder).resolve().relative_to(root).as_posix()
            except ValueError:
                raise ContextCompilationError(
                    f"Agent specification folder for '{agent_id}' is outside the repository."
                )

        result.append({
            "agent_id": agent_id,
            "slug": slug,
            "folder": relative_folder,
            "status": item["status"],
            "loaded_specifications": sorted(item["loaded_specifications"]),
            "missing_required_specifications": sorted(
                item["missing_required_specifications"]
            ),
        })

    return result


def _validate_registered_roster(agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    expected_ids = [item["agent_id"] for item in DEFAULT_AGENTS]
    actual_ids = [item.get("agent_id") for item in agents]

    if len(actual_ids) != 8 or len(set(actual_ids)) != 8:
        raise ContextCompilationError(
            "L0 requires exactly eight unique registered specialist records."
        )
    if set(actual_ids) != set(expected_ids):
        missing = sorted(set(expected_ids) - set(actual_ids))
        unexpected = sorted(set(actual_ids) - set(expected_ids))
        raise ContextCompilationError(
            "Registered specialist roster differs from the canonical catalog; "
            f"missing={missing}, unexpected={unexpected}."
        )

    by_id = {item["agent_id"]: item for item in agents}
    return [_public_agent(by_id[agent_id]) for agent_id in expected_ids]


def compile_l0_company_context(
    foundation: FoundationService,
    *,
    max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
    reserved_output_tokens: int = DEFAULT_RESERVED_OUTPUT_TOKENS,
) -> dict[str, Any]:
    """Compile deterministic, integrity-gated L0 context from live foundation state.

    The ``foundation`` object must already exist. Its ``validate`` operation
    must succeed before any identity or policy content is returned.
    """
    maximum = _positive_integer(max_context_tokens, "max_context_tokens")
    reserve = _positive_integer(
        reserved_output_tokens,
        "reserved_output_tokens",
        allow_zero=True,
    )
    available = maximum - reserve
    if available <= 0:
        raise ContextCompilationError(
            "reserved_output_tokens must be smaller than max_context_tokens."
        )

    validate_policy_catalog()

    try:
        foundation_report = foundation.validate()
    except (FoundationError, RegistryError, sqlite3.Error, OSError, ValueError) as exc:
        raise ContextCompilationError(
            f"Foundation validation could not complete: {exc}"
        ) from exc

    if not isinstance(foundation_report, Mapping) or not foundation_report.get("valid"):
        issues = (
            foundation_report.get("issues", [])
            if isinstance(foundation_report, Mapping)
            else ["Foundation validation returned an invalid report."]
        )
        raise ContextCompilationError(
            "L0 compilation refused because the company foundation is invalid: "
            + "; ".join(str(item) for item in issues)
        )

    try:
        company = foundation.registry.get_company(COMPANY_ID)
        projects = foundation.registry.list_projects(COMPANY_ID)
        registered_agents = foundation.registry.list_agents(COMPANY_ID)
        public_company = _public_company(company)
    except (RegistryError, sqlite3.Error, KeyError, TypeError, ValueError) as exc:
        raise ContextCompilationError(
            f"Canonical registry records could not be read or validated: {exc}"
        ) from exc

    primary_projects = [
        item for item in projects if item.get("project_id") == PROJECT_ID
    ]
    if len(primary_projects) != 1:
        raise ContextCompilationError(
            "L0 requires exactly one canonical AI-Dev-Company project record."
        )

    try:
        public_project = _public_project(primary_projects[0])
        agents = _validate_registered_roster(registered_agents)
        specification_status = _agent_specification_status(foundation.root)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ContextCompilationError(
            f"L0 specialist or project contract could not be compiled: {exc}"
        ) from exc

    policy_payload = [
        policy.to_dict()
        for policy in sorted(
            COMPANY_OPERATING_POLICIES,
            key=lambda item: item.priority,
        )
    ]

    policy_digest = hashlib.sha256(
        _canonical_json(policy_payload).encode("utf-8")
    ).hexdigest()

    storage_contract = str(foundation_report.get("storage_contract", ""))
    if not storage_contract:
        raise ContextCompilationError(
            "Foundation validation did not disclose its storage contract."
        )

    core_packet: dict[str, Any] = {
        "schema": L0_CONTEXT_SCHEMA,
        "level": "L0",
        "purpose": "Company identity and non-negotiable operating policies",
        "scope": {
            "included": [
                "canonical company identity",
                "canonical primary project identity",
                "eight-specialist roster and lifecycle state",
                "specialist specification readiness summary",
                "company-wide operating policies and their enforcement limits",
                "current storage boundary",
            ],
            "excluded": [
                "project-specific requirements and backlog (L1)",
                "specialist architecture and detailed tool contracts (L2)",
                "task-specific source files and dependency context (L3)",
                "deep security findings and test evidence (L4)",
            ],
        },
        "company": public_company,
        "primary_project": public_project,
        "specialists": {
            "registered_count": len(agents),
            "registered_agents": agents,
            "specification_readiness": specification_status,
            "loader_contract": (
                "Read-only specification discovery; it does not call a model "
                "provider or execute specialist work."
            ),
            "activation_rule": (
                "A registered specialist is not necessarily specification-ready, "
                "runtime-ready, evaluated, or active. Do not infer model invocation "
                "or execution from a registry record."
            ),
        },
        "operating_policies": {
            "catalog_version": POLICY_CATALOG_VERSION,
            "catalog_source": POLICY_CATALOG_SOURCE,
            "count": len(policy_payload),
            "sha256": policy_digest,
            "policies": policy_payload,
        },
        "storage_boundary": {
            "contract": storage_contract,
            "registry_storage": "SQLite",
            "memory_storage": "SQLite",
            "cloud_shared_memory": False,
            "distributed_atomic_transaction": False,
        },
        "verification": {
            "foundation_valid": True,
            "registry_valid": bool(
                foundation_report.get("registry_validation", {}).get("valid", False)
            ),
            "memory_bindings_valid": bool(
                foundation_report.get("memory", {}).get("bindings_valid", False)
            ),
            "registered_specialists": len(agents),
            "policy_catalog_validated": True,
        },
        "sources": [
            {
                "source_id": "registry.company",
                "authority": "canonical company identity",
                "storage": "company registry database",
            },
            {
                "source_id": "registry.primary_project",
                "authority": "canonical project identity and repository binding",
                "storage": "company registry database",
            },
            {
                "source_id": "registry.specialists",
                "authority": "canonical eight-specialist roster and lifecycle state",
                "storage": "company registry database",
            },
            {
                "source_id": "company.operating_policies",
                "authority": "version-controlled company policy catalog",
                "path": POLICY_CATALOG_SOURCE,
                "version": POLICY_CATALOG_VERSION,
            },
            {
                "source_id": "agent.specification_readiness",
                "authority": "read-only specification file discovery",
                "storage": "repository agents/ directory",
            },
        ],
    }

    budget = {
        "max_context_tokens": maximum,
        "reserved_output_tokens": reserve,
        "available_context_tokens": available,
        "estimated_context_tokens": 0,
        "estimation_method": _TOKEN_ESTIMATION_METHOD,
        "truncated": False,
        "omitted_sections": [],
    }
    packet = {
        **core_packet,
        "budget": budget,
        # A fixed-length placeholder ensures the digest field is counted.
        "packet_sha256": "0" * 64,
    }

    stable_estimate = False
    for _ in range(8):
        estimated = _estimate_tokens(packet)
        if budget["estimated_context_tokens"] == estimated:
            stable_estimate = True
            break
        budget["estimated_context_tokens"] = estimated

    final_estimate = _estimate_tokens(packet)
    if not stable_estimate or final_estimate != budget["estimated_context_tokens"]:
        raise ContextCompilationError(
            "L0 token-budget estimation did not converge deterministically."
        )

    if final_estimate > available:
        raise ContextBudgetExceeded(final_estimate, available)

    unsigned_packet = dict(packet)
    unsigned_packet.pop("packet_sha256")
    packet["packet_sha256"] = hashlib.sha256(
        _canonical_json(unsigned_packet).encode("utf-8")
    ).hexdigest()
    return packet


def write_context_packet(
    packet: Mapping[str, Any],
    destination: str | os.PathLike[str],
) -> Path:
    """Atomically write a compiled packet without modifying project memory."""
    if packet.get("schema") != L0_CONTEXT_SCHEMA:
        raise ContextCompilationError(
            "Refusing to write a packet with an unsupported L0 schema."
        )
    supplied_digest = packet.get("packet_sha256")
    if not isinstance(supplied_digest, str) or len(supplied_digest) != 64:
        raise ContextCompilationError(
            "Refusing to write an L0 packet without its integrity digest."
        )

    unsigned_packet = dict(packet)
    unsigned_packet.pop("packet_sha256", None)
    expected_digest = hashlib.sha256(
        _canonical_json(unsigned_packet).encode("utf-8")
    ).hexdigest()
    if supplied_digest != expected_digest:
        raise ContextCompilationError(
            "Refusing to write an L0 packet whose integrity digest does not match."
        )

    target = Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(
                json.dumps(
                    packet,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                    allow_nan=False,
                ) + "\n"
            )
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary_path, target)
        temporary_path = None
        return target
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
