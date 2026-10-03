"""Post-publication lifecycle: status changes and measured outcomes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from automation_miner.artifacts.lifecycle import (
    load_ledger,
    parse_status,
    record_outcome,
    resolve_metric,
    set_status,
)
from automation_miner.artifacts.registry import parse_frontmatter
from automation_miner.artifacts.workspace import Workspace, read_json
from automation_miner.cli.main import main
from automation_miner.graph.runner import run_mine
from automation_miner.mcp.tools import dispatch
from automation_miner.schemas import OppStatus


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    run_mine(workspace_path=tmp_path, idea="Claims intake at a regional insurer", dry_run=True)
    return tmp_path


def _brief(root: Path, am_id: str = "AM-001") -> str:
    found = Workspace(root).find_opportunity(am_id)
    assert found is not None
    return found[1].read_text(encoding="utf-8")


def test_status_change_updates_ledger_brief_and_registry(workspace: Path) -> None:
    event = set_status(workspace, "am-001", "evaluating", "pilot agreed")
    assert (event.previous, event.status) == (OppStatus.IDENTIFIED, OppStatus.EVALUATING)
    set_status(workspace, "AM-001", "building")
    brief = _brief(workspace)
    assert parse_frontmatter(brief)["status"] == "implementing"
    assert brief.count("## Lifecycle") == 1 and "pilot agreed" in brief
    assert "status → implementing (from evaluating)" in brief
    entry = next(e for e in read_json(workspace / "registry.json")["entries"] if e["i"] == "AM-001")
    assert entry["s"] == "implementing"
    assert [e.status for e in load_ledger(workspace).events] == [
        OppStatus.EVALUATING, OppStatus.IMPLEMENTING,
    ]


def test_status_rejects_no_op_unknown_and_missing(workspace: Path) -> None:
    with pytest.raises(ValueError, match="already identified"):
        set_status(workspace, "AM-001", "identified")
    with pytest.raises(ValueError, match="unknown status"):
        set_status(workspace, "AM-001", "shipped")
    with pytest.raises(ValueError, match="not found"):
        set_status(workspace, "AM-999", "live")


def test_outcome_resolves_success_measure_numbers(workspace: Path) -> None:
    event = record_outcome(
        workspace, "AM-001", "1", "4 min", baseline="9 min", verdict="met", note="n=212"
    )
    assert event.metric.startswith("Manual handling time per item")
    brief = _brief(workspace)
    assert parse_frontmatter(brief)["outcome"] == "met"
    assert "9 min → 4 min" in brief
    registry = read_json(workspace / "registry.json")
    assert registry["stats"]["outcomes"] == {"met": 1, "partial": 0, "missed": 0}
    with pytest.raises(ValueError, match="success measures"):
        record_outcome(workspace, "AM-001", "99", "x")
    with pytest.raises(ValueError, match="measured value"):
        record_outcome(workspace, "AM-001", "1", "  ")


def test_metric_text_passes_through_and_aliases_resolve() -> None:
    assert resolve_metric("no measures here", " Cycle time ") == "Cycle time"
    assert parse_status("Validating") is OppStatus.EVALUATING


def test_cli_lifecycle_round_trip(workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ws = ["--workspace", str(workspace)]
    assert main(["status", "AM-002", "live", *ws]) == 0
    assert main(["outcome", "AM-002", "2", "12%", "--verdict", "partial", *ws]) == 0
    assert main(["outcomes", "--json", *ws]) == 0
    payload = json.loads(capsys.readouterr().out.split("\n", 2)[2])
    assert payload["count"] == 1 and payload["outcomes"][0]["verdict"] == "partial"
    assert main(["status", "AM-002", "live", *ws]) == 1


def test_mcp_lifecycle_tools(workspace: Path) -> None:
    moved = dispatch("set_opportunity_status", {"am_id": "AM-003", "status": "designing"}, workspace)
    assert moved.success and moved.data["status"] == "designing"
    bad = dispatch("record_opportunity_outcome", {"am_id": "AM-003", "metric": "1"}, workspace)
    assert not bad.success and bad.error.code == "validation_error"
    missing = dispatch("set_opportunity_status", {"am_id": "AM-404", "status": "live"}, workspace)
    assert not missing.success and missing.error.code == "not_found"
    recorded = dispatch(
        "record_opportunity_outcome",
        {"am_id": "AM-003", "metric": "1", "measured": "5 min", "verdict": "missed"},
        workspace,
    )
    assert recorded.success
    listed = dispatch("list_outcomes", {}, workspace)
    assert listed.data["count"] == 1 and listed.data["outcomes"][0]["am_id"] == "AM-003"
