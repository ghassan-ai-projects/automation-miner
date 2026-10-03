"""End-to-end graph run with the mock model: valid run dir, opps, registry."""

from __future__ import annotations

import json
from pathlib import Path

from automation_miner.artifacts.workspace import read_json
from automation_miner.artifacts.layout import RunLayout
from automation_miner.graph.runner import run_mine
from automation_miner.schemas import LAYER_ORDER


def test_full_run_dry(workspace: Path) -> None:
    result = run_mine(
        workspace_path=workspace,
        idea="German healthcare back office",
        constraints="budget:low",
        dry_run=True,
    )
    run_dir = Path(result["run_dir"])

    # Results at the top level, how-we-got-there under trace/
    layout = RunLayout(run_dir)
    results = {"opportunities.json", "summary.json", "run.json", "report.md"}
    assert {p.name for p in run_dir.iterdir() if p.is_file()} == results
    for path in (layout.context, layout.input_assessment, layout.domain_map, layout.run_log):
        assert path.is_file() and path.parent == layout.trace, path
    for layer in LAYER_ORDER:
        assert layout.layer(layer.value).is_file()
    assert layout.candidate_portfolio.is_file()
    assert len(list(layout.drafts.glob("*.json"))) == 5
    assert read_json(layout.opportunities)["layout"] == 2

    # Five mock opportunities, one per layer, sequential AM ids
    opps = result["opportunities"]
    assert len(opps) == 5
    assert [o["am_id"] for o in opps] == [f"AM-{i:03d}" for i in range(1, 6)]
    layers = {o["draft"]["layer"] for o in opps}
    assert layers == {layer.value for layer in LAYER_ORDER}

    # ICE math is deterministic: mock scorer 4/4/4, and a one-liner caps
    # confidence at 2 because the problem itself is not observed.
    assert all(o["ice"] == 32 for o in opps)
    assert all(o["tier"] == "low" for o in opps)
    assert all(
        any("thin input" in note for note in o["calibration"]) for o in opps
    )
    for opp in opps:
        for factor in ("impact_rationale", "confidence_rationale", "ease_rationale"):
            assert opp["score"][factor], factor

    # Draft iterations persisted (mock critic passes at v1)
    drafts = list(layout.critique.glob("AM-*.v1.json"))
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
    assert "## Validate First" in text
    summary = read_json(run_dir / "summary.json")
    assert summary["input_quality"]["level"] == "thin"
    assert summary["retained_quality"]["level"] == "thin"
    assert all(entry["artifact_type"] == "discovery_hypothesis" for entry in summary["opportunities"])

    # Report + run log rendered
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "| 1 | AM-001 |" in report
    assert "Low-hanging fruit" in report
    assert "German healthcare back office" in report
    assert "## Recommended Sequence" in report
    assert "Model calls:" in report
    run_md = layout.run_log.read_text(encoding="utf-8")
    assert "# Automation Mining Run" in run_md
    assert "## Phase 1: Domain Map" in run_md
    assert "Operations team -> Intake -> Validation" in run_md

    domain_map = read_json(RunLayout(run_dir).domain_map)
    assert domain_map["stakeholder_processes"][0]["processes"]

    # Registry rebuilt with all five entries
    registry = read_json(workspace / "registry.json")
    assert registry["stats"]["opps"] == 5
    assert len(registry["by_ice_range"]["low_under_40"]) == 5
    assert registry["stats"]["layers"] == {
        "document": 1,
        "communication": 1,
        "decision": 1,
        "monitoring": 1,
        "knowledge": 1,
    }

    # Manifest
    manifest = read_json(run_dir / "run.json")
    assert manifest["status"] == "completed"
    assert manifest["budget"]["max_attempts"] == 200
    assert manifest["usage"]["attempts"] > 0
    assert manifest["dry_run"] is True
    assert manifest["max_iterations"] == 2
    assert manifest["input_quality"]["level"] == "thin"
    assert manifest["retained_quality"]["level"] == "thin"
    assert manifest["source_value"] == "German healthcare back office"
    assert manifest["config_source"] == "defaults"
    assert manifest["prompt_version"]
    assert manifest["opportunities"] == [f"AM-{i:03d}" for i in range(1, 6)]
    assert manifest["analysis_mode"] == "operational"


def test_explicit_strategy_mode_is_persisted(workspace: Path) -> None:
    result = run_mine(
        workspace_path=workspace,
        idea="Portfolio AI roadmap and proposed investment themes",
        mode="strategy",
        dry_run=True,
    )
    run_dir = Path(result["run_dir"])
    domain_map = read_json(RunLayout(run_dir).domain_map)
    manifest = read_json(run_dir / "run.json")
    assert domain_map["analysis_mode"] == "strategy"
    assert manifest["analysis_mode"] == "strategy"


def test_unknown_constraint_values_do_not_activate_policy(workspace: Path) -> None:
    result = run_mine(
        workspace_path=workspace,
        idea="Unknown deployment policy",
        constraint_params={"deployment": "budget:low"},
        dry_run=True,
    )

    assert all(
        not any("budget low/zero" in note for note in opportunity["overrides_applied"])
        for opportunity in result["opportunities"]
    )


def test_unresolved_draft_reference_blocks_publication_end_to_end(
    workspace: Path, monkeypatch
) -> None:
    from automation_miner.models import mock

    original = mock.call_json

    def inject_unresolved_ref(role: str, schema_name: str, prompt: str):
        payload = original(role, schema_name, prompt)
        if schema_name == "OpportunityDraft":
            payload["evidence_refs"] = ["S99"]
        return payload

    monkeypatch.setattr(mock, "call_json", inject_unresolved_ref)
    result = run_mine(workspace_path=workspace, idea="Unresolved reference", dry_run=True)

    assert all(opportunity["eligibility"] == "filtered" for opportunity in result["opportunities"])
    assert all(
        any("grounding: cited evidence ids do not resolve: S99" in reason for reason in opportunity["exclusion_reasons"])
        for opportunity in result["opportunities"]
    )
    assert not list((workspace / "opps").rglob("AM-*.md"))


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


def test_opportunities_json_filters(workspace: Path) -> None:
    result = run_mine(workspace_path=workspace, idea="Any domain", dry_run=True)
    portfolio = json.loads(
        (Path(result["run_dir"]) / "opportunities.json").read_text(encoding="utf-8")
    )
    assert set(portfolio["filters"]) == {"low_hanging", "high_value", "vision"}
    # mock scores 4/2/4 on thin input: low-hanging, but below the ICE 40 high-value bar
    assert len(portfolio["filters"]["low_hanging"]) == 5
    assert portfolio["filters"]["high_value"] == []
    assert portfolio["filters"]["vision"] == []


def test_urgent_constraint_publishes_three_and_retains_the_rest(workspace: Path) -> None:
    result = run_mine(
        workspace_path=workspace,
        idea="Urgent domain",
        constraints="urgent, needed in 1 week",
        dry_run=True,
    )
    opps = result["opportunities"]
    published = [o for o in opps if o["eligibility"] == "published"]
    filtered = [o for o in opps if o["eligibility"] == "filtered"]

    # All five are retained; only three reach publication.
    assert len(opps) == 5
    assert len(published) == 3
    assert len(filtered) == 2
    assert all(o["exclusion_reasons"] for o in filtered)

    # Briefs are written only for the published set.
    briefs = sorted((workspace / "opps" / "urgent-domain").glob("AM-*.md"))
    assert len(briefs) == 3

    # And the report explains what was held back rather than hiding it.
    report = (Path(result["run_dir"]) / "report.md").read_text(encoding="utf-8")
    assert "## Excluded from Published Portfolio" in report
    assert "urgent timeline publishes only the top 3" in report


def test_summary_json_is_the_compact_view(workspace: Path) -> None:
    result = run_mine(
        workspace_path=workspace, idea="Summary domain", constraints="budget:low", dry_run=True
    )
    summary = read_json(Path(result["run_dir"]) / "summary.json")

    assert summary["domain"] == "Summary domain"
    assert summary["constraints"] == "budget:low"
    assert summary["dry_run"] is True
    assert summary["stats"]["published"] == 5
    assert summary["context"]["chunks"] >= 1
    assert summary["usage"]["calls"] > 0
    assert summary["notes"], "budget:low must be recorded as an active policy"

    entry = summary["opportunities"][0]
    assert set(entry) >= {"am_id", "title", "layer", "ice", "tier", "filters", "problem"}
    assert entry["filters"] == ["low_hanging"]


def test_run_manifest_records_usage_and_stage_timings(workspace: Path) -> None:
    result = run_mine(workspace_path=workspace, idea="Telemetry domain", dry_run=True)
    manifest = read_json(Path(result["run_dir"]) / "run.json")

    assert manifest["usage"]["calls"] > 0
    assert manifest["usage"]["by_role"]["drafter"]["calls"] == 6
    assert set(manifest["stage_seconds"]) >= {"ingest", "domain_map", "score", "publish"}
    assert manifest["context"]["chunks"] >= 1
    assert manifest["filtered"] == []


def test_parallel_stages_are_deterministic(workspace: Path, tmp_path: Path) -> None:
    """Critique and scoring fan out over threads; order must not vary."""
    from automation_miner.models.client import MinerModel
    from automation_miner.models.config import load_config

    def run(root: Path, workers: int) -> list[str]:
        config = load_config(None)
        config.concurrency = {"critique": workers, "score": workers}
        model = MinerModel(config, dry_run=True)
        try:
            result = run_mine(
                workspace_path=root, idea="Deterministic domain", dry_run=True, model=model
            )
        finally:
            model.close()
        return [o["am_id"] for o in result["opportunities"]]

    serial = run(tmp_path / "serial", workers=1)
    parallel = run(tmp_path / "parallel", workers=5)
    assert serial == parallel == [f"AM-{i:03d}" for i in range(1, 6)]
