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


def run_index(
    root: Path,
    base_commit: str,
    output: Path,
) -> dict:
    exit_code = main(
        [
            "--root",
            str(root),
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

    return json.loads(
        output.read_text(encoding="utf-8")
    )


def test_cli_builds_git_change_and_current_impact_reports(
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
    payload = run_index(tmp_path, base_commit, output)

    git_changes = payload["git_changes"]

    assert git_changes["change_count"] == 1
    assert git_changes["base_commit"] == base_commit
    assert git_changes["changes"][0]["status"] == "M"
    assert git_changes["changes"][0]["path"] == "pkg/core.py"

    assert payload["schema_version"] == "1.3"
    assert payload["change_impact_status"]["status"] == "computed"

    impact = payload["change_impact"]

    assert impact["changed_files"] == ["pkg/core.py"]
    assert impact["impacted_count"] == 2
    assert impact["direct_count"] == 1
    assert impact["transitive_count"] == 1

    assert {
        item["path"]
        for item in impact["impacted_files"]
    } == {
        "pkg/service.py",
        "app.py",
    }

    assert payload["historical_change_impact"] is None
    assert (
        payload["historical_change_impact_status"]["status"]
        == "no_removed_paths"
    )


def test_deleted_file_uses_historical_dependency_graph(
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
    payload = run_index(tmp_path, base_commit, output)

    git_changes = payload["git_changes"]

    assert git_changes["change_count"] == 1
    assert git_changes["removed_paths"] == ["pkg/legacy.py"]

    # Current snapshot cannot analyse a source file that no longer exists.
    assert payload["change_impact"] is None
    assert payload["change_impact_status"]["status"] == "not_computed"

    # The base commit still contains the deleted source and its dependents.
    historical = payload["historical_change_impact"]

    assert historical is not None
    assert historical["base_commit"] == base_commit

    historical_report = historical["impact_report"]

    assert historical_report["changed_files"] == [
        "pkg/legacy.py"
    ]
    assert historical_report["impacted_count"] == 1
    assert historical_report["direct_count"] == 1

    assert historical_report["impacted_files"][0]["path"] == (
        "consumer.py"
    )

    assert (
        payload["historical_change_impact_status"]["status"]
        == "computed"
    )

    assert not any(
        item["path"] == "pkg/legacy.py"
        for item in payload["change_impact_skipped_paths"]
    )


def test_renamed_file_uses_old_path_for_historical_impact(
    tmp_path: Path,
) -> None:
    initialize_repository(tmp_path)

    write(tmp_path, "pkg/__init__.py", "")
    write(tmp_path, "pkg/legacy.py", "VALUE = 1\n")
    write(tmp_path, "consumer.py", "import pkg.legacy\n")

    base_commit = commit_all(tmp_path, "base project")

    run_git(
        tmp_path,
        "mv",
        "pkg/legacy.py",
        "pkg/modern.py",
    )
    commit_all(tmp_path, "rename legacy module")

    output = tmp_path / ".ai-dev-company" / "repository-index.json"
    payload = run_index(tmp_path, base_commit, output)

    changes = payload["git_changes"]["changes"]

    rename = next(
        item
        for item in changes
        if item["status"] == "R"
    )

    assert rename["path"] == "pkg/modern.py"
    assert rename["previous_path"] == "pkg/legacy.py"

    historical = payload["historical_change_impact"]

    assert historical is not None
    assert historical["impact_report"]["changed_files"] == [
        "pkg/legacy.py"
    ]

    assert {
        item["path"]
        for item in historical["impact_report"]["impacted_files"]
    } == {"consumer.py"}


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
