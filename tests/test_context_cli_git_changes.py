from __future__ import annotations

import json
import shutil
import subprocess

from pathlib import Path

import pytest

from company_os.context.__main__ import main


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


def create_python_project(root: Path) -> None:
    write(root, "pkg/__init__.py", "")
    write(root, "pkg/core.py", "VALUE = 1\n")
    write(root, "pkg/service.py", "import pkg.core\n")
    write(root, "app.py", "import pkg.service\n")


def test_cli_builds_git_change_and_impact_reports(
    tmp_path: Path,
) -> None:
    initialize_repository(tmp_path)
    create_python_project(tmp_path)

    base_commit = commit_all(tmp_path, "base project")

    write(
        tmp_path,
        "pkg/core.py",
        "VALUE = 100\n",
    )
    commit_all(tmp_path, "modify core")

    output = tmp_path / ".ai-dev-company" / "repository-index.json"

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--output",
            str(output),
            "--git-base",
            base_commit,
            "--git-head",
            "HEAD",
        ]
    )

    assert exit_code == 0
    assert output.exists()

    payload = json.loads(
        output.read_text(encoding="utf-8")
    )

    git_changes = payload["git_changes"]

    assert git_changes["change_count"] == 1
    assert git_changes["base_commit"] == base_commit
    assert git_changes["changes"][0]["status"] == "M"
    assert git_changes["changes"][0]["path"] == "pkg/core.py"

    assert payload["change_impact_status"]["status"] == "computed"

    impact = payload["change_impact"]

    assert impact["changed_files"] == ["pkg/core.py"]
    assert impact["impacted_count"] == 2
    assert impact["direct_count"] == 1
    assert impact["transitive_count"] == 1

    impacted_paths = {
        item["path"]
        for item in impact["impacted_files"]
    }

    assert impacted_paths == {
        "pkg/service.py",
        "app.py",
    }


def test_cli_reports_deleted_file_without_fake_current_impact(
    tmp_path: Path,
) -> None:
    initialize_repository(tmp_path)

    write(tmp_path, "pkg/__init__.py", "")
    write(tmp_path, "pkg/legacy.py", "VALUE = 1\n")
    write(tmp_path, "consumer.py", "import pkg.legacy\n")

    base_commit = commit_all(tmp_path, "base project")

    (tmp_path / "pkg" / "legacy.py").unlink()
    commit_all(tmp_path, "remove legacy module")

    output = tmp_path / ".ai-dev-company" / "repository-index.json"

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--output",
            str(output),
            "--git-base",
            base_commit,
        ]
    )

    assert exit_code == 0

    payload = json.loads(
        output.read_text(encoding="utf-8")
    )

    git_changes = payload["git_changes"]

    assert git_changes["change_count"] == 1
    assert git_changes["removed_paths"] == [
        "pkg/legacy.py"
    ]

    assert payload["change_impact"] is None
    assert payload["change_impact_status"]["status"] == "not_computed"

    skipped = payload["change_impact_skipped_paths"]

    assert any(
        item["path"] == "pkg/legacy.py"
        and "Historical impact" in item["reason"]
        or (
            item["path"] == "pkg/legacy.py"
            and "Historical impact" not in item["reason"]
            and "base commit" in item["reason"]
        )
        for item in skipped
    )


def test_cli_rejects_invalid_git_base_without_writing_index(
    tmp_path: Path,
    capsys,
) -> None:
    initialize_repository(tmp_path)

    write(tmp_path, "app.py", "VALUE = 1\n")
    commit_all(tmp_path, "initial")

    output = tmp_path / ".ai-dev-company" / "repository-index.json"

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--output",
            str(output),
            "--git-base",
            "missing-ref",
        ]
    )

    assert exit_code == 2
    assert not output.exists()

    error = capsys.readouterr().err

    assert "Git command failed" in error
