from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from company_os.context import ScanPolicy, map_python_dependencies, scan_repository
from company_os.context.__main__ import main


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_scanner_indexes_text_files_and_stable_hashes(tmp_path: Path) -> None:
    content = "from pathlib import Path\n\nVALUE = 7\n"
    write(tmp_path / "src" / "sample.py", content)
    write(tmp_path / "README.md", "# Example\n")

    snapshot = scan_repository(tmp_path)

    paths = [item.path for item in snapshot.files]
    assert paths == ["README.md", "src/sample.py"]
    record = next(item for item in snapshot.files if item.path == "src/sample.py")
    assert record.sha256 == hashlib.sha256(content.encode()).hexdigest()
    assert record.line_count == 3
    assert record.language == "python"
    assert snapshot.to_dict()["file_count"] == 2
    assert len(snapshot.snapshot_sha256) == 64


def test_scanner_excludes_runtime_secrets_and_diagnostic_logs(tmp_path: Path) -> None:
    write(tmp_path / "src" / "app.py", "print('ok')\n")
    write(tmp_path / ".env", "API_KEY=secret\n")
    write(tmp_path / ".env.example", "API_KEY=replace-me\n")
    write(tmp_path / ".ai-dev-company" / "state.sqlite3", "not source")
    write(tmp_path / "PS-Output.txt", "PowerShell diagnostic output")
    write(tmp_path / "ps output.log", "PowerShell diagnostic output")
    write(tmp_path / "node_modules" / "pkg" / "index.js", "module.exports = 1")

    paths = {item.path for item in scan_repository(tmp_path).files}
    assert paths == {".env.example", "src/app.py"}
    assert not any("secret" in item.path for item in scan_repository(tmp_path).files)


def test_scanner_skips_oversized_files_with_warning(tmp_path: Path) -> None:
    write(tmp_path / "large.py", "x = '123456789'\n")
    snapshot = scan_repository(tmp_path, ScanPolicy(max_file_bytes=5))
    assert snapshot.files == ()
    assert any(item.code == "file_too_large" for item in snapshot.warnings)


def test_scanner_skips_binary_and_non_utf8_files(tmp_path: Path) -> None:
    (tmp_path / "binary.txt").write_bytes(b"not-text\x00payload")
    (tmp_path / "broken.py").write_bytes(b"\xff\xfe\xfd")
    snapshot = scan_repository(tmp_path)
    assert snapshot.files == ()
    assert {item.code for item in snapshot.warnings} == {"binary_file_skipped", "non_utf8_file_skipped"}


def test_scanner_rejects_invalid_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        scan_repository(tmp_path / "missing")


def test_scanner_policy_validates_size_limit() -> None:
    with pytest.raises(ValueError):
        ScanPolicy(max_file_bytes=0)


def test_dependency_mapper_identifies_local_stdlib_and_external_imports(tmp_path: Path) -> None:
    write(tmp_path / "samplepkg" / "__init__.py", "")
    write(tmp_path / "samplepkg" / "helpers.py", "VALUE = 1\n")
    write(
        tmp_path / "samplepkg" / "service.py",
        "import json\nimport requests\nfrom samplepkg import helpers\n",
    )

    snapshot = scan_repository(tmp_path)
    report = map_python_dependencies(tmp_path, snapshot)
    edges = {(item.imported_module, item.classification) for item in report.edges}

    assert ("json", "stdlib") in edges
    assert ("requests", "external") in edges
    assert ("samplepkg.helpers", "local") in edges
    local = next(item for item in report.edges if item.imported_module == "samplepkg.helpers")
    assert local.resolved_file == "samplepkg/helpers.py"


def test_dependency_mapper_resolves_relative_imports(tmp_path: Path) -> None:
    write(tmp_path / "pkg" / "__init__.py", "")
    write(tmp_path / "pkg" / "core.py", "VALUE = 1\n")
    write(tmp_path / "pkg" / "api.py", "from .core import VALUE\n")

    report = map_python_dependencies(tmp_path)

    edge = next(item for item in report.edges if item.source_file == "pkg/api.py")
    assert edge.imported_module == "pkg.core"
    assert edge.classification == "local"
    assert edge.resolved_file == "pkg/core.py"


def test_dependency_mapper_reports_syntax_errors_without_execution(tmp_path: Path) -> None:
    write(tmp_path / "broken.py", "def unfinished(:\n    pass\n")
    report = map_python_dependencies(tmp_path)
    assert report.files_analyzed == 0
    assert len(report.parse_issues) == 1
    assert report.parse_issues[0].path == "broken.py"


def test_dependency_mapper_skips_file_changed_after_snapshot(tmp_path: Path) -> None:
    write(tmp_path / "module.py", "import json\n")
    snapshot = scan_repository(tmp_path)
    write(tmp_path / "module.py", "import os\n")

    report = map_python_dependencies(tmp_path, snapshot)

    assert report.edges == ()
    assert any(item.code == "source_changed_after_scan" for item in report.warnings)


def test_cli_writes_machine_readable_report(tmp_path: Path) -> None:
    write(tmp_path / "app.py", "import json\n")
    output = tmp_path / ".ai-dev-company" / "index.json"

    assert main(["--root", str(tmp_path), "--output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["repository"]["file_count"] == 1
    assert payload["python_dependencies"]["edge_count"] == 1
    assert payload["python_dependencies"]["snapshot_sha256"] == payload["repository"]["snapshot_sha256"]


def test_scanner_does_not_follow_symlink_files(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("do not index", encoding="utf-8")
    link = tmp_path / "linked.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unavailable on this platform.")

    snapshot = scan_repository(tmp_path)
    assert snapshot.files == ()
    assert any(item.code == "symlink_skipped" for item in snapshot.warnings)


def test_dependency_report_is_bound_to_the_scanned_snapshot(tmp_path: Path) -> None:
    write(tmp_path / "module.py", "import json\n")
    snapshot = scan_repository(tmp_path)
    report = map_python_dependencies(tmp_path, snapshot)
    assert report.snapshot_sha256 == snapshot.snapshot_sha256
