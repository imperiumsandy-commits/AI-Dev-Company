from __future__ import annotations

from pathlib import Path

from company_os.context.__main__ import main


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def create_project(root: Path) -> None:
    write(root / "pkg" / "__init__.py", "")
    write(root / "pkg" / "core.py", "VALUE = 1\n")
    write(
        root / "pkg" / "service.py",
        "import pkg.core\n",
    )


def test_cli_rejects_missing_changed_file(
    tmp_path: Path,
    capsys,
) -> None:
    create_project(tmp_path)

    output = tmp_path / ".ai-dev-company" / "index.json"

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--output",
            str(output),
            "--changed",
            "pkg/does_not_exist.py",
        ]
    )

    assert exit_code == 2
    assert not output.exists()

    error = capsys.readouterr().err

    assert "not present in the repository snapshot" in error
    assert "pkg/does_not_exist.py" in error


def test_cli_rejects_scanner_excluded_changed_file(
    tmp_path: Path,
    capsys,
) -> None:
    create_project(tmp_path)

    # The repository scanner deliberately excludes virtual environments.
    write(
        tmp_path / ".venv" / "ignored_module.py",
        "VALUE = 10\n",
    )

    output = tmp_path / ".ai-dev-company" / "index.json"

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--output",
            str(output),
            "--changed",
            ".venv/ignored_module.py",
        ]
    )

    assert exit_code == 2
    assert not output.exists()

    error = capsys.readouterr().err

    assert "not present in the repository snapshot" in error
    assert ".venv/ignored_module.py" in error


def test_cli_rejects_unsupported_binary_changed_file(
    tmp_path: Path,
    capsys,
) -> None:
    create_project(tmp_path)

    binary_file = tmp_path / "assets" / "image.png"
    binary_file.parent.mkdir(parents=True, exist_ok=True)
    binary_file.write_bytes(b"\x89PNG\r\n\x1a\n")

    output = tmp_path / ".ai-dev-company" / "index.json"

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--output",
            str(output),
            "--changed",
            "assets/image.png",
        ]
    )

    assert exit_code == 2
    assert not output.exists()

    error = capsys.readouterr().err

    assert "not present in the repository snapshot" in error
    assert "assets/image.png" in error
