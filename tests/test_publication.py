"""Crash-recovery tests for run publication state."""

from __future__ import annotations

import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from automation_miner.artifacts.layout import RunLayout
from automation_miner.artifacts.registry import reindex
from automation_miner.artifacts.workspace import read_json


def _journal(run_dir: Path) -> Path:
    path = RunLayout(run_dir).journal
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _brief(run_id: str, am_id: str = "AM-001") -> str:
    return f'''---
am-id: "{am_id}"
title: "Published"
domain: "Domain"
layer: "document"
status: "identified"
ice-score: 64
impact: 4
confidence: 4
ease: 4
source: "{run_id}"
---

# {am_id}: Published
'''


def _manifest(run_id: str, *, publication_status: str) -> dict[str, object]:
    return {
        "run_id": run_id,
        "domain": "Domain",
        "domain_slug": "domain",
        "constraints": "",
        "source_kind": "idea",
        "source_value": "domain",
        "analysis_mode": "operational",
        "status": "completed",
        "publication_status": publication_status,
        "created": "2026-08-28T00:00:00",
        "max_iterations": 1,
        "profile": "default",
        "config_source": "defaults",
        "prompt_version": "3.2",
        "dry_run": True,
        "opportunities": ["AM-001"],
    }


def test_reindex_quarantines_dead_interrupted_publication(tmp_path: Path) -> None:
    run_id = "2026-08-28_interrupted"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps(_manifest(run_id, publication_status="pending")), encoding="utf-8"
    )
    _journal(run_dir).write_text(
        json.dumps({"run_id": run_id, "state": "promoted", "pid": 999_999_999}),
        encoding="utf-8",
    )
    (run_dir / "opportunities.json").write_text(
        json.dumps({"stats": {"total": 1, "published": 1}, "filters": {"high_value": ["AM-001"]}}),
        encoding="utf-8",
    )
    opp_dir = tmp_path / "opps" / "domain"
    opp_dir.mkdir(parents=True)
    (opp_dir / "AM-001-published.md").write_text(_brief(run_id), encoding="utf-8")

    registry = reindex(tmp_path)

    assert registry["entries"] == []
    assert not list((tmp_path / "opps").rglob("AM-*.md"))
    assert read_json(run_dir / "run.json")["status"] == "failed"
    manifest = read_json(run_dir / "run.json")
    assert manifest["opportunities"] == []
    assert manifest["filtered"] == ["AM-001"]
    assert read_json(_journal(run_dir))["state"] == "quarantined"
    assert (run_dir / "error.json").is_file()
    summary = read_json(run_dir / "summary.json")
    assert summary["status"] == "failed"
    assert summary["publication_status"] == "pending"
    assert summary["stats"]["total"] == 1
    assert summary["stats"]["published"] == 0
    portfolio = read_json(run_dir / "opportunities.json")
    assert portfolio["published_opportunities"] == []
    assert portfolio["stats"]["published"] == 0
    assert portfolio["stats"]["filters"] == {}


def test_reindex_completes_manifest_finalization_idempotently(tmp_path: Path) -> None:
    run_id = "2026-08-28_manifest-complete"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps(_manifest(run_id, publication_status="complete")), encoding="utf-8"
    )
    _journal(run_dir).write_text(
        json.dumps({"run_id": run_id, "state": "manifest_complete", "pid": 1}),
        encoding="utf-8",
    )
    (run_dir / "summary.json").write_text(
        json.dumps({"status": "completed", "publication_status": "pending"}),
        encoding="utf-8",
    )
    (run_dir / "report.md").write_text(
        "> **Status:** completed  \n> **Publication:** pending  \n", encoding="utf-8"
    )

    reindex(tmp_path)
    reindex(tmp_path)

    assert read_json(_journal(run_dir))["state"] == "complete"
    assert read_json(run_dir / "summary.json")["publication_status"] == "complete"
    assert "> **Publication:** complete  " in (run_dir / "report.md").read_text()


def test_reindex_recovers_after_manifest_commit_before_journal_commit(tmp_path: Path) -> None:
    run_id = "2026-08-28_manifest-before-journal"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps(_manifest(run_id, publication_status="complete")), encoding="utf-8"
    )
    _journal(run_dir).write_text(
        json.dumps({"run_id": run_id, "state": "views_written", "pid": 999_999_999}),
        encoding="utf-8",
    )
    (run_dir / "summary.json").write_text(
        json.dumps({"status": "completed", "publication_status": "pending"}),
        encoding="utf-8",
    )
    (run_dir / "report.md").write_text(
        "> **Status:** completed  \n> **Publication:** pending  \n", encoding="utf-8"
    )
    opp_dir = tmp_path / "opps" / "domain"
    opp_dir.mkdir(parents=True)
    (opp_dir / "AM-001-published.md").write_text(_brief(run_id), encoding="utf-8")

    registry = reindex(tmp_path)

    assert registry["stats"]["opps"] == 1
    assert (opp_dir / "AM-001-published.md").is_file()
    assert read_json(_journal(run_dir))["state"] == "complete"
    assert read_json(run_dir / "summary.json")["publication_status"] == "complete"


def test_concurrent_reindex_keeps_all_published_entries(tmp_path: Path) -> None:
    for number in (1, 2):
        run_id = f"2026-08-28_domain-{number}"
        run_dir = tmp_path / "runs" / run_id
        run_dir.mkdir(parents=True)
        manifest = _manifest(run_id, publication_status="complete")
        manifest["opportunities"] = [f"AM-00{number}"]
        (run_dir / "run.json").write_text(json.dumps(manifest), encoding="utf-8")
        opp_dir = tmp_path / "opps" / f"domain-{number}"
        opp_dir.mkdir(parents=True)
        (opp_dir / f"AM-00{number}-published.md").write_text(
            _brief(run_id, f"AM-00{number}"), encoding="utf-8"
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: reindex(tmp_path), range(4)))

    assert {entry["i"] for entry in read_json(tmp_path / "registry.json")["entries"]} == {
        "AM-001",
        "AM-002",
    }
