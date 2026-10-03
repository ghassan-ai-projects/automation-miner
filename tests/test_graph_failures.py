"""Terminal failure handling: every failed run is diagnosable from disk."""

from __future__ import annotations

from pathlib import Path

from automation_miner.artifacts.workspace import read_json
from automation_miner.graph.runner import run_mine
import pytest


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
    assert "trace/context.json" in error["artifacts_written"]
    assert read_json(run_dirs[0] / "run.json")["status"] == "failed"
    assert read_json(run_dirs[0] / "summary.json")["status"] == "failed"
    assert "> **Status:** failed  " in (run_dirs[0] / "report.md").read_text(encoding="utf-8")


def test_failure_recording_logs_when_error_artifact_cannot_be_written(
    workspace: Path, monkeypatch, caplog
) -> None:
    import logging
    import automation_miner.graph.failure as build_module
    from automation_miner.models.client import MinerModel

    original = build_module.write_json

    def fail_error(path, payload):  # type: ignore[no-untyped-def]
        if path.name == "error.json":
            raise OSError("error store unavailable")
        return original(path, payload)

    monkeypatch.setattr(build_module, "write_json", fail_error)
    original_call = MinerModel.call_json

    def explode(self, role, system, prompt, schema):  # type: ignore[no-untyped-def]
        if role == "layer_analyst":
            raise RuntimeError("failure for logging")
        return original_call(self, role, system, prompt, schema)

    monkeypatch.setattr(MinerModel, "call_json", explode)
    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError, match="failure for logging"):
            run_mine(workspace_path=workspace, idea="Failure logging", dry_run=True)

    run_dir = next((workspace / "runs").iterdir())
    assert "Unable to persist failure artifact" in caplog.text
    assert run_dir.name in caplog.text
    assert read_json(run_dir / "run.json")["status"] == "failed"
    assert read_json(run_dir / "summary.json")["status"] == "failed"


def test_failure_recording_does_not_mask_original_error_on_malformed_manifest(
    workspace: Path,
) -> None:
    from automation_miner.execution import RunExecutionContext
    from automation_miner.graph.runner import record_failure as _record_failure
    from automation_miner.schemas import RunBudget

    run_dir = workspace / "runs" / "2026-08-28_malformed-manifest"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text("{not-json", encoding="utf-8")
    execution = RunExecutionContext(run_dir.name, RunBudget())

    with pytest.raises(RuntimeError, match="original pipeline error"):
        try:
            raise RuntimeError("original pipeline error")
        except RuntimeError as exc:
            _record_failure(run_dir, exc, execution)
            raise

    assert read_json(run_dir / "summary.json")["status"] == "failed"


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
    import automation_miner.graph.publish as build_module

    def fail_reindex(_root: Path) -> None:
        raise RuntimeError("simulated registry outage")

    monkeypatch.setattr(build_module, "reindex_locked", fail_reindex)
    with pytest.raises(RuntimeError, match="simulated registry outage"):
        run_mine(workspace_path=workspace, idea="Partial publication", dry_run=True)

    run_dir = next((workspace / "runs").iterdir())
    assert read_json(run_dir / "run.json")["status"] == "failed"
    assert read_json(run_dir / "summary.json")["status"] == "failed"
    assert "> **Status:** failed  " in (run_dir / "report.md").read_text(encoding="utf-8")
    assert not list((workspace / "opps").rglob("AM-*.md"))
    error = read_json(run_dir / "error.json")
    assert len(error["quarantined_artifacts"]) == 5
    summary = read_json(run_dir / "summary.json")
    assert summary["stats"]["published"] == 0
    assert all(entry["brief_path"] == "" for entry in summary["opportunities"])


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


def test_failed_run_resumes_without_repeating_completed_stages(
    workspace: Path, monkeypatch
) -> None:
    from collections import Counter

    from automation_miner.graph.runner import resume_run
    from automation_miner.models.client import MinerModel

    calls: Counter[str] = Counter()
    original = MinerModel.call_json
    fail = {"critic": True}

    def counting(self, role, system, prompt, schema, **kwargs):  # type: ignore[no-untyped-def]
        calls[schema.__name__] += 1
        if role == "critic" and fail["critic"]:
            raise RuntimeError("provider outage during critique")
        return original(self, role, system, prompt, schema, **kwargs)

    monkeypatch.setattr(MinerModel, "call_json", counting)
    with pytest.raises(RuntimeError, match="provider outage"):
        run_mine(workspace_path=workspace, idea="Resumable domain", dry_run=True)
    run_dir = next((workspace / "runs").iterdir())
    assert read_json(run_dir / "run.json")["status"] == "failed"
    before = Counter(calls)

    fail["critic"] = False
    result = resume_run(workspace_path=workspace, run_id=run_dir.name, dry_run=True)

    assert result["status"] == "completed"
    assert read_json(run_dir / "run.json")["status"] == "completed"
    assert (run_dir / "error.previous.json").is_file() and not (run_dir / "error.json").exists()
    new = calls - before
    for reused in ("InputAssessment", "DomainMap", "LayerAnalysis", "CandidatePortfolio",
                   "OpportunityDraft"):
        assert new[reused] == 0, reused
    assert new["Critique"] == 5 and new["PortfolioScores"] == 1


def test_only_failed_runs_can_resume(workspace: Path) -> None:
    from automation_miner.graph.runner import resume_run

    result = run_mine(workspace_path=workspace, idea="Done domain", dry_run=True)
    with pytest.raises(ValueError, match="only failed runs"):
        resume_run(workspace_path=workspace, run_id=result["run_id"], dry_run=True)
