from __future__ import annotations

import json

from pathlib import Path

from company_os.context.__main__ import main


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def run_incremental(root: Path, output: Path, *extra: str) -> dict:
    arguments = [
        "--root",
        str(root),
        "--output",
        str(output),
        "--incremental",
    ]

    arguments.extend(extra)

    exit_code = main(arguments)

    assert exit_code == 0
    assert output.exists()

    return json.loads(
        output.read_text(encoding="utf-8")
    )


def test_cli_reuses_unchanged_repository_scan(
    tmp_path: Path,
    capsys,
) -> None:
    write(tmp_path / "app.py", "import json\nVALUE = 1\n")
    write(tmp_path / "README.md", "# Project\n")

    output = tmp_path / ".ai-dev-company" / "repository-index.json"

    first = run_incremental(
        tmp_path,
        output,
    )

    first_stats = first["scan_execution"]["stats"]

    assert first["schema_version"] == "1.4"
    assert first["scan_execution"]["mode"] == "incremental"
    assert first_stats["cache_state"] == "miss"
    assert first_stats["files_reused"] == 0
    assert first_stats["files_read"] == 2

    capsys.readouterr()

    second = run_incremental(
        tmp_path,
        output,
    )

    second_stats = second["scan_execution"]["stats"]

    assert second["snapshot_sha256"] == first["snapshot_sha256"]
    assert second_stats["cache_state"] == "hit"
    assert second_stats["files_reused"] == 2
    assert second_stats["files_read"] == 0
    assert second_stats["bytes_read"] == 0

    output_text = capsys.readouterr().out

    assert "Incremental scan: cache=hit" in output_text
    assert "reused=2" in output_text
    assert "read=0" in output_text


def test_cli_incremental_scan_updates_only_changed_file(
    tmp_path: Path,
) -> None:
    write(tmp_path / "app.py", "VALUE = 1\n")
    write(tmp_path / "README.md", "# Stable\n")

    output = tmp_path / ".ai-dev-company" / "repository-index.json"

    first = run_incremental(tmp_path, output)

    write(tmp_path / "app.py", "VALUE = 200\n")

    second = run_incremental(tmp_path, output)

    stats = second["scan_execution"]["stats"]

    assert second["snapshot_sha256"] != first["snapshot_sha256"]
    assert stats["files_read"] == 1
    assert stats["files_reused"] == 1


def test_cli_strict_verification_requires_incremental_mode(
    tmp_path: Path,
    capsys,
) -> None:
    write(tmp_path / "app.py", "VALUE = 1\n")

    output = tmp_path / ".ai-dev-company" / "repository-index.json"

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--output",
            str(output),
            "--verify-incremental",
        ]
    )

    assert exit_code == 2
    assert not output.exists()

    assert (
        "--verify-incremental requires --incremental"
        in capsys.readouterr().err
    )


def test_cli_refresh_cache_forces_full_content_read(
    tmp_path: Path,
) -> None:
    write(tmp_path / "app.py", "VALUE = 1\n")
    output = tmp_path / ".ai-dev-company" / "repository-index.json"

    run_incremental(tmp_path, output)

    refreshed = run_incremental(
        tmp_path,
        output,
        "--refresh-scan-cache",
    )

    stats = refreshed["scan_execution"]["stats"]

    assert stats["cache_state"] == "forced_full"
    assert stats["files_reused"] == 0
    assert stats["files_read"] == 1
