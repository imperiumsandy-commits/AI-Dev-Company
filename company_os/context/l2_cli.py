"""CLI for compiling a validated L2 specialist context.

General specialist queue:
    python -m company_os.context.l2_cli --root . --agent backend-developer

Task-specific context:
    python -m company_os.context.l2_cli --root . --agent backend-developer --task-id <existing-task-id>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ai_dev_company.memory_store import AGENT_IDS
from company_os.foundation import FoundationError, FoundationService

from .specialist_context import (
    DEFAULT_L2_MAX_CONTEXT_TOKENS,
    DEFAULT_L2_RESERVED_OUTPUT_TOKENS,
    L2ContextCompilationError,
    compile_l2_specialist_context,
    write_l2_context_packet,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compile a validated L2 context for one canonical specialist, "
            "including its own domain contract and task ownership."
        )
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root containing .ai-dev-company state.",
    )
    parser.add_argument(
        "--agent",
        required=True,
        choices=AGENT_IDS,
        help="Canonical specialist slug.",
    )
    parser.add_argument(
        "--task-id",
        default=None,
        help=(
            "Optional task ID. It must be unassigned or owned by this specialist."
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Output JSON path. Defaults to .ai-dev-company/context/"
            "l2-<specialist>.json."
        ),
    )
    parser.add_argument(
        "--max-context-tokens",
        type=int,
        default=DEFAULT_L2_MAX_CONTEXT_TOKENS,
    )
    parser.add_argument(
        "--reserved-output-tokens",
        type=int,
        default=DEFAULT_L2_RESERVED_OUTPUT_TOKENS,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.root).expanduser().resolve()

    if not root.is_dir():
        print(
            f"l2-context: repository root is not a directory: {root}",
            file=sys.stderr,
        )
        return 2

    if args.output is None:
        output = (
            root
            / ".ai-dev-company"
            / "context"
            / f"l2-{args.agent}.json"
        )
    else:
        requested = Path(args.output).expanduser()
        output = requested if requested.is_absolute() else root / requested

    output = output.resolve()

    try:
        output.relative_to(root)
    except ValueError:
        print(
            "l2-context: output must remain inside the repository root.",
            file=sys.stderr,
        )
        return 2

    try:
        foundation = FoundationService(root)

        packet = compile_l2_specialist_context(
            foundation,
            args.agent,
            task_id=args.task_id,
            max_context_tokens=args.max_context_tokens,
            reserved_output_tokens=args.reserved_output_tokens,
        )

        written = write_l2_context_packet(packet, output)

    except (
        L2ContextCompilationError,
        FoundationError,
        OSError,
        ValueError,
    ) as exc:
        print(f"l2-context: error: {exc}", file=sys.stderr)
        return 2

    specialist = packet["specialist"]
    scope = specialist["task_scope"]

    print(
        "L2 specialist context compiled and integrity-digested.\n"
        f"Specialist: {specialist['identity']['display_name']} "
        f"({specialist['identity']['slug']})\n"
        f"Task mode: {scope['mode']} | "
        f"Tasks in scope: {scope['owned_task_count']}\n"
        f"Output: {written}\n"
        f"Estimated tokens: "
        f"{packet['budget']['estimated_context_tokens']} / "
        f"{packet['budget']['available_context_tokens']} available\n"
        f"Packet SHA-256: {packet['packet_sha256']}\n"
        "Execution: not invoked | Tool access: not granted"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
