"""Workspace path validation and atomic artifact helpers."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from automation_miner.artifacts.workspace import (
    Workspace,
    normalize_am_id,
    read_json,
    write_json,
)


def test_normalize_am_id() -> None:
    assert normalize_am_id("2") == "AM-002"
    assert normalize_am_id("am-12") == "AM-012"
    assert normalize_am_id("AM-1000") == "AM-1000"
    for invalid in ("", "AM-000", "*", "AM-1*", "../AM-001"):
        with pytest.raises(ValueError):
            normalize_am_id(invalid)


def test_run_report_path_accepts_only_direct_generated_ids(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    path = workspace.run_report_path("2026-07-22_test-domain-2")
    assert path == tmp_path / "runs" / "2026-07-22_test-domain-2" / "report.md"
    with pytest.raises(ValueError):
        workspace.run_report_path("../../outside")


def test_repeated_run_directories_are_unique(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    first = workspace.new_run_dir("domain")
    second = workspace.new_run_dir("domain")
    assert first != second
    assert second.name.endswith("-2")


def test_write_json_replaces_complete_document(tmp_path: Path) -> None:
    path = tmp_path / "artifact.json"
    write_json(path, {"version": 1})
    write_json(path, {"version": 2, "complete": True})
    assert read_json(path) == {"version": 2, "complete": True}
    assert not list(tmp_path.glob("*.tmp"))


def test_am_number_reservations_are_monotonic_and_concurrent(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        ranges = list(pool.map(lambda _: workspace.reserve_am_numbers(2), range(4)))
    allocated = sorted(number for batch in ranges for number in batch)
    assert allocated == list(range(1, 9))
    assert (tmp_path / ".am-ids.sqlite3").is_file()
    assert workspace.reserve_am_numbers(1) == [9]


def test_am_number_reservation_continues_from_registry_only_migration(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    write_json(workspace.registry_path, {"entries": [{"i": "AM-377"}]})
    assert workspace.reserve_am_numbers(2) == [378, 379]


def test_am_number_reservation_migrates_legacy_counter(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    (tmp_path / ".am-counter").write_text("41\n", encoding="utf-8")

    assert workspace.reserve_am_numbers(2) == [42, 43]
    assert workspace.next_am_number() == 44
    assert (tmp_path / ".am-counter").read_text(encoding="utf-8").strip() == "43"


def test_am_number_reservation_is_unique_across_processes(tmp_path: Path) -> None:
    script = (
        "from pathlib import Path; "
        "from automation_miner.artifacts.workspace import Workspace; "
        f"print(Workspace(Path({str(tmp_path)!r})).reserve_am_numbers(2))"
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    outputs = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr
        outputs.append(json.loads(stdout.replace("'", '"')))

    assert sorted(number for batch in outputs for number in batch) == [1, 2, 3, 4]


def test_find_opportunity_rejects_non_list_manifest_opportunities(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    run_id = "2026-08-28_scalar-manifest"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "publication_status": "complete",
                "opportunities": "AM-001",
            }
        ),
        encoding="utf-8",
    )
    opp_dir = tmp_path / "opps" / "domain"
    opp_dir.mkdir(parents=True)
    (opp_dir / "AM-001-scalar.md").write_text(
        '---\nam-id: "AM-001"\nsource: "2026-08-28_scalar-manifest"\n---\n',
        encoding="utf-8",
    )

    assert workspace.find_opportunity("AM-001") is None


def test_find_opportunity_rejects_mismatch_and_ambiguity(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    run_id = "2026-08-28_lookup-safe"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "publication_status": "complete",
                "opportunities": ["AM-001"],
            }
        ),
        encoding="utf-8",
    )
    opp_dir = tmp_path / "opps" / "domain"
    opp_dir.mkdir(parents=True)
    mismatched = '---\nam-id: "AM-999"\nsource: "2026-08-28_lookup-safe"\n---\n'
    matching = '---\nam-id: "AM-001"\nsource: "2026-08-28_lookup-safe"\n---\n'
    (opp_dir / "AM-001-mismatch.md").write_text(mismatched, encoding="utf-8")
    (opp_dir / "AM-001-first.md").write_text(matching, encoding="utf-8")
    (opp_dir / "AM-001-second.md").write_text(matching, encoding="utf-8")

    assert workspace.find_opportunity("AM-001") is None
