"""Planning stages: evidence routing, portfolio plan, constraint parameters."""

from __future__ import annotations

from pathlib import Path

from automation_miner.artifacts.workspace import read_json
from automation_miner.artifacts.layout import RunLayout
from automation_miner.graph.runner import run_mine
from automation_miner.schemas import LAYER_ORDER


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
    portfolio = read_json(RunLayout(Path(result["run_dir"])).candidate_portfolio)
    assert len(portfolio["candidates"]) == 3
    assert len(result["opportunities"]) == 3


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


def test_prior_ideas_only_come_from_the_same_domain(workspace: Path) -> None:
    """Unrelated domains are noise to the planner, not differentiation targets."""
    from automation_miner.artifacts.workspace import Workspace, write_json
    from automation_miner.graph.stages import PipelineStages
    from automation_miner.models.client import MinerModel
    from automation_miner.models.config import load_config

    write_json(
        workspace / "registry.json",
        {
            "entries": [
                {"i": "AM-001", "t": "Parcel ETA bot", "l": "communication", "d": "logistics"},
                {"i": "AM-002", "t": "Claims triage", "l": "decision", "d": "claims"},
            ]
        },
    )
    stages = PipelineStages(MinerModel(load_config(workspace), dry_run=True), Workspace(workspace))
    assert [idea["id"] for idea in stages._prior_ideas("claims")] == ["AM-002"]
    assert stages._prior_ideas("veterinary") == []


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
    context = read_json(RunLayout(run_dir).context)
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


def test_drafters_see_the_evidence_behind_the_pains_they_address(
    workspace: Path, monkeypatch
) -> None:
    """Pain-ledger refs are pinned into each drafter's evidence selection."""
    from automation_miner.context import EvidenceIndex

    pinned_calls: list[list[str]] = []
    original = EvidenceIndex.select

    def spy(self, query, budget_tokens, pinned=()):  # type: ignore[no-untyped-def]
        pinned_calls.append(list(pinned))
        return original(self, query, budget_tokens, pinned=pinned)

    monkeypatch.setattr(EvidenceIndex, "select", spy)
    run_mine(workspace_path=workspace, idea="Pinned pains", dry_run=True)
    # Mock pains cite S1; every drafter (and critic) selection pins it.
    assert pinned_calls and all("S1" in pinned for pinned in pinned_calls if pinned)
