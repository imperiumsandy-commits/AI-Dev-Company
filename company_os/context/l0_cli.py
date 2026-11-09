"""CLI for validating and exporting the L0 company context packet.

Usage:
    python -m company_os.context.l0_cli --root .
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from company_os.foundation import FoundationError, FoundationService

from .l0_company_context import (
    DEFAULT_MAX_CONTEXT_TOKENS,
    DEFAULT_RESERVED_OUTPUT_TOKENS,
    ContextCompilationError,
    compile_l0_company_context,
    write_context_packet,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compile a validated L0 packet containing AI-Dev-Company identity, "
            "its canonical specialist roster, and company operating policies."
        )
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root containing .ai-dev-company state (default: current directory).",
    )
    parser.add_argument(
        "--output",
        default=".ai-dev-company/context/l0-company-context.json",
        help="Output path; relative paths are resolved from --root.",
    )
    parser.add_argument(
        "--max-context-tokens",
        type=int,
        default=DEFAULT_MAX_CONTEXT_TOKENS,
        help=f"Maximum total context budget (default: {DEFAULT_MAX_CONTEXT_TOKENS}).",
    )
    parser.add_argument(
        "--reserved-output-tokens",
        type=int,
        default=DEFAULT_RESERVED_OUTPUT_TOKENS,
        help=f"Tokens reserved for the model response (default: {DEFAULT_RESERVED_OUTPUT_TOKENS}).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.root).expanduser().resolve()

    if not root.is_dir():
        print(f"l0-context: repository root is not a directory: {root}", file=sys.stderr)
        return 2

    try:
        foundation = FoundationService(root)
        packet = compile_l0_company_context(
            foundation,
            max_context_tokens=args.max_context_tokens,
            reserved_output_tokens=args.reserved_output_tokens,
        )

        requested_output = Path(args.output).expanduser()
        output = requested_output if requested_output.is_absolute() else root / requested_output
        output = output.resolve()
        try:
            output.relative_to(root)
        except ValueError as exc:
            raise ContextCompilationError(
                "Output must remain inside the selected repository root."
            ) from exc

        written = write_context_packet(packet, output)
    except (ContextCompilationError, FoundationError, OSError, ValueError) as exc:
        print(f"l0-context: error: {exc}", file=sys.stderr)
        return 2

    print(
        "L0 company context compiled and integrity-digested.\n"
        f"Output: {written}\n"
        f"Specialists: {packet['specialists']['registered_count']} | "
        f"Policies: {packet['operating_policies']['count']} | "
        f"Estimated tokens: {packet['budget']['estimated_context_tokens']} / "
        f"{packet['budget']['available_context_tokens']} available\n"
        f"Packet SHA-256: {packet['packet_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
