"""Loads existing specialist specifications and combines them with live memory."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .memory_store import AGENT_IDS, MemoryStore


AGENT_DIRECTORIES = {
    "business-analyst-pm": ("business-analyst-pm", "business-analyst", "business-analyst-project-manager"),
    "system-architect": ("system-architect",),
    "backend-developer": ("backend-developer",),
    "frontend-developer": ("frontend-developer",),
    "database-administrator": ("database-administrator", "database-admin", "database-developer"),
    "cybersecurity-engineer": ("cybersecurity-engineer",),
    "qa-bug-hunter": ("qa-bug-hunter", "qa-engineer", "quality-assurance-engineer", "qa-tester"),
    "devops-engineer": ("devops-engineer",),
}

SPEC_FILES = (
    "ROLE.md",
    "ARCHITECTURE.md",
    "WORKFLOW.md",
    "TOOL_POLICY.md",
    "OUTPUT_CONTRACT.md",
    "MEMORY_POLICY.md",
    "QUALITY_GATES.md",
    "FAILURE_RECOVERY.md",
)


def locate_agent(root: Path, agent_id: str) -> Path | None:
    if agent_id not in AGENT_IDS:
        raise ValueError(f"Unknown agent ID: {agent_id}")
    for folder in AGENT_DIRECTORIES[agent_id]:
        candidate = root / "agents" / folder
        if candidate.is_dir() and any((candidate / name).is_file() for name in SPEC_FILES):
            return candidate
    return None


def load_agent(root: Path, agent_id: str) -> dict[str, Any]:
    folder = locate_agent(root, agent_id)
    specifications: dict[str, str] = {}
    if folder is not None:
        for filename in SPEC_FILES:
            path = folder / filename
            if path.is_file():
                content = path.read_text(encoding="utf-8-sig", errors="replace")
                specifications[filename] = content[:50000]

    required = ("ROLE.md", "ARCHITECTURE.md", "WORKFLOW.md")
    missing = [name for name in required if name not in specifications]

    return {
        "agent_id": agent_id,
        "folder": str(folder) if folder else None,
        "status": "ready_to_load" if folder and "ROLE.md" in specifications else "missing_specification",
        "loaded_specifications": specifications,
        "missing_required_specifications": missing,
        "note": (
            "Specifications were read from disk. This loader does not call an AI provider."
            if specifications else
            "No matching agent specification folder was found; no instructions were invented."
        ),
    }


def list_agents(root: Path) -> list[dict[str, Any]]:
    result = []
    for agent_id in AGENT_IDS:
        spec = load_agent(root, agent_id)
        result.append({
            "agent_id": agent_id,
            "folder": spec["folder"],
            "status": spec["status"],
            "loaded_specifications": list(spec["loaded_specifications"].keys()),
            "missing_required_specifications": spec["missing_required_specifications"],
        })
    return result


def build_agent_context(
    root: Path, agent_id: str, task: str = ""
) -> dict[str, Any]:
    """Prepare live context; a later provider adapter can send it to an LLM."""
    store = MemoryStore(root)
    specification = load_agent(root, agent_id)
    project_memories = store.list_memories(scope="project", limit=20)
    agent_memories = store.list_memories(scope=agent_id, limit=20)
    assigned_tasks = store.list_tasks(agent_id=agent_id, limit=50)

    store.record_event(
        actor="runtime",
        event_type="agent_context_built",
        entity_type="agent",
        entity_id=agent_id,
        payload={"task": task[:1000], "specification_status": specification["status"]},
    )

    return {
        "agent_id": agent_id,
        "task_request": task,
        "instructions": [
            "Use this specialist's own loaded specifications; do not blend its role into a generic agent.",
            "Treat external AI output as a draft and require relevant verification evidence.",
            "Use project memory for continuity and preserve new decisions, task changes and checkpoints.",
            "If required specifications or tools are missing, report the gap rather than pretending they exist.",
            "This context builder does not execute an AI model call or perform code changes by itself.",
        ],
        "specification": specification,
        "project_summary": store.summary(),
        "project_memory": project_memories,
        "agent_memory": agent_memories,
        "assigned_tasks": assigned_tasks,
    }
