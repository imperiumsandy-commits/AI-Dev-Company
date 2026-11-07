from __future__ import annotations

import shutil
import subprocess

from pathlib import Path

import pytest

from company_os.context.git_changes import (
    GitChangeError,
    detect_git_changes,
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


def test_detects_added_modified_deleted_and_renamed_paths(
    tmp_path: Path,
) -> None:
    initialize_repository(tmp_path)

    write(tmp_path, "pkg/core.py", "VALUE = 1\n")
    write(tmp_path, "delete_me.py", "VALUE = 2\n")
    write(tmp_path, "old name.py", "VALUE = 3\n")

    base_commit = commit_all(tmp_path, "base snapshot")

    write(tmp_path, "pkg/core.py", "VALUE = 100\n")
    write(tmp_path, "added file.py", "VALUE = 4\n")

    (tmp_path / "delete_me.py").unlink()

    run_git(
        tmp_path,
        "mv",
        "old name.py",
        "new name.py",
    )

    commit_all(tmp_path, "change repository")

    report = detect_git_changes(
        tmp_path,
        base_ref=base_commit,
        head_ref="HEAD",
    )

    changes = {
        (item.status, item.path, item.previous_path): item
        for item in report.changes
    }

    assert ("M", "pkg/core.py", None) in changes
    assert ("A", "added file.py", None) in changes
    assert ("D", "delete_me.py", None) in changes
    assert ("R", "new name.py", "old name.py") in changes

    renamed = changes[("R", "new name.py", "old name.py")]

    assert renamed.similarity is not None
    assert 0 <= renamed.similarity <= 100

    assert report.change_count == 4

    assert report.status_counts["added"] == 1
    assert report.status_counts["modified"] == 1
    assert report.status_counts["deleted"] == 1
    assert report.status_counts["renamed"] == 1

    assert report.impact_candidate_paths == (
        "added file.py",
        "new name.py",
        "pkg/core.py",
    )

    assert report.removed_paths == (
        "delete_me.py",
        "old name.py",
    )


def test_same_commit_produces_empty_report(
    tmp_path: Path,
) -> None:
    initialize_repository(tmp_path)

    write(tmp_path, "app.py", "VALUE = 1\n")
    base_commit = commit_all(tmp_path, "initial")

    report = detect_git_changes(
        tmp_path,
        base_ref=base_commit,
        head_ref=base_commit,
    )

    assert report.change_count == 0
    assert report.changes == ()
    assert report.impact_candidate_paths == ()
    assert report.removed_paths == ()
    assert report.status_counts["added"] == 0


def test_invalid_base_ref_is_rejected(
    tmp_path: Path,
) -> None:
    initialize_repository(tmp_path)

    write(tmp_path, "app.py", "VALUE = 1\n")
    commit_all(tmp_path, "initial")

    with pytest.raises(GitChangeError):
        detect_git_changes(
            tmp_path,
            base_ref="this-ref-does-not-exist",
            head_ref="HEAD",
        )


def test_non_repository_root_is_rejected(
    tmp_path: Path,
) -> None:
    with pytest.raises(GitChangeError):
        detect_git_changes(
            tmp_path,
            base_ref="main",
        )


def test_subdirectory_is_not_mistaken_for_repository_root(
    tmp_path: Path,
) -> None:
    initialize_repository(tmp_path)

    write(tmp_path, "pkg/app.py", "VALUE = 1\n")
    commit_all(tmp_path, "initial")

    with pytest.raises(GitChangeError, match="top-level directory"):
        detect_git_changes(
            tmp_path / "pkg",
            base_ref="HEAD",
        )


def test_empty_base_ref_is_rejected(
    tmp_path: Path,
) -> None:
    initialize_repository(tmp_path)

    write(tmp_path, "app.py", "VALUE = 1\n")
    commit_all(tmp_path, "initial")

    with pytest.raises(ValueError, match="base_ref cannot be empty"):
        detect_git_changes(
            tmp_path,
            base_ref="   ",
        )
