"""Command-line entry point for repository intelligence.

Examples:
    python -m company_os.context

    python -m company_os.context \
        --root . \
        --changed company_os/registry/core.py

    python -m company_os.context \
        --root . \
        --changed company_os/registry/core.py \
        --changed company_os/registry/catalog.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

from pathlib import Path
from typing import Any

from .dependency_mapper import map_python_dependencies
from .impact_analyzer import analyze_change_impact
from .repository_scanner import ScanPolicy, scan_repository

INDEX_SCHEMA_VERSION = "1.1"


def _atomic_write_json(output: Path, payload: dict[str, Any]) -> None:
    """Write JSON atomically so readers never see a partial index."""

    serialized = json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
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
                # Do not hide the original write/replace failure.
                pass


def _resolve_output_path(root: Path, requested_output: str) -> Path:
    """Resolve output paths relative to the selected repository root."""

    output = Path(requested_output).expanduser()

    if not output.is_absolute():
        output = root / output

    return output.resolve()


def _validate_changed_files(
    snapshot,
    impact_report,
) -> None:
    """Reject paths that the current repository snapshot did not index.

    Impact analysis must not silently report zero affected files for a typo,
    missing file, excluded path, binary file, or unsupported file.
    """

    indexed_paths = {
        record.path
        for record in snapshot.files
    }

    requested_paths = set(impact_report.changed_files)
    unavailable_paths = sorted(requested_paths - indexed_paths)

    if unavailable_paths:
        paths_text = ", ".join(unavailable_paths)

        raise ValueError(
            "Changed file(s) are not present in the repository snapshot: "
            f"{paths_text}. The file may be missing, excluded by the scan "
            "policy, unsupported, binary, non-UTF-8, or larger than the "
            "configured file-size limit. Impact analysis requires each "
            "changed file to be present in the current repository snapshot."
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a deterministic repository intelligence index and "
            "optionally calculate local Python dependency impact."
        )
    )

    parser.add_argument(
        "--root",
        default=".",
        help="Repository root directory (default: current directory).",
    )

    parser.add_argument(
        "--output",
        default=".ai-dev-company/repository-index.json",
        help=(
            "JSON output path. Relative paths are resolved from --root. "
            "Default: .ai-dev-company/repository-index.json."
        ),
    )

    parser.add_argument(
        "--max-file-bytes",
        type=int,
        default=2 * 1024 * 1024,
        help="Maximum source file size to inspect (default: 2 MiB).",
    )

    parser.add_argument(
        "--changed",
        action="append",
        default=[],
        metavar="REPO_PATH",
        help=(
            "Repository-relative changed file to analyze. Repeat this option "
            "for multiple files. Every supplied path must be present in the "
            "current repository snapshot. Impact analysis follows local "
            "Python import edges only."
        ),
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Build the repository index and return a process exit code."""

    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        root = Path(args.root).expanduser().resolve()

        if not root.exists() or not root.is_dir():
            raise ValueError(
                f"Repository root is not an existing directory: {root}"
            )

        policy = ScanPolicy(
            max_file_bytes=args.max_file_bytes,
        )

        snapshot = scan_repository(root, policy)
        dependencies = map_python_dependencies(root, snapshot)

        impact_report = None

        if args.changed:
            impact_report = analyze_change_impact(
                dependencies,
                args.changed,
            )

            _validate_changed_files(
                snapshot,
                impact_report,
            )

        output = _resolve_output_path(
            root,
            args.output,
        )

        # Never overwrite a source file that was indexed.
        if output.is_relative_to(root):
            output_relative = output.relative_to(root).as_posix()

            indexed_paths = {
                record.path
                for record in snapshot.files
            }

            if output_relative in indexed_paths:
                raise ValueError(
                    "Refusing to overwrite an indexed source file: "
                    f"{output_relative}"
                )

        payload = {
            "schema_version": INDEX_SCHEMA_VERSION,
            "snapshot_sha256": snapshot.snapshot_sha256,
            "repository": snapshot.to_dict(),
            "python_dependencies": dependencies.to_dict(),
            "change_impact": (
                impact_report.to_dict()
                if impact_report is not None
                else None
            ),
        }

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        _atomic_write_json(
            output,
            payload,
        )

    except (OSError, ValueError) as exc:
        print(
            f"repository-index: error: {exc}",
            file=sys.stderr,
        )
        return 2

    print(
        f"Repository index created: {output}\n"
        f"Files indexed: {len(snapshot.files)} | "
        f"skipped: {snapshot.skipped_files} | "
        f"Python files analyzed: {dependencies.files_analyzed} | "
        f"dependency edges: {len(dependencies.edges)} | "
        f"parse issues: {len(dependencies.parse_issues)}"
    )

    if impact_report is None:
        print("Change impact: not requested")
    else:
        print(
            f"Change impact: {impact_report.impacted_count} impacted files | "
            f"{impact_report.direct_count} direct | "
            f"{impact_report.transitive_count} transitive"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
