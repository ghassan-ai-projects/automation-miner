"""Run lifecycle: create or resume the run handle, execute the graph, record failure.

A run directory and an initial ``running`` manifest exist before ingestion or
any provider call, so every failure — including budget exhaustion — is written
into the run that raised it, never merely the newest directory. A failed run
can be resumed: stages whose artifacts are already in ``trace/`` are reused,
so a failure at minute 14 does not cost the first 13 minutes again.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Literal

from automation_miner import ingest as ing
from automation_miner.artifacts.layout import RunLayout
from automation_miner.artifacts.workspace import Workspace, read_json, write_json
from automation_miner.constraints import normalize_constraint_params, render_constraints
from automation_miner.execution import RunExecutionContext, StageProgress
from automation_miner.graph.build import build_graph
from automation_miner.graph.failure import record_failure
from automation_miner.graph.state import MinerState
from automation_miner.models.client import MinerModel, RunScopedModel
from automation_miner.models.config import load_config
from automation_miner.prompts import PROMPT_VERSION
from automation_miner.schemas import AnalysisMode, InputQuality, RunBudget, RunManifest

MAX_ITERATIONS = 10
RESUMABLE = frozenset({"failed", "budget_exhausted", "running"})

__all__ = ["MAX_ITERATIONS", "RESUMABLE", "record_failure", "resume_run", "run_mine"]

Kind = Literal["idea", "file", "kb"]


@dataclass(frozen=True)
class RunRequest:
    """A validated description of what to mine; enough to start or resume a run."""

    kind: Kind
    value: str
    raw_constraints: str
    constraint_params: dict[str, str]
    requested_mode: AnalysisMode
    max_iterations: int
    profile: str

    @property
    def constraints(self) -> str:
        return render_constraints(self.raw_constraints, self.constraint_params)

    @property
    def preliminary_domain(self) -> str:
        if self.kind == "idea":
            return " ".join(self.value.split())[: ing.MAX_DOMAIN_CHARS] or "untitled-domain"
        return Path(self.value).stem or Path(self.value).name or f"untitled-{self.kind}"


def _request(
    idea: str | None, file: Path | None, kb: Path | None, constraints: str,
    constraint_params: dict[str, Any] | None, mode: str, max_iterations: int, profile: str,
) -> RunRequest:
    if sum(x is not None for x in (idea, file, kb)) != 1:
        raise ValueError("Provide exactly one of idea, file, or kb.")
    if not 1 <= max_iterations <= MAX_ITERATIONS:
        raise ValueError(f"max_iterations must be between 1 and {MAX_ITERATIONS}")
    try:
        requested_mode = AnalysisMode(mode)
    except ValueError as exc:
        raise ValueError("mode must be auto, operational, or strategy") from exc
    kind: Kind = "idea" if idea is not None else "file" if file is not None else "kb"
    value = idea if idea is not None else str(file if file is not None else kb)
    params = normalize_constraint_params(constraint_params)
    return RunRequest(kind, value, constraints, params, requested_mode, max_iterations, profile)


def _initial_state(
    request: RunRequest, workspace_path: Path, run_dir: Path, budget: RunBudget, created: str,
    resume: bool = False,
) -> dict[str, Any]:
    run = {
        "workspace": str(workspace_path), "run_dir": str(run_dir), "run_id": run_dir.name,
        "run_budget": budget.model_dump(mode="json"), "status": "running", "created": created,
        "start_ts": time.time(), "resume": resume, "layer_analyses": [], "drafts": [],
        "stage_seconds": {},
    }
    return {
        **run,
        "input_kind": request.kind,
        "input_value": request.value,
        "constraints": request.constraints,
        "policy_constraints": request.raw_constraints,
        "constraint_params": request.constraint_params,
        "max_iterations": request.max_iterations,
        "profile": request.profile,
        "requested_mode": request.requested_mode.value,
    }


def _fail(run_dir: Path, exc: BaseException, execution: RunExecutionContext) -> None:
    record_failure(run_dir, exc, execution)
    setattr(exc, "run_id", run_dir.name)
    setattr(exc, "run_dir", str(run_dir))


def _execute(
    model: MinerModel,
    workspace: Workspace,
    run_dir: Path,
    execution: RunExecutionContext,
    initial: dict[str, Any],
    preflight_callback: Callable[[InputQuality], None] | None,
) -> MinerState:
    try:
        graph = build_graph(
            RunScopedModel(model, execution), workspace, preflight_callback=preflight_callback
        )
        result: MinerState = graph.invoke(initial)
    except Exception as exc:
        _fail(run_dir, exc, execution)
        raise
    return result


def _budget(model: MinerModel) -> tuple[RunBudget, Exception | None]:
    """The configured budget, or the default plus the error that rejected it."""
    try:
        return RunBudget.model_validate(model.config.budget), None
    except Exception as exc:
        return RunBudget(), exc


def _manifest(
    request: RunRequest, model: MinerModel, run_dir: Path, budget: RunBudget
) -> RunManifest:
    try:
        models = model.routing_table()
    except Exception:
        models = {}
    domain = request.preliminary_domain
    strategy = request.requested_mode is AnalysisMode.STRATEGY
    return RunManifest(
        run_id=run_dir.name, domain=domain, domain_slug=ing.slugify(domain),
        constraints=request.constraints, raw_constraints=request.raw_constraints,
        constraint_params=request.constraint_params, source_kind=request.kind,
        source_value=request.value or "(empty input)",
        analysis_mode="strategy" if strategy else "operational",
        requested_mode=request.requested_mode.value, status="running", budget=budget,
        created=f"{datetime.now():%Y-%m-%dT%H:%M:%S}", max_iterations=request.max_iterations,
        profile=request.profile, config_source=model.config.source,
        prompt_version=PROMPT_VERSION, dry_run=model.dry_run, models=models,
    )


def _start(
    request: RunRequest,
    model: MinerModel,
    workspace: Workspace,
    progress_callback: Callable[[StageProgress], None] | None,
) -> tuple[Path, RunExecutionContext, RunManifest]:
    """Allocate the run directory and persist its ``running`` manifest first."""
    workspace.ensure()
    run_dir = workspace.new_run_dir(ing.slugify(request.preliminary_domain))
    budget, budget_error = _budget(model)
    execution = RunExecutionContext(run_dir.name, budget, on_stage=progress_callback)
    manifest = _manifest(request, model, run_dir, budget)
    try:
        write_json(RunLayout(run_dir).manifest, manifest)
        if budget_error is not None:
            raise budget_error
    except Exception as exc:
        _fail(run_dir, exc, execution)
        raise
    return run_dir, execution, manifest


def run_mine(
    *, workspace_path: Path, idea: str | None = None, file: Path | None = None,
    kb: Path | None = None, constraints: str = "", max_iterations: int = 2,
    profile: str = "default", dry_run: bool = False, mode: str = "auto",
    constraint_params: dict[str, Any] | None = None, model: MinerModel | None = None,
    preflight_callback: Callable[[InputQuality], None] | None = None,
    progress_callback: Callable[[StageProgress], None] | None = None,
) -> MinerState:
    """Run the full pipeline once. Exactly one of idea/file/kb is required."""
    request = _request(idea, file, kb, constraints, constraint_params, mode, max_iterations, profile)
    owns_model = model is None
    model = model or MinerModel(load_config(workspace_path, profile), dry_run=dry_run)
    workspace = Workspace(workspace_path)
    try:
        run_dir, execution, manifest = _start(request, model, workspace, progress_callback)
        initial = _initial_state(
            request, workspace_path, run_dir, execution.budget, manifest.created
        )
        return _execute(model, workspace, run_dir, execution, initial, preflight_callback)
    finally:
        if owns_model:
            model.close()


def _resumable(workspace_path: Path, run_id: str) -> tuple[RunLayout, RunManifest, RunRequest]:
    layout = RunLayout(Workspace(workspace_path).run_summary_path(run_id).parent)
    if not layout.manifest.is_file():
        raise ValueError(f"No run {run_id!r} in {workspace_path}")
    manifest = RunManifest.model_validate(read_json(layout.manifest))
    if manifest.status not in RESUMABLE:
        raise ValueError(f"Run {run_id!r} is {manifest.status}; only failed runs can resume")
    request = RunRequest(
        manifest.source_kind,
        manifest.source_value,
        manifest.raw_constraints,
        manifest.constraint_params,
        AnalysisMode(manifest.requested_mode),
        manifest.max_iterations,
        manifest.profile,
    )
    return layout, manifest, request


def resume_run(
    *,
    workspace_path: Path,
    run_id: str,
    dry_run: bool = False,
    model: MinerModel | None = None,
    progress_callback: Callable[[StageProgress], None] | None = None,
) -> MinerState:
    """Continue a failed or interrupted run, reusing every completed stage."""
    layout, manifest, request = _resumable(workspace_path, run_id)
    owns_model = model is None
    model = model or MinerModel(load_config(workspace_path, request.profile), dry_run=dry_run)
    try:
        budget = RunBudget.model_validate(model.config.budget)
        execution = RunExecutionContext(run_id, budget, on_stage=progress_callback)
        if layout.error.is_file():
            layout.error.replace(layout.root / "error.previous.json")
        write_json(layout.manifest, manifest.model_copy(update={"status": "running"}))
        initial = _initial_state(
            request, workspace_path, layout.root, budget, manifest.created, resume=True
        )
        return _execute(model, Workspace(workspace_path), layout.root, execution, initial, None)
    finally:
        if owns_model:
            model.close()
