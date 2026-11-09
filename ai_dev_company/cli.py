"""CLI for AI-Dev-Company memory and integrated company foundation."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from .agent_loader import build_agent_context, list_agents
from .foundation import FoundationService
from .memory_store import AGENT_IDS, TASK_STATUSES, MemoryStore


def emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def git_state(root: Path) -> dict[str, Any]:
    def run(args: list[str]) -> str:
        result = subprocess.run(
            args,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
        return (
            result.stdout.strip()
            if result.returncode == 0
            else f"Unavailable: {result.stderr.strip()}"
        )

    return {
        "branch": run(["git", "branch", "--show-current"]),
        "status": run(["git", "status", "--short", "--branch"]),
    }


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-dev",
        description="AI-Dev-Company persistent memory and foundation CLI.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser(
        "init",
        help="Initialize persistent project memory and foundation migrations.",
    )
    commands.add_parser(
        "status",
        help="Show project memory, foundation health and specialist-spec status.",
    )
    commands.add_parser(
        "agents",
        help="Show which of the eight agent specifications can be loaded.",
    )
    commands.add_parser(
        "handoff",
        help="Export current memory and foundation status for a new session.",
    )

    context = commands.add_parser(
        "agent-context",
        help="Load one specialist's specifications and project memory.",
    )
    context.add_argument("--agent", required=True, choices=AGENT_IDS)
    context.add_argument("--task", default="")

    remember = commands.add_parser(
        "remember",
        help="Persist project or specialist memory.",
    )
    remember.add_argument(
        "--scope",
        required=True,
        choices=("project",) + AGENT_IDS,
    )
    remember.add_argument(
        "--kind",
        required=True,
        choices=(
            "decision",
            "lesson",
            "note",
            "requirement",
            "future_work",
            "risk",
            "policy",
        ),
    )
    remember.add_argument("--title", required=True)
    remember.add_argument("--content", required=True)

    memories = commands.add_parser(
        "memories",
        help="Read saved memories.",
    )
    memories.add_argument("--scope", choices=("project",) + AGENT_IDS)
    memories.add_argument("--limit", type=int, default=20)

    add_task = commands.add_parser(
        "task-add",
        help="Save a task in the durable backlog.",
    )
    add_task.add_argument("--title", required=True)
    add_task.add_argument("--description", default="")
    add_task.add_argument("--agent", choices=AGENT_IDS)
    add_task.add_argument(
        "--priority",
        choices=("critical", "high", "normal", "low"),
        default="normal",
    )
    add_task.add_argument("--acceptance", nargs="*", default=[])
    add_task.add_argument("--depends-on", nargs="*", default=[])
    add_task.add_argument("--next-action", default="")

    tasks = commands.add_parser(
        "task-list",
        help="List saved tasks.",
    )
    tasks.add_argument("--agent", choices=AGENT_IDS)
    tasks.add_argument("--status", choices=TASK_STATUSES)
    tasks.add_argument("--limit", type=int, default=100)

    update = commands.add_parser(
        "task-update",
        help="Update task status or next action.",
    )
    update.add_argument("--id", required=True)
    update.add_argument("--status", choices=TASK_STATUSES)
    update.add_argument("--next-action")
    update.add_argument("--note")

    checkpoint = commands.add_parser(
        "checkpoint",
        help="Save a durable project checkpoint.",
    )
    checkpoint.add_argument("--name", required=True)
    checkpoint.add_argument("--note", default="")

    foundation = commands.add_parser(
        "foundation",
        help="Manage the integrated Company OS foundation.",
    )
    foundation_commands = foundation.add_subparsers(
        dest="foundation_action",
        required=True,
    )

    foundation_init = foundation_commands.add_parser(
        "init",
        help="Bootstrap the company, project, eight agents and memory bindings.",
    )
    foundation_init.add_argument("--root")
    foundation_init.add_argument("--owner-name", required=True)
    foundation_init.add_argument("--owner-email", required=True)
    foundation_init.add_argument(
        "--actor",
        default="owner:imperiumsandy-commits",
    )
    foundation_init.add_argument(
        "--reason",
        default="Integrated Company Foundation bootstrap",
    )

    foundation_status = foundation_commands.add_parser(
        "status",
        help="Validate registry, memory and specialist identity bindings.",
    )
    foundation_status.add_argument("--root")

    foundation_backup = foundation_commands.add_parser(
        "backup",
        help="Create a verified runtime-state backup.",
    )
    foundation_backup.add_argument("--root")
    foundation_backup.add_argument("--destination", required=True)

    foundation_restore = foundation_commands.add_parser(
        "restore",
        help="Restore verified runtime state into an empty project state directory.",
    )
    foundation_restore.add_argument("--backup", required=True)
    foundation_restore.add_argument("--target-root", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "foundation":
            if args.foundation_action == "restore":
                result = FoundationService.restore_backup(
                    backup_path=args.backup,
                    target_root=args.target_root,
                )
                emit(result)
                return 0

            if args.root:
                root = Path(args.root).expanduser().resolve()
            else:
                root = MemoryStore().root

            foundation = FoundationService(root)

            if args.foundation_action == "init":
                result = foundation.bootstrap(
                    owner_name=args.owner_name,
                    owner_email=args.owner_email,
                    actor=args.actor,
                    reason=args.reason,
                )
                emit(result)
                return 0

            if args.foundation_action == "status":
                result = foundation.validate()
                emit(result)
                return 0 if result["valid"] else 2

            if args.foundation_action == "backup":
                result = foundation.create_backup(args.destination)
                emit(result)
                return 0

            parser.error("Unsupported foundation command")

        # The supported CLI always runs the memory integration migration.
        # Existing standalone MemoryStore APIs remain available to Python callers.
        root_discovery = MemoryStore()
        foundation = FoundationService(root_discovery.root)
        store = foundation.memory
        root = store.root

        if args.command == "init":
            emit({
                "initialized": True,
                "project_root": str(root),
                "memory_database": str(store.db_path),
                "seed_memories": len(
                    store.list_memories(scope="project", limit=200)
                ),
                "foundation": foundation.validate(),
                "note": (
                    "Local SQLite memory persists between program runs. "
                    "Use 'ai-dev foundation init' to register the company "
                    "and bind all eight specialists."
                ),
            })

        elif args.command == "status":
            emit({
                "project": store.summary(),
                "foundation": foundation.validate(),
                "agents": list_agents(root),
                "git": git_state(root),
            })

        elif args.command == "agents":
            emit(list_agents(root))

        elif args.command == "agent-context":
            emit(build_agent_context(root, args.agent, args.task))

        elif args.command == "remember":
            emit(store.add_memory(
                scope=args.scope,
                kind=args.kind,
                title=args.title,
                content=args.content,
            ))

        elif args.command == "memories":
            emit(store.list_memories(
                scope=args.scope,
                limit=args.limit,
            ))

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
                agent_id=args.agent,
                status=args.status,
                limit=args.limit,
            ))

        elif args.command == "task-update":
            if (
                args.status is None
                and args.next_action is None
                and args.note is None
            ):
                parser.error(
                    "task-update needs at least one of "
                    "--status, --next-action or --note"
                )

            emit(store.update_task(
                task_id=args.id,
                status=args.status,
                next_action=args.next_action,
                note=args.note,
            ))

        elif args.command == "checkpoint":
            emit(store.save_checkpoint(args.name, args.note))

        elif args.command == "handoff":
            emit({
                "handoff_version": 2,
                "project_root": str(root),
                "memory_database": str(store.db_path),
                "git": git_state(root),
                "foundation": foundation.validate(),
                "project_memory": store.summary(),
                "agents": list_agents(root),
                "resume_instruction": (
                    "Continue from saved tasks, decisions, events and checkpoints. "
                    "Verify the actual Git branch and source files before coding. "
                    "Treat registry registration as identity only; do not claim an "
                    "agent is operational unless its specification, runtime and tests "
                    "prove that capability. The GitHub repository remains the source "
                    "of truth for source code."
                ),
            })

        return 0

    except (ValueError, RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
