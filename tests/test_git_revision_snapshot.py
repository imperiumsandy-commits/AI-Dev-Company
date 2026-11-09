from __future__ import annotations

import shutil
import subprocess

from pathlib import Path

import pytest

from company_os.context.git_snapshot import (
    GitRevisionSnapshotError,
    load_git_revision_dependencies,
)


pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="Git executable is required for these integration tests.",
)


def run_git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise AssertionError(
            f"Git test command failed: {arguments!r}\n{result.stderr}"
        )

    return result.stdout.strip()


def initialize_repository(root: Path) -> None:
    run_git(root, "init", "--quiet")
    run_git(root, "config", "user.name", "Company OS Tests")
    run_git(root, "config", "user.email", "tests@example.invalid")


def write(root: Path, relative_path: str, content: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def commit_all(root: Path, message: str) -> str:
    run_git(root, "add", "-A")
    run_git(root, "commit", "--quiet", "-m", message)
    return run_git(root, "rev-parse", "HEAD")


def test_loads_python_dependencies_from_historical_commit(
    tmp_path: Path,
) -> None:
    initialize_repository(tmp_path)

    write(tmp_path, "pkg/__init__.py", "")
    write(tmp_path, "pkg/core.py", "VALUE = 1\n")
    write(tmp_path, "consumer.py", "import pkg.core\n")
    write(
        tmp_path,
        ".venv/hidden.py",
        "SHOULD_NOT_BE_INDEXED = True\n",
    )

    commit = commit_all(tmp_path, "base snapshot")

    historical = load_git_revision_dependencies(
        tmp_path,
        revision=commit,
    )

    assert historical.commit == commit

    assert historical.indexed_paths == frozenset({
        "pkg/__init__.py",
        "pkg/core.py",
        "consumer.py",
    })

    assert ".venv/hidden.py" in historical.skipped_paths

    local_edges = [
        edge
        for edge in historical.dependencies.edges
        if edge.classification == "local"
    ]

    assert any(
        edge.source_file == "consumer.py"
        and edge.resolved_file == "pkg/core.py"
        for edge in local_edges
    )

    metadata = historical.to_dict()

    assert metadata["snapshot_sha256"] == (
        historical.dependencies.snapshot_sha256
    )
    assert metadata["python_files_indexed"] == 3
    assert metadata["python_files_analyzed"] == 3


def test_historical_snapshot_enforces_total_byte_limit(
    tmp_path: Path,
) -> None:
    initialize_repository(tmp_path)

    write(
        tmp_path,
        "large_module.py",
        "VALUE = 'This file is larger than one byte.'\n",
    )

    commit = commit_all(tmp_path, "base snapshot")

    with pytest.raises(
        GitRevisionSnapshotError,
        match="total byte limit",
    ):
        load_git_revision_dependencies(
            tmp_path,
            revision=commit,
            max_total_python_bytes=1,
        )


def test_historical_snapshot_rejects_invalid_revision(
    tmp_path: Path,
) -> None:
    initialize_repository(tmp_path)

    write(tmp_path, "app.py", "VALUE = 1\n")
    commit_all(tmp_path, "initial")

    with pytest.raises(GitRevisionSnapshotError):
        load_git_revision_dependencies(
            tmp_path,
            revision="revision-that-does-not-exist",
        )


def test_historical_snapshot_requires_repository_root(
    tmp_path: Path,
) -> None:
    initialize_repository(tmp_path)

    write(tmp_path, "pkg/app.py", "VALUE = 1\n")
    commit_all(tmp_path, "initial")

    with pytest.raises(
        GitRevisionSnapshotError,
        match="top-level directory",
    ):
        load_git_revision_dependencies(
            tmp_path / "pkg",
            revision="HEAD",
        )
