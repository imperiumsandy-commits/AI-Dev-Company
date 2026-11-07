from __future__ import annotations

from pathlib import Path

import pytest

from company_os.context import (
    analyze_change_impact,
    map_python_dependencies,
    scan_repository,
)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_report(root: Path):
    """Create a small package with a known dependency graph."""

    write(root / "pkg" / "__init__.py", "")
    write(root / "pkg" / "repository.py", "VALUE = 1\n")
    write(
        root / "pkg" / "service.py",
        "import pkg.repository\n",
    )
    write(
        root / "app.py",
        "import pkg.service\n",
    )
    write(
        root / "independent.py",
        "VALUE = 99\n",
    )

    snapshot = scan_repository(root)
    return map_python_dependencies(root, snapshot)


def test_finds_direct_and_transitive_dependents(tmp_path: Path) -> None:
    report = build_report(tmp_path)

    impact = analyze_change_impact(
        report,
        ["pkg/repository.py"],
    )

    by_path = {
        item.path: item
        for item in impact.impacted_files
    }

    assert set(by_path) == {
        "pkg/service.py",
        "app.py",
    }

    assert by_path["pkg/service.py"].direct is True
    assert by_path["pkg/service.py"].distance == 1

    assert by_path["app.py"].direct is False
    assert by_path["app.py"].distance == 2

    assert by_path["app.py"].dependency_chain == (
        "pkg/repository.py",
        "pkg/service.py",
        "app.py",
    )


def test_reports_correct_impact_counts(tmp_path: Path) -> None:
    report = build_report(tmp_path)

    impact = analyze_change_impact(
        report,
        ["pkg/repository.py"],
    )

    assert impact.impacted_count == 2
    assert impact.direct_count == 1
    assert impact.transitive_count == 1


def test_multiple_changed_files_are_normalized_and_deduplicated(
    tmp_path: Path,
) -> None:
    report = build_report(tmp_path)

    impact = analyze_change_impact(
        report,
        [
            "pkg/repository.py",
            "pkg\\repository.py",
            "pkg/service.py",
        ],
    )

    assert impact.changed_files == (
        "pkg/repository.py",
        "pkg/service.py",
    )

    assert "app.py" in {
        item.path for item in impact.impacted_files
    }

    # Changed files are not reported as their own impacted files.
    assert not (
        set(impact.changed_files)
        & {item.path for item in impact.impacted_files}
    )


def test_empty_changed_files_are_rejected(tmp_path: Path) -> None:
    report = build_report(tmp_path)

    with pytest.raises(ValueError):
        analyze_change_impact(report, [])


def test_string_instead_of_iterable_is_rejected(tmp_path: Path) -> None:
    report = build_report(tmp_path)

    with pytest.raises(TypeError):
        analyze_change_impact(report, "app.py")


@pytest.mark.parametrize(
    "path",
    [
        "",
        ".",
        "../outside.py",
        "pkg/../../outside.py",
        "/absolute/file.py",
        "C:\\outside\\file.py",
    ],
)
def test_unsafe_changed_paths_are_rejected(
    tmp_path: Path,
    path: str,
) -> None:
    report = build_report(tmp_path)

    with pytest.raises(ValueError):
        analyze_change_impact(report, [path])


def test_external_imports_are_not_treated_as_repository_dependents(
    tmp_path: Path,
) -> None:
    write(
        tmp_path / "app.py",
        "import requests\n",
    )

    report = map_python_dependencies(
        tmp_path,
        scan_repository(tmp_path),
    )

    impact = analyze_change_impact(
        report,
        ["app.py"],
    )

    assert impact.impacted_files == ()


def test_result_is_deterministic(tmp_path: Path) -> None:
    report = build_report(tmp_path)

    first = analyze_change_impact(
        report,
        ["pkg/repository.py"],
    ).to_dict()

    second = analyze_change_impact(
        report,
        ["pkg/repository.py"],
    ).to_dict()

    assert first == second


def test_cycles_do_not_cause_infinite_traversal(
    tmp_path: Path,
) -> None:
    write(
        tmp_path / "a.py",
        "import b\n",
    )
    write(
        tmp_path / "b.py",
        "import a\n",
    )
    write(
        tmp_path / "c.py",
        "import a\n",
    )

    report = map_python_dependencies(
        tmp_path,
        scan_repository(tmp_path),
    )

    impact = analyze_change_impact(
        report,
        ["a.py"],
    )

    paths = {item.path for item in impact.impacted_files}

    assert paths == {"b.py", "c.py"}
    assert "a.py" not in paths


def test_to_dict_is_json_serializable(tmp_path: Path) -> None:
    import json

    report = build_report(tmp_path)

    impact = analyze_change_impact(
        report,
        ["pkg/repository.py"],
    )

    encoded = json.dumps(impact.to_dict())
    decoded = json.loads(encoded)

    assert decoded["impacted_count"] == 2
    assert decoded["direct_count"] == 1
    assert decoded["transitive_count"] == 1
