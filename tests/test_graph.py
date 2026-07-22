"""End-to-end graph run with the mock model: valid run dir, opps, registry."""

from __future__ import annotations

import json
from pathlib import Path

from automation_miner.artifacts.workspace import read_json
from automation_miner.graph.build import run_mine
from automation_miner.schemas import LAYER_ORDER


def test_full_run_dry(workspace: Path) -> None:
    result = run_mine(
        workspace_path=workspace,
        idea="German healthcare back office",
        constraints="budget:low",
        dry_run=True,
    )
    run_dir = Path(result["run_dir"])

    # Artifacts exist
    for rel in (
        "context.json",
        "domain_map.json",
        "opportunities.json",
        "run.json",
        "run.md",
        "report.md",
    ):
        assert (run_dir / rel).is_file(), f"missing {rel}"
    for layer in LAYER_ORDER:
        assert (run_dir / "layers" / f"{layer.value}.json").is_file()

    # Five mock opportunities, one per layer, sequential AM ids
    opps = result["opportunities"]
    assert len(opps) == 5
    assert [o["am_id"] for o in opps] == [f"AM-{i:03d}" for i in range(1, 6)]
    layers = {o["draft"]["layer"] for o in opps}
    assert layers == {layer.value for layer in LAYER_ORDER}

    # ICE math is deterministic (mock scorer: 4/4/4)
    assert all(o["ice"] == 64 for o in opps)
    assert all(o["score"]["rationale"] for o in opps)

    # Draft iterations persisted (mock critic passes at v1)
    drafts = list((run_dir / "drafts").glob("AM-*.v1.json"))
    assert len(drafts) == 5

    # Briefs published in partitioned opps dir with exact frontmatter
    opp_files = sorted((workspace / "opps" / "german-healthcare-back-office").glob("AM-*.md"))
    assert len(opp_files) == 5
    text = opp_files[0].read_text(encoding="utf-8")
    assert text.startswith("---\nam-id: \"AM-001\"")
    assert 'layer: "document"' in text
    assert "## Problem Statement" in text
    assert "## Risk & Mitigations" in text
    assert "## Self-Improvement" in text

    # Report + run log rendered
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "| 1 | AM-001 |" in report
    assert "Low-hanging fruit" in report
    run_md = (run_dir / "run.md").read_text(encoding="utf-8")
    assert "# Automation Mining Run" in run_md
    assert "## Phase 1: Domain Map" in run_md

    # Registry rebuilt with all five entries
    registry = read_json(workspace / "registry.json")
    assert registry["stats"]["opps"] == 5
    assert len(registry["by_ice_range"]["high_60_79"]) == 5
    assert registry["stats"]["layers"] == {
        "document": 1,
        "communication": 1,
        "decision": 1,
        "monitoring": 1,
        "knowledge": 1,
    }

    # Manifest
    manifest = read_json(run_dir / "run.json")
    assert manifest["dry_run"] is True
    assert manifest["max_iterations"] == 2
    assert manifest["opportunities"] == [f"AM-{i:03d}" for i in range(1, 6)]


def test_numbering_continues_across_runs(workspace: Path) -> None:
    run_mine(workspace_path=workspace, idea="Domain one", dry_run=True)
    result = run_mine(workspace_path=workspace, idea="Domain two", dry_run=True)
    ids = [o["am_id"] for o in result["opportunities"]]
    assert ids == [f"AM-{i:03d}" for i in range(6, 11)]


def test_compliance_constraint_applies_override(workspace: Path) -> None:
    result = run_mine(
        workspace_path=workspace,
        idea="Hospital billing",
        constraints="compliance:heavy",
        dry_run=True,
    )
    opps = result["opportunities"]
    assert all(o["draft"]["risk_level"] == "medium" for o in opps)
    assert any(o["overrides_applied"] for o in opps)


def test_run_with_kb_input(workspace: Path, tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "notes.md").write_text("# Domain notes\nManual reporting everywhere.", "utf-8")
    result = run_mine(workspace_path=workspace, kb=kb, dry_run=True)
    ctx = read_json(Path(result["run_dir"]) / "context.json")
    assert ctx["source_kind"] == "kb"
    assert "Manual reporting" in ctx["content"]


def test_opportunities_json_filters(workspace: Path) -> None:
    result = run_mine(workspace_path=workspace, idea="Any domain", dry_run=True)
    portfolio = json.loads(
        (Path(result["run_dir"]) / "opportunities.json").read_text(encoding="utf-8")
    )
    assert set(portfolio["filters"]) == {"low_hanging", "high_value", "vision"}
    # mock scores (4/4/4, medium risk) hit low-hanging + high-value
    assert len(portfolio["filters"]["low_hanging"]) == 5
    assert len(portfolio["filters"]["high_value"]) == 5
    assert portfolio["filters"]["vision"] == []
