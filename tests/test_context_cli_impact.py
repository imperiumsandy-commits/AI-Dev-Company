from __future__ import annotations

import json

from pathlib import Path

from company_os.context.__main__ import main


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def create_dependency_project(root: Path) -> None:
    """Create a small project with a predictable import chain."""
    write(root / "pkg" / "__init__.py", "")
    write(root / "pkg" / "core.py", "VALUE = 1\n")
    write(
        root / "pkg" / "service.py",
        "import pkg.core\n",
    )
    write(
        root / "app.py",
        "import pkg.service\n",
    )
    write(
        root / "independent.py",
        "VALUE = 99\n",
    )


def test_cli_includes_impact_report_for_changed_file(
    tmp_path: Path,
    capsys,
) -> None:
    create_dependency_project(tmp_path)
    output = tmp_path / ".ai-dev-company" / "index.json"

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--output",
            str(output),
            "--changed",
            "pkg/core.py",
        ]
    )

    assert exit_code == 0

    payload = json.loads(
        output.read_text(encoding="utf-8")
    )

    impact = payload["change_impact"]

    assert payload["schema_version"] == "1.3"
    assert payload["snapshot_sha256"] == payload["repository"]["snapshot_sha256"]

    assert impact["schema_version"] == "1.1"
    assert impact["snapshot_sha256"] == payload["snapshot_sha256"]
    assert impact["changed_files"] == ["pkg/core.py"]

    assert impact["impacted_count"] == 2
    assert impact["direct_count"] == 1
    assert impact["transitive_count"] == 1

    impacted = {
        item["path"]: item
        for item in impact["impacted_files"]
    }

    assert impacted["pkg/service.py"]["direct"] is True
    assert impacted["app.py"]["direct"] is False

    output_text = capsys.readouterr().out

    assert "Current impact: 2 impacted files" in output_text


def test_cli_supports_multiple_changed_arguments(
    tmp_path: Path,
) -> None:
    create_dependency_project(tmp_path)

    output = tmp_path / ".ai-dev-company" / "index.json"

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--output",
            str(output),
            "--changed",
            "pkg/core.py",
            "--changed",
            "pkg/service.py",
        ]
    )

    assert exit_code == 0

    payload = json.loads(
        output.read_text(encoding="utf-8")
    )

    impact = payload["change_impact"]

    assert impact["changed_files"] == [
        "pkg/core.py",
        "pkg/service.py",
    ]

    # app.py imports the second changed file directly.
    assert impact["impacted_count"] == 1
    assert impact["direct_count"] == 1
    assert impact["transitive_count"] == 0

    assert impact["impacted_files"][0]["path"] == "app.py"


def test_cli_normalizes_windows_style_changed_paths(
    tmp_path: Path,
) -> None:
    create_dependency_project(tmp_path)

    output = tmp_path / ".ai-dev-company" / "index.json"

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--output",
            str(output),
            "--changed",
            r"pkg\core.py",
        ]
    )

    assert exit_code == 0

    payload = json.loads(
        output.read_text(encoding="utf-8")
    )

    assert payload["change_impact"]["changed_files"] == [
        "pkg/core.py"
    ]


def test_cli_rejects_path_traversal_without_writing_index(
    tmp_path: Path,
    capsys,
) -> None:
    create_dependency_project(tmp_path)

    output = tmp_path / ".ai-dev-company" / "index.json"

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--output",
            str(output),
            "--changed",
            "../outside.py",
        ]
    )

    assert exit_code == 2
    assert not output.exists()

    error = capsys.readouterr().err

    assert "Path traversal is not allowed" in error


def test_cli_refuses_to_overwrite_indexed_source_file(
    tmp_path: Path,
    capsys,
) -> None:
    create_dependency_project(tmp_path)

    source = tmp_path / "app.py"
    original_content = source.read_text(encoding="utf-8")

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--output",
            str(source),
        ]
    )

    assert exit_code == 2
    assert source.read_text(encoding="utf-8") == original_content

    error = capsys.readouterr().err

    assert "Refusing to overwrite an indexed source file" in error


def test_cli_keeps_impact_field_stable_when_not_requested(
    tmp_path: Path,
) -> None:
    create_dependency_project(tmp_path)

    output = tmp_path / ".ai-dev-company" / "index.json"

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0

    payload = json.loads(
        output.read_text(encoding="utf-8")
    )

    assert payload["schema_version"] == "1.3"
    assert "change_impact" in payload
    assert payload["change_impact"] is None
    assert payload["git_changes"] is None
    assert payload["change_impact_status"]["status"] == "not_requested"
