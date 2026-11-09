from __future__ import annotations

import json

from pathlib import Path

import pytest

from company_os.context.incremental_scanner import (
    scan_repository_incremental,
)
from company_os.context.repository_scanner import (
    ScanPolicy,
    scan_repository,
)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def snapshot_payload(root: Path) -> dict:
    return scan_repository(root).to_dict()


def test_first_incremental_scan_matches_full_scanner(
    tmp_path: Path,
) -> None:
    write(tmp_path / "app.py", "import json\nVALUE = 1\n")
    write(tmp_path / "README.md", "# Project\n")
    write(tmp_path / ".env", "TOKEN=secret\n")
    write(tmp_path / "assets" / "data.bin", "ignored extension")

    expected = snapshot_payload(tmp_path)

    result = scan_repository_incremental(tmp_path)

    assert result.snapshot.to_dict() == expected
    assert result.stats.cache_state == "miss"
    assert result.stats.files_reused == 0
    assert result.stats.files_read == 2
    assert result.stats.verification_mode == "metadata_cache"


def test_second_scan_reuses_unchanged_files_without_reading_content(
    tmp_path: Path,
) -> None:
    write(tmp_path / "app.py", "VALUE = 1\n")
    write(tmp_path / "README.md", "# First\n")

    first = scan_repository_incremental(tmp_path)
    second = scan_repository_incremental(tmp_path)

    assert first.snapshot.snapshot_sha256 == second.snapshot.snapshot_sha256

    assert second.stats.cache_state == "hit"
    assert second.stats.files_reused == 2
    assert second.stats.files_read == 0
    assert second.stats.bytes_read == 0


def test_modified_file_is_re_read_while_unchanged_file_is_reused(
    tmp_path: Path,
) -> None:
    write(tmp_path / "app.py", "VALUE = 1\n")
    write(tmp_path / "README.md", "# Stable\n")

    scan_repository_incremental(tmp_path)

    write(tmp_path / "app.py", "VALUE = 200\n")

    result = scan_repository_incremental(tmp_path)

    assert result.stats.cache_state == "hit"
    assert result.stats.files_read == 1
    assert result.stats.files_reused == 1

    record = next(
        item
        for item in result.snapshot.files
        if item.path == "app.py"
    )

    assert record.sha256 != (
        scan_repository(tmp_path).files[
            next(
                index
                for index, item in enumerate(scan_repository(tmp_path).files)
                if item.path == "README.md"
            )
        ].sha256
    )


def test_added_and_deleted_files_update_the_snapshot(
    tmp_path: Path,
) -> None:
    write(tmp_path / "keep.py", "VALUE = 1\n")
    write(tmp_path / "delete.py", "VALUE = 2\n")

    scan_repository_incremental(tmp_path)

    (tmp_path / "delete.py").unlink()
    write(tmp_path / "new.py", "VALUE = 3\n")

    result = scan_repository_incremental(tmp_path)

    paths = {item.path for item in result.snapshot.files}

    assert paths == {"keep.py", "new.py"}
    assert result.stats.files_reused == 1
    assert result.stats.files_read == 1
    assert result.snapshot.snapshot_sha256 == (
        scan_repository(tmp_path).snapshot_sha256
    )


def test_policy_change_invalidates_previous_cache(
    tmp_path: Path,
) -> None:
    write(tmp_path / "app.py", "VALUE = 1\n")

    scan_repository_incremental(tmp_path)

    changed_policy = ScanPolicy(
        include_hidden_files=False,
    )

    result = scan_repository_incremental(
        tmp_path,
        changed_policy,
    )

    assert result.stats.cache_state == "policy_changed"
    assert result.stats.files_reused == 0
    assert result.stats.files_read == 1


def test_corrupt_cache_falls_back_to_full_scan_and_recovers(
    tmp_path: Path,
) -> None:
    write(tmp_path / "app.py", "VALUE = 1\n")

    first = scan_repository_incremental(tmp_path)
    cache_path = tmp_path / first.cache_path

    cache_path.write_text(
        "{ this is not valid JSON",
        encoding="utf-8",
    )

    recovered = scan_repository_incremental(tmp_path)

    assert recovered.stats.cache_state == "invalid"
    assert recovered.stats.files_reused == 0
    assert recovered.stats.files_read == 1

    # The corrupt cache is replaced with a valid cache.
    json.loads(cache_path.read_text(encoding="utf-8"))

    next_scan = scan_repository_incremental(tmp_path)

    assert next_scan.stats.cache_state == "hit"
    assert next_scan.stats.files_reused == 1
    assert next_scan.stats.files_read == 0


def test_strict_verification_reads_all_eligible_files(
    tmp_path: Path,
) -> None:
    write(tmp_path / "app.py", "VALUE = 1\n")
    write(tmp_path / "README.md", "# Project\n")

    scan_repository_incremental(tmp_path)

    verified = scan_repository_incremental(
        tmp_path,
        verify_unchanged=True,
    )

    assert verified.stats.cache_state == "hit"
    assert verified.stats.files_reused == 0
    assert verified.stats.files_read == 2
    assert verified.stats.verification_mode == (
        "strict_content_verification"
    )

    assert verified.snapshot.snapshot_sha256 == (
        scan_repository(tmp_path).snapshot_sha256
    )


def test_force_full_ignores_cache_and_rebuilds_it(
    tmp_path: Path,
) -> None:
    write(tmp_path / "app.py", "VALUE = 1\n")

    scan_repository_incremental(tmp_path)

    refreshed = scan_repository_incremental(
        tmp_path,
        force_full=True,
    )

    assert refreshed.stats.cache_state == "forced_full"
    assert refreshed.stats.files_reused == 0
    assert refreshed.stats.files_read == 1


def test_cache_cannot_be_written_into_scanned_source_tree(
    tmp_path: Path,
) -> None:
    write(tmp_path / "app.py", "VALUE = 1\n")

    with pytest.raises(ValueError, match="excluded directory"):
        scan_repository_incremental(
            tmp_path,
            cache_path="cache.json",
        )


def test_incremental_scanner_does_not_follow_symlink_files(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / "outside-incremental-secret.txt"
    outside.write_text("do not index", encoding="utf-8")

    link = tmp_path / "linked.txt"

    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unavailable on this platform.")

    result = scan_repository_incremental(tmp_path)

    assert result.snapshot.files == ()
    assert result.snapshot.skipped_files == 1
    assert any(
        warning.code == "symlink_skipped"
        for warning in result.snapshot.warnings
    )
