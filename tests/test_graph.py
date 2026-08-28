"""End-to-end graph run with the mock model: valid run dir, opps, registry."""

from __future__ import annotations

import json
from pathlib import Path

from automation_miner.artifacts.workspace import read_json
from automation_miner.graph.build import run_mine
from automation_miner.schemas import LAYER_ORDER
import pytest


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
        "input_assessment.json",
        "domain_map.json",
        "opportunities.json",
        "summary.json",
        "run.json",
        "run.md",
        "report.md",
    ):
        assert (run_dir / rel).is_file(), f"missing {rel}"
    for layer in LAYER_ORDER:
        assert (run_dir / "layers" / f"{layer.value}.json").is_file()
    assert (run_dir / "candidate_portfolio.json").is_file()
    assert len(list((run_dir / "drafts").glob("candidate-*.json"))) == 5
    assert (run_dir / "scores.json").is_file()
    assert (run_dir / "ranked.json").is_file()

    # Five mock opportunities, one per layer, sequential AM ids
    opps = result["opportunities"]
    assert len(opps) == 5
    assert [o["am_id"] for o in opps] == [f"AM-{i:03d}" for i in range(1, 6)]
    layers = {o["draft"]["layer"] for o in opps}
    assert layers == {layer.value for layer in LAYER_ORDER}

    # ICE math is deterministic (mock scorer: 4/4/4)
    assert all(o["ice"] == 64 for o in opps)
    assert all(o["tier"] == "high" for o in opps)
    for opp in opps:
        for factor in ("impact_rationale", "confidence_rationale", "ease_rationale"):
            assert opp["score"][factor], factor

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
    run_md = (run_dir / "run.md").read_text(encoding="utf-8")
    assert "# Automation Mining Run" in run_md
    assert "## Phase 1: Domain Map" in run_md
    assert "Operations team -> Intake -> Validation" in run_md

    domain_map = read_json(run_dir / "domain_map.json")
    assert domain_map["stakeholder_processes"][0]["processes"]

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
    assert manifest["status"] == "completed"
    assert manifest["budget"]["max_attempts"] == 70
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
    domain_map = read_json(run_dir / "domain_map.json")
    manifest = read_json(run_dir / "run.json")
    assert domain_map["analysis_mode"] == "strategy"
    assert manifest["analysis_mode"] == "strategy"


def test_dynamic_constraint_params_are_persisted_and_reach_prompts(
    workspace: Path, monkeypatch
) -> None:
    from automation_miner.models.client import MinerModel

    prompts: list[str] = []
    original = MinerModel.call_json

    def capture(self, role, system, prompt, schema):  # type: ignore[no-untyped-def]
        prompts.append(prompt)
        return original(self, role, system, prompt, schema)

    monkeypatch.setattr(MinerModel, "call_json", capture)
    result = run_mine(
        workspace_path=workspace,
        idea="OpenClaw-only opportunity portfolio",
        constraint_params={"agent": "openclaw", "deployment": "local-only"},
        dry_run=True,
    )
    run_dir = Path(result["run_dir"])
    context = read_json(run_dir / "context.json")
    manifest = read_json(run_dir / "run.json")

    expected = {"agent": "openclaw", "deployment": "local-only"}
    assert context["constraint_params"] == expected
    assert manifest["constraint_params"] == expected
    opportunities = read_json(run_dir / "opportunities.json")["opportunities"]
    assert all(
        "OpenClaw agent runtime" in opportunity["draft"]["technical_requirements"]
        for opportunity in opportunities
    )
    planner = next(prompt for prompt in prompts if "Prior published ideas" in prompt)
    candidate_prompts = [
        prompt for prompt in prompts if "Complete planned portfolio" in prompt
    ]
    assert "- agent = openclaw" in planner
    assert len(candidate_prompts) == 5
    assert all("- deployment = local-only" in prompt for prompt in candidate_prompts)


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


def test_portfolio_planner_and_drafters_share_all_candidate_ideas(
    workspace: Path, monkeypatch
) -> None:
    from automation_miner.models.client import MinerModel

    candidate_prompts: list[str] = []
    original = MinerModel.call_json

    def capture(self, role, system, prompt, schema):  # type: ignore[no-untyped-def]
        if "Complete planned portfolio" in prompt:
            candidate_prompts.append(prompt)
        return original(self, role, system, prompt, schema)

    monkeypatch.setattr(MinerModel, "call_json", capture)
    run_mine(workspace_path=workspace, idea="Diverse portfolio", dry_run=True)

    assert len(candidate_prompts) == 5
    for prompt in candidate_prompts:
        for layer in LAYER_ORDER:
            assert f"High-Value {layer.value.title()} Opportunity" in prompt


def test_portfolio_planner_receives_prior_published_ideas(
    workspace: Path, monkeypatch
) -> None:
    from automation_miner.models.client import MinerModel

    run_mine(workspace_path=workspace, idea="Repeatable domain", dry_run=True)
    planner_prompts: list[str] = []
    original = MinerModel.call_json

    def capture(self, role, system, prompt, schema):  # type: ignore[no-untyped-def]
        if "Prior published ideas to avoid repeating" in prompt:
            planner_prompts.append(prompt)
        return original(self, role, system, prompt, schema)

    monkeypatch.setattr(MinerModel, "call_json", capture)
    run_mine(workspace_path=workspace, idea="Repeatable domain", dry_run=True)

    assert len(planner_prompts) == 1
    for layer in LAYER_ORDER:
        assert f"High-Value {layer.value.title()} Opportunity" in planner_prompts[0]


def test_idea_count_can_be_changed_without_code_policy(workspace: Path) -> None:
    result = run_mine(
        workspace_path=workspace,
        idea="Three focused ideas",
        constraint_params={"ideas": 3},
        dry_run=True,
    )
    portfolio = read_json(Path(result["run_dir"]) / "candidate_portfolio.json")
    assert len(portfolio["candidates"]) == 3
    assert len(result["opportunities"]) == 3


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
    assert "Manual reporting" in ctx["overview"]
    assert ctx["chunks"][0]["id"] == "S1"
    assert ctx["stats"]["included_files"] == 1


def test_run_with_mixed_format_kb(workspace: Path, tmp_path: Path) -> None:
    """Every registered format contributes, and unreadable files are reported."""
    pytest.importorskip("pypdf")
    from test_readers import make_pdf

    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "sop.md").write_text("# SOP\n\n400 claims/day by hand.", encoding="utf-8")
    (kb / "rules.pdf").write_bytes(make_pdf(["Audit trail retained 10 years."]))
    (kb / "volumes.csv").write_text(
        "month,claims\n2026-01,8000\n2026-02,8100\n", encoding="utf-8"
    )
    (kb / "broken.json").write_text('{"a": [1,', encoding="utf-8")
    (kb / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)))

    result = run_mine(workspace_path=workspace, kb=kb, dry_run=True)
    ctx = read_json(Path(result["run_dir"]) / "context.json")

    assert ctx["stats"]["included_files"] == 4
    assert ctx["stats"]["skipped_files"] == 1
    sources = {chunk["source"] for chunk in ctx["chunks"]}
    assert sources == {"sop.md", "rules.pdf", "volumes.csv", "broken.json"}
    assert any(c["locator"] == "p.1" for c in ctx["chunks"])

    report = (Path(result["run_dir"]) / "report.md").read_text(encoding="utf-8")
    assert "## Files Not Read" in report
    assert "logo.png" in report


def test_evidence_refs_resolve_against_the_index(workspace: Path, tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "notes.md").write_text("# Notes\n\nManual rework costs 4h/week.", encoding="utf-8")
    result = run_mine(workspace_path=workspace, kb=kb, dry_run=True)
    opps = result["opportunities"]
    assert all(o["draft"]["evidence_refs"] for o in opps)
    assert all(o["unresolved_refs"] == [] for o in opps)


def test_stage_failure_writes_error_json(workspace: Path, monkeypatch) -> None:
    """A failed stage used to leave context.json and no explanation."""
    from automation_miner.models.client import MinerModel

    original = MinerModel.call_json

    def explode(self, role, system, prompt, schema):  # type: ignore[no-untyped-def]
        if role == "layer_analyst":
            raise RuntimeError("simulated provider outage")
        return original(self, role, system, prompt, schema)

    monkeypatch.setattr(MinerModel, "call_json", explode)
    with pytest.raises(Exception, match="simulated provider outage"):
        run_mine(workspace_path=workspace, idea="Failing domain", dry_run=True)

    run_dirs = list((workspace / "runs").iterdir())
    error = read_json(run_dirs[0] / "error.json")
    assert error["stage"] == "layer_analysis"
    assert error["status"] == "failed"
    assert "simulated provider outage" in error["error"]
    assert "context.json" in error["artifacts_written"]
    assert read_json(run_dirs[0] / "run.json")["status"] == "failed"


def test_run_manifest_exists_during_input_preflight(workspace: Path) -> None:
    observed: list[str] = []

    def preflight(_quality) -> None:  # type: ignore[no-untyped-def]
        run_manifests = list((workspace / "runs").glob("*/run.json"))
        assert len(run_manifests) == 1
        observed.append(read_json(run_manifests[0])["status"])

    run_mine(
        workspace_path=workspace,
        idea="Preflight ownership",
        dry_run=True,
        preflight_callback=preflight,
    )

    assert observed == ["running"]


def test_budget_exhaustion_is_terminal_and_attributed(workspace: Path) -> None:
    from automation_miner.execution import BudgetExceeded
    from automation_miner.models.client import MinerModel
    from automation_miner.models.config import load_config

    config = load_config(None)
    config.budget = {"max_attempts": 1, "max_tokens": 100_000, "max_seconds": 30}
    model = MinerModel(config, dry_run=True)
    try:
        with pytest.raises(BudgetExceeded, match="max_attempts"):
            run_mine(
                workspace_path=workspace,
                idea="Budget limited domain",
                dry_run=True,
                model=model,
            )
    finally:
        model.close()

    run_dir = next((workspace / "runs").iterdir())
    error = read_json(run_dir / "error.json")
    manifest = read_json(run_dir / "run.json")
    assert error["status"] == "budget_exhausted"
    assert error["budget_limit"] == "max_attempts"
    assert manifest["status"] == "budget_exhausted"
    assert manifest["usage"]["attempts"] == 1


def test_setup_failure_still_has_a_terminal_run_manifest(workspace: Path) -> None:
    from automation_miner.models.client import MinerModel
    from automation_miner.models.config import load_config

    config = load_config(None)
    config.roles["mapper"] = {"provider": "missing-provider", "model": "model"}
    model = MinerModel(config, dry_run=False)
    try:
        with pytest.raises(ValueError, match="not defined"):
            run_mine(
                workspace_path=workspace,
                idea="Invalid provider setup",
                model=model,
            )
    finally:
        model.close()

    run_dir = next((workspace / "runs").iterdir())
    assert read_json(run_dir / "run.json")["status"] == "failed"
    assert read_json(run_dir / "error.json")["stage"] == "input_assessment"


def test_invalid_budget_is_recorded_after_run_allocation(workspace: Path) -> None:
    from automation_miner.models.client import MinerModel
    from automation_miner.models.config import load_config

    config = load_config(None)
    config.budget = {"max_attempts": "invalid", "max_tokens": 100, "max_seconds": 30}
    model = MinerModel(config, dry_run=True)
    try:
        with pytest.raises(Exception, match="max_attempts"):
            run_mine(workspace_path=workspace, idea="Invalid budget", model=model)
    finally:
        model.close()

    run_dir = next((workspace / "runs").iterdir())
    assert read_json(run_dir / "run.json")["status"] == "failed"
    assert read_json(run_dir / "error.json")["error_type"] == "ValidationError"


def test_post_publish_failure_marks_partial_artifacts_failed(workspace: Path, monkeypatch) -> None:
    import automation_miner.graph.build as build_module

    def fail_reindex(_root: Path) -> None:
        raise RuntimeError("simulated registry outage")

    monkeypatch.setattr(build_module, "reindex", fail_reindex)
    with pytest.raises(RuntimeError, match="simulated registry outage"):
        run_mine(workspace_path=workspace, idea="Partial publication", dry_run=True)

    run_dir = next((workspace / "runs").iterdir())
    assert read_json(run_dir / "run.json")["status"] == "failed"
    assert read_json(run_dir / "summary.json")["status"] == "failed"
    assert "> **Status:** failed  " in (run_dir / "report.md").read_text(encoding="utf-8")
    assert not list((workspace / "opps").rglob("AM-*.md"))
    error = read_json(run_dir / "error.json")
    assert len(error["quarantined_artifacts"]) == 5


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


@pytest.mark.parametrize("iterations", [0, -1, 11])
def test_invalid_iteration_count_fails_before_creating_run(
    workspace: Path, iterations: int
) -> None:
    with pytest.raises(ValueError, match="between 1 and 10"):
        run_mine(
            workspace_path=workspace,
            idea="Invalid iteration domain",
            max_iterations=iterations,
            dry_run=True,
        )
    assert not (workspace / "runs").exists()


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
    assert entry["filters"] == ["low_hanging", "high_value"]


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


def test_layer_analysts_receive_layer_specific_evidence(
    workspace: Path, tmp_path: Path
) -> None:
    """Each layer used to receive the same undifferentiated blob."""
    from automation_miner.models.client import MinerModel
    from automation_miner.models.config import load_config

    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "forms.md").write_text(
        "# Forms\n\n" + "Clerks fill approval forms and re-key spreadsheet data. " * 40,
        encoding="utf-8",
    )
    (kb / "alerts.md").write_text(
        "# Alerts\n\n" + "Nobody monitors the dashboard; incidents surface late. " * 40,
        encoding="utf-8",
    )

    prompts: dict[str, str] = {}
    original = MinerModel.call_json

    def capture(self, role, system, prompt, schema):  # type: ignore[no-untyped-def]
        if role == "layer_analyst":
            layer = prompt.split("\n", 1)[0].removeprefix("Layer: ").strip()
            prompts[layer] = prompt
        return original(self, role, system, prompt, schema)

    config = load_config(None)
    config.context = {"evidence_tokens": 4_000, "layer_tokens": 300, "chunk_tokens": 120}
    model = MinerModel(config, dry_run=True)
    try:
        MinerModel.call_json = capture  # type: ignore[method-assign]
        run_mine(workspace_path=workspace, kb=kb, dry_run=True, model=model)
    finally:
        MinerModel.call_json = original  # type: ignore[method-assign]
        model.close()

    assert set(prompts) == {layer.value for layer in LAYER_ORDER}
    # The document analyst sees the forms file; the monitoring analyst sees alerts.
    assert "approval forms" in prompts["document"]
    assert "dashboard" in prompts["monitoring"]
    assert prompts["document"] != prompts["monitoring"]
