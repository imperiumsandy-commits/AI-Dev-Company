"""Command-line interface for persistent memory and active agent context."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from .agent_loader import build_agent_context, list_agents
from .memory_store import AGENT_IDS, TASK_STATUSES, MemoryStore


def emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def git_state(root: Path) -> dict[str, Any]:
    def run(args: list[str]) -> str:
        result = subprocess.run(
            args, cwd=str(root), capture_output=True, text=True, check=False
        )
        return result.stdout.strip() if result.returncode == 0 else f"Unavailable: {result.stderr.strip()}"

    return {
        "branch": run(["git", "branch", "--show-current"]),
        "status": run(["git", "status", "--short", "--branch"]),
    }


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-dev",
        description="Active AI-Dev-Company project memory and agent context runtime.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("init", help="Initialize the persistent project memory.")
    commands.add_parser("status", help="Show live project memory and agent-spec status.")
    commands.add_parser("agents", help="Show which of the eight agent specs can be loaded.")
    commands.add_parser("handoff", help="Export current memory for a new ChatGPT session.")

    context = commands.add_parser("agent-context", help="Load one specialist's specs and memory.")
    context.add_argument("--agent", required=True, choices=AGENT_IDS)
    context.add_argument("--task", default="")

    remember = commands.add_parser("remember", help="Persist a project or agent memory.")
    remember.add_argument("--scope", required=True, choices=("project",) + AGENT_IDS)
    remember.add_argument(
        "--kind", required=True,
        choices=("decision", "lesson", "note", "requirement", "future_work", "risk", "policy")
    )
    remember.add_argument("--title", required=True)
    remember.add_argument("--content", required=True)

    memories = commands.add_parser("memories", help="Read saved memories.")
    memories.add_argument("--scope", choices=("project",) + AGENT_IDS)
    memories.add_argument("--limit", type=int, default=20)

    add_task = commands.add_parser("task-add", help="Save a task in the durable backlog.")
    add_task.add_argument("--title", required=True)
    add_task.add_argument("--description", default="")
    add_task.add_argument("--agent", choices=AGENT_IDS)
    add_task.add_argument("--priority", choices=("critical", "high", "normal", "low"), default="normal")
    add_task.add_argument("--acceptance", nargs="*", default=[])
    add_task.add_argument("--depends-on", nargs="*", default=[])
    add_task.add_argument("--next-action", default="")

    tasks = commands.add_parser("task-list", help="List saved tasks.")
    tasks.add_argument("--agent", choices=AGENT_IDS)
    tasks.add_argument("--status", choices=TASK_STATUSES)
    tasks.add_argument("--limit", type=int, default=100)

    update = commands.add_parser("task-update", help="Update task status or next action.")
    update.add_argument("--id", required=True)
    update.add_argument("--status", choices=TASK_STATUSES)
    update.add_argument("--next-action")
    update.add_argument("--note")

    checkpoint = commands.add_parser("checkpoint", help="Save a durable project checkpoint.")
    checkpoint.add_argument("--name", required=True)
    checkpoint.add_argument("--note", default="")

    return parser


def main() -> int:
    parser = make_parser()
    args = parser.parse_args()

    try:
        store = MemoryStore()
        root = store.root

        if args.command == "init":
            emit({
                "initialized": True,
                "project_root": str(root),
                "memory_database": str(store.db_path),
                "seed_memories": len(store.list_memories(scope="project", limit=200)),
                "note": "Memory persists on this computer between program runs.",
            })
        elif args.command == "status":
            emit({
                "project": store.summary(),
                "agents": list_agents(root),
                "git": git_state(root),
            })
        elif args.command == "agents":
            emit(list_agents(root))
        elif args.command == "agent-context":
            emit(build_agent_context(root, args.agent, args.task))
        elif args.command == "remember":
            emit(store.add_memory(
                scope=args.scope, kind=args.kind, title=args.title, content=args.content
            ))
        elif args.command == "memories":
            emit(store.list_memories(scope=args.scope, limit=args.limit))
        elif args.command == "task-add":
            emit(store.add_task(
                title=args.title,
                description=args.description,
                agent_id=args.agent,
                priority=args.priority,
                acceptance_criteria=args.acceptance,
                depends_on=args.depends_on,
                next_action=args.next_action,
            ))
        elif args.command == "task-list":
            emit(store.list_tasks(
                agent_id=args.agent, status=args.status, limit=args.limit
            ))
        elif args.command == "task-update":
            if args.status is None and args.next_action is None and args.note is None:
                parser.error("task-update needs at least one of --status, --next-action or --note")
            emit(store.update_task(
                task_id=args.id,
                status=args.status,
                next_action=args.next_action,
                note=args.note,
            ))
        elif args.command == "checkpoint":
            emit(store.save_checkpoint(args.name, args.note))
        elif args.command == "handoff":
            summary = store.summary()
            emit({
                "handoff_version": 1,
                "project_root": str(root),
                "memory_database": str(store.db_path),
                "git": git_state(root),
                "project_memory": summary,
                "agents": list_agents(root),
                "resume_instruction": (
                    "Continue from saved tasks and events. Verify the actual Git branch and "
                    "files before coding. Do not assume a specification or agent is active "
                    "unless the runtime status and tests prove it."
                ),
            })
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
