"""Run repository intelligence as: python -m company_os.context"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .dependency_mapper import map_python_dependencies
from .repository_scanner import ScanPolicy, scan_repository


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a content-free repository intelligence index.")
    parser.add_argument("--root", default=".", help="Repository root (default: current directory).")
    parser.add_argument(
        "--output", default=".ai-dev-company/repository-index.json",
        help="Output JSON path (default: .ai-dev-company/repository-index.json).",
    )
    parser.add_argument("--max-file-bytes", type=int, default=2 * 1024 * 1024)
    args = parser.parse_args(argv)

    try:
        root = Path(args.root).expanduser().resolve()
        policy = ScanPolicy(max_file_bytes=args.max_file_bytes)
        snapshot = scan_repository(root, policy)
        dependencies = map_python_dependencies(root, snapshot)
        report = {
            "schema_version": "1.0",
            "repository": snapshot.to_dict(),
            "python_dependencies": dependencies.to_dict(),
        }
        output = Path(args.output).expanduser()
        if not output.is_absolute():
            output = root / output
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"repository-index: error: {exc}", file=sys.stderr)
        return 2

    print(
        f"Repository index created: {output}\n"
        f"Files indexed: {len(snapshot.files)} | skipped: {snapshot.skipped_files} | "
        f"Python files analyzed: {dependencies.files_analyzed} | "
        f"dependency edges: {len(dependencies.edges)} | parse issues: {len(dependencies.parse_issues)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
