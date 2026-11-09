"""Command-line entry point for repository intelligence."""

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
from .git_snapshot import (
    GitRevisionSnapshotError,
    load_git_revision_dependencies,
)
from .impact_analyzer import analyze_change_impact
from .incremental_scanner import scan_repository_incremental
from .repository_scanner import ScanPolicy, scan_repository

INDEX_SCHEMA_VERSION = "1.4"


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
            "dependency graph, and current/historical impact reports."
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

    parser.add_argument(
        "--incremental",
        action="store_true",
        help=(
            "Use the metadata-backed incremental repository scanner. "
            "Unchanged files may be reused without reading their contents."
        ),
    )

    parser.add_argument(
        "--scan-cache",
        default=None,
        metavar="PATH",
        help=(
            "Optional incremental scan cache path. Relative paths are "
            "resolved from --root. Default: .ai-dev-company/"
            "repository-scan-cache.json."
        ),
    )

    parser.add_argument(
        "--verify-incremental",
        action="store_true",
        help=(
            "Read and hash every eligible file even when cache metadata "
            "matches. Requires --incremental."
        ),
    )

    parser.add_argument(
        "--refresh-scan-cache",
        action="store_true",
        help=(
            "Ignore cached entries, perform a fresh content scan, and "
            "rebuild the incremental cache. Requires --incremental."
        ),
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

        if args.verify_incremental and not args.incremental:
            raise ValueError(
                "--verify-incremental requires --incremental."
            )

        if args.refresh_scan_cache and not args.incremental:
            raise ValueError(
                "--refresh-scan-cache requires --incremental."
            )

        policy = ScanPolicy(
            max_file_bytes=args.max_file_bytes,
        )

        incremental_result = None

        if args.incremental:
            incremental_result = scan_repository_incremental(
                root,
                policy,
                cache_path=args.scan_cache,
                verify_unchanged=args.verify_incremental,
                force_full=args.refresh_scan_cache,
            )

            snapshot = incremental_result.snapshot

            scan_execution = {
                "mode": "incremental",
                **incremental_result.to_dict(),
            }

        else:
            snapshot = scan_repository(root, policy)

            scan_execution = {
                "mode": "full",
                "snapshot_sha256": snapshot.snapshot_sha256,
                "cache_path": None,
                "stats": None,
            }

        dependencies = map_python_dependencies(root, snapshot)

        indexed_paths = {
            record.path
            for record in snapshot.files
        }

        git_report = None

        if args.git_base is not None:
            git_report = detect_git_changes(
                root,
                base_ref=args.git_base,
                head_ref=args.git_head,
            )

        # Current-revision analysis.
        current_impact_paths = list(args.changed)
        skipped_paths: list[dict[str, str]] = []

        if git_report is not None:
            for path in git_report.impact_candidate_paths:
                if path in indexed_paths:
                    current_impact_paths.append(path)
                else:
                    skipped_paths.append({
                        "path": path,
                        "reason": (
                            "The changed path is not in the current repository "
                            "snapshot and cannot enter the static dependency graph."
                        ),
                    })

        current_impact = None

        if current_impact_paths:
            current_impact = analyze_change_impact(
                dependencies,
                current_impact_paths,
            )

            _validate_changed_files(
                snapshot,
                current_impact,
            )

        if current_impact is not None:
            current_status = {
                "status": "computed",
                "reason": None,
            }
        elif git_report is not None and git_report.change_count == 0:
            current_status = {
                "status": "no_changes",
                "reason": "The selected Git comparison contains no changes.",
            }
        elif git_report is not None:
            current_status = {
                "status": "not_computed",
                "reason": (
                    "No current-snapshot paths were eligible for static "
                    "impact analysis."
                ),
            }
        else:
            current_status = {
                "status": "not_requested",
                "reason": None,
            }

        # Historical analysis: deleted and renamed source paths are analysed
        # against the dependency graph reconstructed from the merge-base.
        historical_impact = None

        historical_status = {
            "status": "not_requested",
            "reason": None,
        }

        if git_report is not None:
            removed_paths = git_report.removed_paths

            historical_python_paths = [
                path
                for path in removed_paths
                if path.endswith(".py")
            ]

            non_python_removed_paths = [
                path
                for path in removed_paths
                if not path.endswith(".py")
            ]

            for path in non_python_removed_paths:
                skipped_paths.append({
                    "path": path,
                    "reason": (
                        "Historical dependency impact currently supports "
                        "Python source files only."
                    ),
                })

            if not removed_paths:
                historical_status = {
                    "status": "no_removed_paths",
                    "reason": None,
                }

            elif not historical_python_paths:
                historical_status = {
                    "status": "not_applicable",
                    "reason": (
                        "The comparison contains no deleted or renamed "
                        "Python source files."
                    ),
                }

            else:
                try:
                    historical_snapshot = load_git_revision_dependencies(
                        root,
                        revision=git_report.merge_base,
                        policy=policy,
                    )

                except GitRevisionSnapshotError as exc:
                    historical_status = {
                        "status": "unavailable",
                        "reason": str(exc),
                    }

                    for path in historical_python_paths:
                        skipped_paths.append({
                            "path": path,
                            "reason": (
                                "Historical dependency snapshot could not "
                                f"be reconstructed: {exc}"
                            ),
                        })

                else:
                    historical_indexed_paths = (
                        historical_snapshot.indexed_paths
                    )

                    available_historical_paths = sorted(
                        set(historical_python_paths)
                        & historical_indexed_paths
                    )

                    unavailable_historical_paths = sorted(
                        set(historical_python_paths)
                        - historical_indexed_paths
                    )

                    for path in unavailable_historical_paths:
                        skipped_paths.append({
                            "path": path,
                            "reason": (
                                "The deleted or renamed Python file is not "
                                "indexable in the merge-base snapshot. It may "
                                "be absent, excluded, a symlink, binary, "
                                "non-UTF-8, or oversized."
                            ),
                        })

                    if available_historical_paths:
                        historical_report = analyze_change_impact(
                            historical_snapshot.dependencies,
                            available_historical_paths,
                        )

                        historical_impact = {
                            "purpose": (
                                "Dependents of deleted/renamed files in "
                                "the historical merge-base revision."
                            ),
                            "base_commit": git_report.merge_base,
                            "dependency_snapshot": (
                                historical_snapshot.to_dict()
                            ),
                            "impact_report": historical_report.to_dict(),
                        }

                        historical_status = {
                            "status": (
                                "computed_with_skips"
                                if unavailable_historical_paths
                                else "computed"
                            ),
                            "reason": None,
                        }

                    else:
                        historical_status = {
                            "status": "not_computed",
                            "reason": (
                                "No deleted or renamed Python source file "
                                "could be indexed in the merge-base snapshot."
                            ),
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
            "scan_execution": scan_execution,
            "repository": snapshot.to_dict(),
            "python_dependencies": dependencies.to_dict(),
            "git_changes": (
                git_report.to_dict()
                if git_report is not None
                else None
            ),
            "change_impact": (
                current_impact.to_dict()
                if current_impact is not None
                else None
            ),
            "change_impact_status": current_status,
            "historical_change_impact": historical_impact,
            "historical_change_impact_status": historical_status,
            "change_impact_skipped_paths": sorted(
                skipped_paths,
                key=lambda item: (item["path"], item["reason"]),
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

    if incremental_result is not None:
        stats = incremental_result.stats

        print(
            f"Incremental scan: cache={stats.cache_state} | "
            f"reused={stats.files_reused} | "
            f"read={stats.files_read} | "
            f"bytes_read={stats.bytes_read} | "
            f"verification={stats.verification_mode}"
        )

        if stats.cache_reason:
            print(f"Cache note: {stats.cache_reason}")
    else:
        print("Repository scan: full content scan")

    if git_report is not None:
        print(
            f"Git changes: {git_report.change_count} | "
            f"added: {git_report.status_counts['added']} | "
            f"modified: {git_report.status_counts['modified']} | "
            f"deleted: {git_report.status_counts['deleted']} | "
            f"renamed: {git_report.status_counts['renamed']}"
        )

    if current_impact is not None:
        print(
            f"Current impact: {current_impact.impacted_count} impacted files | "
            f"{current_impact.direct_count} direct | "
            f"{current_impact.transitive_count} transitive"
        )
    else:
        print(f"Current impact: {current_status['status']}")

    if historical_impact is not None:
        historical_report = historical_impact["impact_report"]

        print(
            f"Historical impact: {historical_report['impacted_count']} "
            f"impacted files from base revision"
        )
    else:
        print(
            f"Historical impact: {historical_status['status']}"
        )

    if skipped_paths:
        print(
            f"Git paths not analyzed: {len(skipped_paths)}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
