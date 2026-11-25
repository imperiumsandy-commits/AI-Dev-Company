"""CLI for validating and exporting the L1 project context.

Usage:
    python -m company_os.context.l1_cli --root .
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from company_os.foundation import FoundationError, FoundationService

from .context_layers import (
    DEFAULT_L1_MAX_CONTEXT_TOKENS,
    DEFAULT_L1_RESERVED_OUTPUT_TOKENS,
    L1ContextCompilationError,
    compile_l1_project_context,
    write_l1_context_packet,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compile a validated L1 project context from company identity, "
            "project memory, requirements, decisions and task history."
        )
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root containing .ai-dev-company state.",
    )
    parser.add_argument(
        "--output",
        default=".ai-dev-company/context/l1-project-context.json",
        help="Output path; relative paths are resolved from --root.",
    )
    parser.add_argument(
        "--max-context-tokens",
        type=int,
        default=DEFAULT_L1_MAX_CONTEXT_TOKENS,
        help=(
            "Maximum total context budget, including its L0 parent. "
            f"Default: {DEFAULT_L1_MAX_CONTEXT_TOKENS}."
        ),
    )
    parser.add_argument(
        "--reserved-output-tokens",
        type=int,
        default=DEFAULT_L1_RESERVED_OUTPUT_TOKENS,
        help=(
            "Tokens reserved for the model response. "
            f"Default: {DEFAULT_L1_RESERVED_OUTPUT_TOKENS}."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.root).expanduser().resolve()

    if not root.is_dir():
        print(
            f"l1-context: repository root is not a directory: {root}",
            file=sys.stderr,
        )
        return 2

    try:
        foundation = FoundationService(root)

        packet = compile_l1_project_context(
            foundation,
            max_context_tokens=args.max_context_tokens,
            reserved_output_tokens=args.reserved_output_tokens,
        )

        requested_output = Path(args.output).expanduser()
        output = (
            requested_output
            if requested_output.is_absolute()
            else root / requested_output
        ).resolve()

        try:
            output.relative_to(root)
        except ValueError as exc:
            raise L1ContextCompilationError(
                "Output must remain inside the selected repository root."
            ) from exc

        written = write_l1_context_packet(packet, output)

    except (
        L1ContextCompilationError,
        FoundationError,
        OSError,
        ValueError,
    ) as exc:
        print(f"l1-context: error: {exc}", file=sys.stderr)
        return 2

    project = packet["project"]
    knowledge = project["knowledge"]
    tasks = project["task_backlog"]

    print(
        "L1 project context compiled and integrity-digested.\n"
        f"Output: {written}\n"
        f"Project memories: {knowledge['record_count']} | "
        f"Tasks: {tasks['record_count']} | "
        f"Open tasks: {tasks['open_task_count']}\n"
        f"Estimated tokens: "
        f"{packet['budget']['estimated_context_tokens']} / "
        f"{packet['budget']['available_context_tokens']} available\n"
        f"Packet SHA-256: {packet['packet_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
