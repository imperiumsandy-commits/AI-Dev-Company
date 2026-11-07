"""Command-line entry point for repository intelligence.

Examples:
    python -m company_os.context

    python -m company_os.context \
        --root . \
        --changed company_os/registry/core.py

    python -m company_os.context \
        --root . \
        --git-base origin/main \
        --git-head HEAD
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
from .git_changes import detect_git_changes
from .impact_analyzer import analyze_change_impact
from .repository_scanner import ScanPolicy, scan_repository

INDEX_SCHEMA_VERSION = "1.2"


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
                pass


def _resolve_output_path(root: Path, requested_output: str) -> Path:
    """Resolve output paths relative to the repository root."""

    output = Path(requested_output).expanduser()

    if not output.is_absolute():
        output = root / output

    return output.resolve()


def _validate_changed_files(snapshot: Any, impact_report: Any) -> None:
    """Reject manually requested changed paths absent from the snapshot."""

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
            f"{paths_text}. A file may be missing, excluded by the scan "
            "policy, unsupported, binary, non-UTF-8, or larger than the "
            "configured file-size limit. Impact analysis requires every "
            "manually supplied changed file to be present in the snapshot."
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a deterministic repository intelligence index, "
            "dependency graph, and optional change-impact report."
        )
    )

    parser.add_argument(
        "--root",
        default=".",
        help="Git repository root (default: current directory).",
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
            "Manually specify a repository-relative changed file. "
            "Repeat this option for multiple files."
        ),
    )

    parser.add_argument(
        "--git-base",
        default=None,
        metavar="GIT_REF",
        help=(
            "Compare committed changes from the merge-base of GIT_REF "
            "and --git-head. Example: origin/main."
        ),
    )

    parser.add_argument(
        "--git-head",
        default="HEAD",
        metavar="GIT_REF",
        help="Target commit or ref for Git comparison (default: HEAD).",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Build repository intelligence and return a process exit code."""

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

        indexed_paths = {
            record.path
            for record in snapshot.files
        }

        git_report = None

        if args.git_base:
            git_report = detect_git_changes(
                root,
                base_ref=args.git_base,
                head_ref=args.git_head,
            )

        # Manually supplied paths are strict: invalid or excluded paths fail.
        impact_paths = list(args.changed)

        # Git changes are broader than the scanner's supported text inventory.
        # Only currently indexed paths are sent to the Python impact analyzer.
        skipped_git_paths: list[dict[str, str]] = []

        if git_report is not None:
            for path in git_report.impact_candidate_paths:
                if path in indexed_paths:
                    impact_paths.append(path)
                else:
                    skipped_git_paths.append({
                        "path": path,
                        "reason": (
                            "The changed path is not in the current repository "
                            "snapshot, so it cannot enter the static "
                            "dependency impact graph."
                        ),
                    })

            # Deleted files and rename sources require the dependency graph
            # from the base commit, not the current repository snapshot.
            for path in git_report.removed_paths:
                skipped_git_paths.append({
                    "path": path,
                    "reason": (
                        "This path was removed or renamed. Historical impact "
                        "requires a dependency graph reconstructed from the "
                        "base commit; the current snapshot cannot provide it."
                    ),
                })

        impact_report = None

        if impact_paths:
            impact_report = analyze_change_impact(
                dependencies,
                impact_paths,
            )

            _validate_changed_files(
                snapshot,
                impact_report,
            )

        if impact_report is not None:
            impact_status = {
                "status": "computed",
                "reason": None,
            }
        elif git_report is not None and git_report.change_count == 0:
            impact_status = {
                "status": "no_changes",
                "reason": "The selected Git comparison contains no changes.",
            }
        elif git_report is not None:
            impact_status = {
                "status": "not_computed",
                "reason": (
                    "No changed current-snapshot paths were eligible for "
                    "static impact analysis. See change_impact_skipped_paths."
                ),
            }
        else:
            impact_status = {
                "status": "not_requested",
                "reason": None,
            }

        output = _resolve_output_path(
            root,
            args.output,
        )

        # Never overwrite a source file included in the repository snapshot.
        if output.is_relative_to(root):
            output_relative = output.relative_to(root).as_posix()

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
            "git_changes": (
                git_report.to_dict()
                if git_report is not None
                else None
            ),
            "change_impact": (
                impact_report.to_dict()
                if impact_report is not None
                else None
            ),
            "change_impact_status": impact_status,
            "change_impact_skipped_paths": skipped_git_paths,
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

    if git_report is not None:
        print(
            f"Git changes: {git_report.change_count} | "
            f"added: {git_report.status_counts['added']} | "
            f"modified: {git_report.status_counts['modified']} | "
            f"deleted: {git_report.status_counts['deleted']} | "
            f"renamed: {git_report.status_counts['renamed']}"
        )

    if impact_report is None:
        print(
            f"Change impact: {impact_status['status']}"
        )
    else:
        print(
            f"Change impact: {impact_report.impacted_count} impacted files | "
            f"{impact_report.direct_count} direct | "
            f"{impact_report.transitive_count} transitive"
        )

    if skipped_git_paths:
        print(
            f"Git paths not analyzed for current-snapshot impact: "
            f"{len(skipped_git_paths)}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
