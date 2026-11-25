"""Integrity-gated L2 specialist context compilation.

L2 combines:
- The validated L1 project context.
- One canonical registry specialist.
- That specialist's validated, domain-specific manifest.
- Only the task scope belonging to that specialist.

This compiler is read-only. It does not invoke an AI provider, execute a
task, authorize tools, or activate a specialist.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

from ai_dev_company.agent_loader import (
    AgentSpecificationError,
    load_agent,
    validate_agent_manifest,
)
from ai_dev_company.memory_store import AGENT_IDS
from company_os.foundation import FoundationService
from company_os.registry.catalog import DEFAULT_AGENTS

from .context_layers import compile_l1_project_context
from .l0_company_context import ContextCompilationError


L2_CONTEXT_SCHEMA = "company-context.l2.v1"

DEFAULT_L2_MAX_CONTEXT_TOKENS = 48000
DEFAULT_L2_RESERVED_OUTPUT_TOKENS = 12000

TOKEN_ESTIMATION_METHOD = (
    "ceil(UTF-8 canonical JSON bytes / 3); deterministic heuristic, "
    "not an exact provider tokenizer"
)

_SENSITIVE_PATTERNS = (
    re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|"
        r"github_pat_[A-Za-z0-9_]{20,})\b"
    ),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bxai-[A-Za-z0-9_-]{20,}\b", re.IGNORECASE),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b", re.IGNORECASE),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}\b", re.IGNORECASE),
)


class L2ContextCompilationError(ContextCompilationError):
    """The specialist context cannot be safely compiled."""


class L2ContextBudgetExceeded(L2ContextCompilationError):
    """The complete L2 packet exceeds its available context budget."""

    def __init__(
        self,
        estimated_tokens: int,
        available_tokens: int,
    ) -> None:
        self.estimated_tokens = estimated_tokens
        self.available_tokens = available_tokens
        super().__init__(
            "Complete L2 specialist context exceeds its available token budget: "
            f"estimated={estimated_tokens}, available={available_tokens}. "
            "The specialist contract and parent L1 context were not truncated."
        )


class L2SpecialistTaskOwnershipError(L2ContextCompilationError):
    """A task was requested using a specialist that does not own it."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _estimate_tokens(value: Any) -> int:
    encoded = _canonical_json(value).encode("utf-8")
    return max(1, math.ceil(len(encoded) / 3))


def _validate_budget(
    max_context_tokens: int,
    reserved_output_tokens: int,
) -> tuple[int, int, int]:
    for field, value, minimum in (
        ("max_context_tokens", max_context_tokens, 1),
        ("reserved_output_tokens", reserved_output_tokens, 0),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise L2ContextCompilationError(
                f"{field} must be an integer."
            )
        if value < minimum:
            raise L2ContextCompilationError(
                f"{field} must be greater than or equal to {minimum}."
            )

    available = max_context_tokens - reserved_output_tokens
    if available <= 0:
        raise L2ContextCompilationError(
            "reserved_output_tokens must be smaller than max_context_tokens."
        )

    return max_context_tokens, reserved_output_tokens, available


def _assert_no_sensitive_values(
    value: Any,
    reference: str,
) -> None:
    """Reject known secret-like patterns without exposing their values."""
    if isinstance(value, str):
        for pattern in _SENSITIVE_PATTERNS:
            if pattern.search(value):
                raise L2ContextCompilationError(
                    "L2 compilation refused because a credential-like value "
                    f"was found in {reference}. Remove it before compilation."
                )
        return

    if isinstance(value, Mapping):
        for key, child in value.items():
            _assert_no_sensitive_values(
                child,
                f"{reference}.{key}",
            )
        return

    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_no_sensitive_values(
                child,
                f"{reference}[{index}]",
            )


def _finalise_packet(
    core_packet: Mapping[str, Any],
    *,
    max_context_tokens: int,
    reserved_output_tokens: int,
) -> dict[str, Any]:
    maximum, reserve, available = _validate_budget(
        max_context_tokens,
        reserved_output_tokens,
    )

    budget: dict[str, Any] = {
        "max_context_tokens": maximum,
        "reserved_output_tokens": reserve,
        "available_context_tokens": available,
        "estimated_context_tokens": 0,
        "estimation_method": TOKEN_ESTIMATION_METHOD,
        "truncated": False,
        "omitted_sections": [],
    }

    packet: dict[str, Any] = {
        **dict(core_packet),
        "budget": budget,
        "packet_sha256": "0" * 64,
    }

    converged = False
    for _ in range(8):
        estimated = _estimate_tokens(packet)
        if estimated == budget["estimated_context_tokens"]:
            converged = True
            break
        budget["estimated_context_tokens"] = estimated

    final_estimate = _estimate_tokens(packet)
    if (
        not converged
        or final_estimate != budget["estimated_context_tokens"]
    ):
        raise L2ContextCompilationError(
            "L2 token-budget estimation did not converge deterministically."
        )

    if final_estimate > available:
        raise L2ContextBudgetExceeded(final_estimate, available)

    unsigned_packet = dict(packet)
    unsigned_packet.pop("packet_sha256")

    packet["packet_sha256"] = hashlib.sha256(
        _canonical_json(unsigned_packet).encode("utf-8")
    ).hexdigest()

    return packet


def _canonical_specialist(agent_id: str) -> dict[str, Any]:
    if agent_id not in AGENT_IDS:
        raise L2ContextCompilationError(
            f"Unknown canonical specialist ID: {agent_id}."
        )

    canonical = next(
        (item for item in DEFAULT_AGENTS if item["slug"] == agent_id),
        None,
    )

    if canonical is None:
        raise L2ContextCompilationError(
            f"Specialist '{agent_id}' is not in the canonical registry catalog."
        )

    return canonical


def _resolve_task_scope(
    tasks: list[dict[str, Any]],
    agent_id: str,
    task_id: str | None,
) -> dict[str, Any]:
    """Resolve specialist-only queue or one task and its direct dependencies."""
    task_by_id = {
        item["task_id"]: item
        for item in tasks
    }

    if task_id is None:
        owned_tasks = [
            item
            for item in tasks
            if item.get("agent_id") == agent_id
        ]

        return {
            "mode": "specialist_queue",
            "selected_task": None,
            "direct_dependencies": [],
            "owned_task_count": len(owned_tasks),
            "owned_tasks": owned_tasks,
        }

    selected = task_by_id.get(task_id)
    if selected is None:
        raise L2ContextCompilationError(
            f"Task '{task_id}' does not exist in the canonical L1 backlog."
        )

    assigned_agent = selected.get("agent_id")
    if assigned_agent not in (None, agent_id):
        raise L2SpecialistTaskOwnershipError(
            f"Task '{task_id}' belongs to '{assigned_agent}', not "
            f"'{agent_id}'. L2 compilation refused to cross specialist ownership."
        )

    dependency_ids = selected.get("depends_on", [])
    if not isinstance(dependency_ids, list):
        raise L2ContextCompilationError(
            f"Task '{task_id}' has an invalid dependency list."
        )

    missing_dependencies = sorted(
        dependency
        for dependency in dependency_ids
        if dependency not in task_by_id
    )
    if missing_dependencies:
        raise L2ContextCompilationError(
            f"Task '{task_id}' references missing dependencies: "
            + ", ".join(missing_dependencies)
        )

    return {
        "mode": "single_task",
        "selected_task": selected,
        "direct_dependencies": [
            task_by_id[dependency]
            for dependency in dependency_ids
        ],
        "owned_task_count": 1,
        "owned_tasks": [selected],
    }


def compile_l2_specialist_context(
    foundation: FoundationService,
    agent_id: str,
    *,
    task_id: str | None = None,
    max_context_tokens: int = DEFAULT_L2_MAX_CONTEXT_TOKENS,
    reserved_output_tokens: int = DEFAULT_L2_RESERVED_OUTPUT_TOKENS,
) -> dict[str, Any]:
    """Compile one specialist context over a validated, complete L1 parent."""
    maximum, reserve, _ = _validate_budget(
        max_context_tokens,
        reserved_output_tokens,
    )

    canonical = _canonical_specialist(agent_id)

    try:
        parent = compile_l1_project_context(
            foundation,
            max_context_tokens=maximum,
            reserved_output_tokens=reserve,
        )
    except ContextCompilationError:
        raise
    except (OSError, ValueError) as exc:
        raise L2ContextCompilationError(
            f"Required L1 project context could not be compiled: {exc}"
        ) from exc

    specification = load_agent(foundation.root, agent_id)
    if specification["status"] != "ready_to_load":
        errors = specification.get("validation_errors", [])
        detail = "; ".join(errors) if errors else specification["status"]
        raise L2ContextCompilationError(
            f"Specialist '{agent_id}' is not specification-ready: {detail}"
        )

    manifest = specification.get("manifest")
    if not isinstance(manifest, Mapping):
        raise L2ContextCompilationError(
            f"Specialist '{agent_id}' has no validated machine-readable manifest."
        )

    try:
        validate_agent_manifest(manifest, canonical)
    except AgentSpecificationError as exc:
        raise L2ContextCompilationError(
            f"Specialist '{agent_id}' failed canonical contract validation: {exc}"
        ) from exc

    _assert_no_sensitive_values(
        manifest,
        f"agent_manifest:{agent_id}",
    )

    registered_agents = (
        parent["parent_context"]["specialists"]["registered_agents"]
    )
    registry_matches = [
        item
        for item in registered_agents
        if item["slug"] == agent_id
    ]

    if len(registry_matches) != 1:
        raise L2ContextCompilationError(
            f"Specialist '{agent_id}' is not uniquely registered in L0."
        )

    registry_identity = registry_matches[0]

    if (
        registry_identity["agent_id"] != manifest["registry_agent_id"]
        or registry_identity["domain"] != manifest["domain"]
        or registry_identity["capabilities"] != sorted(
            manifest["capabilities"]
        )
    ):
        raise L2ContextCompilationError(
            f"Specialist '{agent_id}' manifest does not match live "
            "canonical registry identity."
        )

    task_records = parent["project"]["task_backlog"]["tasks"]
    task_scope = _resolve_task_scope(
        task_records,
        agent_id,
        task_id,
    )

    manifest_path = f"agents/{agent_id}/agent.yaml"

    core_packet = {
        "schema": L2_CONTEXT_SCHEMA,
        "level": "L2",
        "purpose": (
            "Domain-owned specialist reasoning, architecture, contracts, "
            "workflow, evaluation and safe handoffs."
        ),
        "parent_context": parent,
        "specialist": {
            "identity": {
                "registry_agent_id": registry_identity["agent_id"],
                "slug": registry_identity["slug"],
                "display_name": registry_identity["display_name"],
                "domain": registry_identity["domain"],
                "role_version": registry_identity["role_version"],
                "registry_status": registry_identity["status"],
            },
            "specification": manifest,
            "specification_source": {
                "path": manifest_path,
                "format": (
                    "JSON document valid within the YAML 1.2 JSON subset"
                ),
                "sha256": specification["manifest_sha256"],
                "schema_version": manifest["schema_version"],
            },
            "task_scope": task_scope,
        },
        "execution_boundary": {
            "specialist_registered": True,
            "specification_validated": True,
            "runtime_implemented": False,
            "domain_evaluation_completed": False,
            "agent_active": False,
            "model_provider_called": False,
            "task_executed": False,
            "tool_access_granted": False,
            "declared_capabilities_are_authorization": False,
            "authorization_note": (
                "The manifest declares candidate capabilities only. "
                "The future shared runtime must enforce project scope, "
                "tool allowlists, owner approvals and least privilege."
            ),
        },
        "handoff_contract": {
            "source_specialist": agent_id,
            "handoffs": manifest["handoffs"],
            "independent_verification_required": True,
            "specialist_may_approve_own_verification": False,
        },
        "provenance": {
            "parent_l1_packet_sha256": parent["packet_sha256"],
            "specialist_manifest_sha256": specification["manifest_sha256"],
            "registry_agent_id": registry_identity["agent_id"],
            "project_id": parent["project"]["identity"]["project_id"],
        },
        "compiler_contract": {
            "memory_mutated": False,
            "registry_mutated": False,
            "model_provider_called": False,
            "task_executed": False,
            "tool_access_granted": False,
            "token_estimation": TOKEN_ESTIMATION_METHOD,
        },
    }

    return _finalise_packet(
        core_packet,
        max_context_tokens=maximum,
        reserved_output_tokens=reserve,
    )


def write_l2_context_packet(
    packet: Mapping[str, Any],
    destination: str | os.PathLike[str],
) -> Path:
    """Verify the L2 digest and atomically write a complete UTF-8 JSON packet."""
    if packet.get("schema") != L2_CONTEXT_SCHEMA:
        raise L2ContextCompilationError(
            "Refusing to write a packet with an unsupported L2 schema."
        )

    supplied_digest = packet.get("packet_sha256")
    if (
        not isinstance(supplied_digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", supplied_digest)
    ):
        raise L2ContextCompilationError(
            "Refusing to write an L2 packet without a valid SHA-256 digest."
        )

    unsigned_packet = dict(packet)
    unsigned_packet.pop("packet_sha256", None)

    expected_digest = hashlib.sha256(
        _canonical_json(unsigned_packet).encode("utf-8")
    ).hexdigest()

    if supplied_digest != expected_digest:
        raise L2ContextCompilationError(
            "Refusing to write an L2 packet whose digest does not match."
        )

    output = Path(destination).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    serialized = json.dumps(
        dict(packet),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\n"

    temporary_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary_path, output)
        temporary_path = None

    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    return output
