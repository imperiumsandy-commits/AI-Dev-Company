"""Load and validate the eight canonical AI-Dev-Company specialist specs.

The loader reads declarative specifications only. It does not invoke an
LLM, grant tools, authorize privileged actions, or execute specialist work.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .memory_store import AGENT_IDS, MemoryStore


AGENT_DIRECTORIES = {
    "business-analyst-pm": ("business-analyst-pm",),
    "system-architect": ("system-architect",),
    "backend-developer": ("backend-developer",),
    "frontend-developer": ("frontend-developer",),
    "database-administrator": ("database-administrator",),
    "cybersecurity-engineer": ("cybersecurity-engineer",),
    "qa-bug-hunter": ("qa-bug-hunter",),
    "devops-engineer": ("devops-engineer",),
}

SPEC_FILES = ("agent.yaml",)
REQUIRED_SPEC_FILES = ("agent.yaml",)
MAX_SPEC_FILE_BYTES = 50_000
SPEC_SCHEMA_VERSION = "company-agent-spec.v1"

_REQUIRED_FORBIDDEN_ACTIONS = frozenset({
    "secret_access",
    "unrestricted_shell",
    "production_deploy_without_approval",
    "approve_own_verification",
})


class AgentSpecificationError(ValueError):
    """A specialist specification violates the canonical contract."""


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentSpecificationError(
            f"Specialist manifest field '{field}' must be non-empty text."
        )
    return value.strip()


def _string_list(
    value: Any,
    field: str,
    *,
    minimum: int = 1,
) -> list[str]:
    if not isinstance(value, list) or len(value) < minimum:
        raise AgentSpecificationError(
            f"Specialist manifest field '{field}' must contain "
            f"at least {minimum} entries."
        )

    result: list[str] = []
    for index, item in enumerate(value):
        result.append(_string(item, f"{field}[{index}]"))

    if len(result) != len(set(result)):
        raise AgentSpecificationError(
            f"Specialist manifest field '{field}' contains duplicates."
        )

    return result


def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AgentSpecificationError(
            f"Specialist manifest section '{field}' must be an object."
        )
    return value


def _records(
    value: Any,
    field: str,
    required_keys: tuple[str, ...],
    *,
    minimum: int,
) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or len(value) < minimum:
        raise AgentSpecificationError(
            f"Specialist manifest section '{field}' must contain "
            f"at least {minimum} records."
        )

    result: list[Mapping[str, Any]] = []
    for index, raw in enumerate(value):
        item = _object(raw, f"{field}[{index}]")
        for key in required_keys:
            _string(item.get(key), f"{field}[{index}].{key}")
        result.append(item)

    return result


def validate_agent_manifest(
    manifest: Mapping[str, Any],
    canonical_agent: Mapping[str, Any],
) -> None:
    """Validate identity and complete specialist operating contracts."""
    if manifest.get("schema_version") != SPEC_SCHEMA_VERSION:
        raise AgentSpecificationError(
            f"Unsupported specialist specification schema: "
            f"{manifest.get('schema_version')!r}."
        )

    identity_fields = (
        ("registry_agent_id", "agent_id"),
        ("slug", "slug"),
        ("display_name", "display_name"),
        ("domain", "domain"),
    )

    for manifest_field, canonical_field in identity_fields:
        supplied = _string(manifest.get(manifest_field), manifest_field)
        expected = _string(
            canonical_agent.get(canonical_field),
            f"canonical.{canonical_field}",
        )
        if supplied != expected:
            raise AgentSpecificationError(
                f"Specialist identity mismatch for '{manifest_field}': "
                f"expected {expected!r}, received {supplied!r}."
            )

    role_version = _string(manifest.get("role_version"), "role_version")
    if role_version != str(canonical_agent.get("role_version", "1.0.0")):
        raise AgentSpecificationError(
            "Specialist role_version does not match the canonical registry."
        )

    supplied_capabilities = _string_list(
        manifest.get("capabilities"),
        "capabilities",
    )
    expected_capabilities = list(canonical_agent.get("capabilities", []))
    if supplied_capabilities != expected_capabilities:
        raise AgentSpecificationError(
            "Specialist capabilities do not exactly match the canonical "
            "registry catalog."
        )

    _string(manifest.get("mission"), "mission")
    _string(manifest.get("specialty"), "specialty")

    ownership = _object(manifest.get("ownership"), "ownership")
    _string_list(ownership.get("owns"), "ownership.owns", minimum=3)
    _string_list(
        ownership.get("not_owned"),
        "ownership.not_owned",
        minimum=2,
    )
    _string_list(
        ownership.get("decision_authority"),
        "ownership.decision_authority",
        minimum=2,
    )

    inputs = _object(manifest.get("inputs"), "inputs")
    _string_list(inputs.get("required"), "inputs.required", minimum=2)
    _string_list(inputs.get("optional"), "inputs.optional", minimum=1)

    outputs = _object(manifest.get("outputs"), "outputs")
    _string_list(outputs.get("artifacts"), "outputs.artifacts", minimum=2)
    _string_list(outputs.get("contracts"), "outputs.contracts", minimum=2)
    _string_list(
        outputs.get("evidence_requirements"),
        "outputs.evidence_requirements",
        minimum=2,
    )

    architecture = _object(
        manifest.get("architecture"),
        "architecture",
    )
    _records(
        architecture.get("components"),
        "architecture.components",
        ("name", "responsibility"),
        minimum=3,
    )
    _string_list(
        architecture.get("data_objects"),
        "architecture.data_objects",
        minimum=2,
    )
    _string_list(
        architecture.get("invariants"),
        "architecture.invariants",
        minimum=4,
    )

    workflow = _object(manifest.get("workflow"), "workflow")
    _records(
        workflow.get("stages"),
        "workflow.stages",
        ("name", "action", "exit_evidence"),
        minimum=4,
    )
    _string_list(
        workflow.get("stop_conditions"),
        "workflow.stop_conditions",
        minimum=3,
    )

    tool_policy = _object(
        manifest.get("tool_policy"),
        "tool_policy",
    )
    allowed = _string_list(
        tool_policy.get("allowed_capabilities"),
        "tool_policy.allowed_capabilities",
    )
    forbidden = set(_string_list(
        tool_policy.get("forbidden_actions"),
        "tool_policy.forbidden_actions",
    ))
    if not _REQUIRED_FORBIDDEN_ACTIONS.issubset(forbidden):
        missing = sorted(_REQUIRED_FORBIDDEN_ACTIONS - forbidden)
        raise AgentSpecificationError(
            "Specialist tool policy is missing mandatory restrictions: "
            + ", ".join(missing)
        )

    _string_list(
        tool_policy.get("privileged_actions_require_approval"),
        "tool_policy.privileged_actions_require_approval",
        minimum=2,
    )
    if tool_policy.get("execution_authority") != "declarative_only":
        raise AgentSpecificationError(
            "Specialist specification cannot grant execution authority."
        )

    _string_list(
        manifest.get("quality_gates"),
        "quality_gates",
        minimum=6,
    )

    memory_policy = _object(
        manifest.get("memory_policy"),
        "memory_policy",
    )
    _string(memory_policy.get("authoritative_source"), "memory_policy.authoritative_source")
    _string_list(
        memory_policy.get("persist"),
        "memory_policy.persist",
        minimum=3,
    )
    _string_list(
        memory_policy.get("never_persist"),
        "memory_policy.never_persist",
        minimum=3,
    )
    _string_list(
        memory_policy.get("resume_steps"),
        "memory_policy.resume_steps",
        minimum=3,
    )

    _records(
        manifest.get("failure_modes"),
        "failure_modes",
        ("condition", "response", "escalation"),
        minimum=3,
    )
    _records(
        manifest.get("evaluation_scenarios"),
        "evaluation_scenarios",
        ("scenario_id", "scenario", "expected_behavior"),
        minimum=4,
    )
    _records(
        manifest.get("handoffs"),
        "handoffs",
        ("recipient", "trigger", "required_payload"),
        minimum=2,
    )

    readiness = _object(manifest.get("readiness"), "readiness")
    if readiness.get("specification_state") != "specification_ready":
        raise AgentSpecificationError(
            "Specialist manifest must explicitly identify its specification state."
        )
    if readiness.get("runtime_state") != "not_implemented":
        raise AgentSpecificationError(
            "A specification must not claim an unimplemented runtime."
        )
    if readiness.get("evaluated") is not False:
        raise AgentSpecificationError(
            "A specialist cannot claim completed evaluation from its manifest."
        )
    if readiness.get("active") is not False:
        raise AgentSpecificationError(
            "A specialist manifest cannot activate itself."
        )


def locate_agent(root: Path, agent_id: str) -> Path | None:
    if agent_id not in AGENT_IDS:
        raise ValueError(f"Unknown agent ID: {agent_id}")

    resolved_root = Path(root).expanduser().resolve()

    for folder in AGENT_DIRECTORIES[agent_id]:
        candidate = (resolved_root / "agents" / folder).resolve()

        try:
            candidate.relative_to(resolved_root)
        except ValueError:
            raise AgentSpecificationError(
                f"Specialist directory for '{agent_id}' escapes the repository root."
            )

        if candidate.is_dir() and (candidate / "agent.yaml").is_file():
            return candidate

    return None


def load_agent(root: Path, agent_id: str) -> dict[str, Any]:
    """Load one specialist's canonical manifest without executing it."""
    from company_os.registry.catalog import DEFAULT_AGENTS

    folder = locate_agent(root, agent_id)
    if folder is None:
        return {
            "agent_id": agent_id,
            "folder": None,
            "status": "missing_specification",
            "loaded_specifications": {},
            "missing_required_specifications": list(REQUIRED_SPEC_FILES),
            "manifest": None,
            "manifest_sha256": None,
            "validation_errors": [],
            "note": "No canonical agent.yaml was found; no role was invented.",
        }

    path = folder / "agent.yaml"
    try:
        resolved_file = path.resolve()
        resolved_file.relative_to(folder.resolve())

        file_size = resolved_file.stat().st_size
        if file_size > MAX_SPEC_FILE_BYTES:
            raise AgentSpecificationError(
                f"Specialist manifest exceeds the {MAX_SPEC_FILE_BYTES}-byte limit."
            )

        raw_bytes = resolved_file.read_bytes()
        content = raw_bytes.decode("utf-8-sig")
        manifest = json.loads(content)

        if not isinstance(manifest, dict):
            raise AgentSpecificationError(
                "Specialist agent.yaml must contain one top-level object."
            )

    except (OSError, UnicodeDecodeError, json.JSONDecodeError, AgentSpecificationError) as exc:
        return {
            "agent_id": agent_id,
            "folder": str(folder),
            "status": "invalid_specification",
            "loaded_specifications": {},
            "missing_required_specifications": [],
            "manifest": None,
            "manifest_sha256": None,
            "validation_errors": [str(exc)],
            "note": "The specialist manifest could not be safely loaded.",
        }

    canonical = next(
        (item for item in DEFAULT_AGENTS if item["slug"] == agent_id),
        None,
    )
    if canonical is None:
        raise ValueError(f"No canonical registry definition for agent: {agent_id}")

    try:
        validate_agent_manifest(manifest, canonical)
    except AgentSpecificationError as exc:
        return {
            "agent_id": agent_id,
            "folder": str(folder),
            "status": "invalid_specification",
            "loaded_specifications": {"agent.yaml": content},
            "missing_required_specifications": [],
            "manifest": manifest,
            "manifest_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "validation_errors": [str(exc)],
            "note": "The manifest failed canonical specialist validation.",
        }

    digest = hashlib.sha256(raw_bytes).hexdigest()

    return {
        "agent_id": agent_id,
        "folder": str(folder),
        "status": "ready_to_load",
        "loaded_specifications": {"agent.yaml": content},
        "missing_required_specifications": [],
        "manifest": manifest,
        "manifest_sha256": digest,
        "validation_errors": [],
        "note": (
            "The canonical declarative specification was validated. "
            "No AI provider was called and no tools were granted."
        ),
    }


def list_agents(root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for agent_id in AGENT_IDS:
        spec = load_agent(root, agent_id)
        result.append({
            "agent_id": agent_id,
            "folder": spec["folder"],
            "status": spec["status"],
            "loaded_specifications": list(spec["loaded_specifications"]),
            "missing_required_specifications": spec[
                "missing_required_specifications"
            ],
            "manifest_sha256": spec["manifest_sha256"],
            "validation_errors": spec["validation_errors"],
        })
    return result


def build_agent_context(
    root: Path,
    agent_id: str,
    task: str = "",
) -> dict[str, Any]:
    """Build an informational context snapshot, not an executing agent."""
    store = MemoryStore(root)
    specification = load_agent(root, agent_id)

    if specification["status"] != "ready_to_load":
        raise AgentSpecificationError(
            f"Agent '{agent_id}' is not specification-ready: "
            f"{specification['status']}."
        )

    project_memories = store.list_memories(scope="project", limit=20)
    agent_memories = store.list_memories(scope=agent_id, limit=20)
    assigned_tasks = store.list_tasks(agent_id=agent_id, limit=50)

    store.record_event(
        actor="runtime",
        event_type="agent_context_built",
        entity_type="agent",
        entity_id=agent_id,
        payload={
            "task": task[:1000],
            "specification_status": specification["status"],
            "manifest_sha256": specification["manifest_sha256"],
        },
    )

    return {
        "agent_id": agent_id,
        "task_request": task,
        "instructions": [
            "Use only this specialist's own validated domain specification.",
            "Do not assume declared tools have been authorized or granted.",
            "Treat external AI output as a draft requiring evidence.",
            "Do not cross specialist ownership boundaries.",
            "If required permissions, inputs or verification are missing, stop and report the gap.",
            "This context builder does not invoke a model or execute work.",
        ],
        "specification": specification,
        "project_summary": store.summary(),
        "project_memory": project_memories,
        "agent_memory": agent_memories,
        "assigned_tasks": assigned_tasks,
    }
