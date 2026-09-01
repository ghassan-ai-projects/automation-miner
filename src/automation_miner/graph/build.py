"""LangGraph pipeline: ingest → domain_map → 5 layer analyses → 5 drafters
→ critique/refine loop → ICE scoring → rank + filters → publish.

Every node persists JSON artifacts into the run directory; artifacts are the
source of truth. Fan-out over the five layers uses langgraph's Send API.

Two structural changes from v3:

* **Each stage draws its own evidence.** Instead of re-sending one shared blob,
  a stage selects the chunks most relevant to its question within its own token
  budget. The critique loop builds its evidence pack once per opportunity rather
  than per round, which is where the old cost went: 163,523 prompt characters
  for a single 8-file dry run.
* **Critique and scoring run in parallel.** They were sequential over every
  opportunity — 10 opportunities x 2 rounds is ~40 serial HTTP calls, 7-20
  minutes of wall clock. AM-ids are reserved before fan-out, so ids stay stable
  and results are re-sorted deterministically.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Callable, Literal, cast

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from automation_miner import ingest as ing
from automation_miner.artifacts.briefs import render_brief, title_slug
from automation_miner.artifacts.publication import (
    mark_manifest_failed,
    mark_portfolio_failed,
    mark_summary_failed,
    promote_publication,
    quarantine_run_briefs,
    write_publication_journal,
)
from automation_miner.artifacts.registry import reindex_locked
from automation_miner.artifacts.reports import render_report, render_run_md, render_summary
from automation_miner.artifacts.workspace import (
    Workspace,
    read_json,
    workspace_transaction_lock,
    write_json,
    write_text,
)
from automation_miner.constraints import normalize_constraint_params, render_constraints
from automation_miner.context import (
    ContextBudget,
    EvidenceIndex,
    draft_query,
    layer_query,
    render_chunks,
)
from automation_miner.graph.loop import run_critique_loop
from automation_miner.graph.state import MinerState
from automation_miner.execution import BudgetExceeded, RunExecutionContext
from automation_miner.models.client import MinerModel, RunScopedModel
from automation_miner.models.config import load_config
from automation_miner.prompts import (
    DOMAIN_MAP_SYSTEM,
    DRAFTER_SYSTEM,
    INPUT_ASSESSMENT_SYSTEM,
    LAYER_ANALYST_SYSTEM,
    PORTFOLIO_PLANNER_SYSTEM,
    PROMPT_VERSION,
    SCORER_SYSTEM,
    candidate_draft_prompt,
    domain_map_prompt,
    input_assessment_prompt,
    layer_analysis_prompt,
    portfolio_plan_prompt,
    score_prompt,
)
from automation_miner.readers import build_registry
from automation_miner.schemas import (
    LAYER_ORDER,
    AnalysisMode,
    CandidatePortfolio,
    Chunk,
    ContextPacket,
    DomainMap,
    ICEScore,
    InputAssessment,
    Layer,
    LayerAnalysis,
    Opportunity,
    OpportunityCandidate,
    OpportunityDraft,
    InputQuality,
    RunManifest,
    RunBudget,
    StageFailure,
    Tier,
)
from automation_miner.scoring import (
    apply_constraint_overrides,
    apply_portfolio_policy,
    compute_ice,
    parse_constraint_policy,
    portfolio_stats,
    published,
    validate_coherence,
)

MAX_ITERATIONS = 10
LOGGER = logging.getLogger(__name__)


def build_graph(
    model: MinerModel | RunScopedModel,
    workspace: Workspace,
    budget: ContextBudget | None = None,
    preflight_callback: Callable[[InputQuality], None] | None = None,
) -> Any:
    """Build the compiled mining pipeline for one model client + workspace."""
    budget = budget or ContextBudget.from_config(model.config.context)

    def _mark_stage(stage: str) -> None:
        execution = getattr(model, "execution", None)
        if execution is not None:
            execution.set_stage(stage)
            execution.remaining_seconds()

    def _index(state: MinerState) -> EvidenceIndex:
        chunks = state["context"].get("chunks", [])
        if not isinstance(chunks, list):
            raise ValueError("context chunks must be a list")
        return EvidenceIndex([Chunk.model_validate(chunk) for chunk in chunks])

    def _timed(state: MinerState, stage: str, started: float) -> dict[str, float]:
        elapsed = round(time.time() - started, 2)
        execution = getattr(model, "execution", None)
        if execution is not None:
            execution.record_stage(stage, elapsed)
        return {**state.get("stage_seconds", {}), stage: elapsed}

    def ingest_node(state: MinerState) -> dict[str, Any]:
        _mark_stage("ingest")
        started = time.time()
        kind, value = state["input_kind"], state["input_value"]
        registry = build_registry(model.config.readers)
        cache_root = workspace.cache_dir
        if kind == "idea":
            packet = ing.ingest_idea(
                value,
                state["constraints"],
                budget,
                preflight_callback=preflight_callback,
            )
        elif kind == "file":
            packet = ing.ingest_file(
                Path(value),
                state["constraints"],
                model,
                budget,
                registry,
                cache_root,
                preflight_callback,
            )
        else:
            packet = ing.ingest_kb(
                Path(value),
                state["constraints"],
                model,
                budget,
                registry,
                cache_root,
                preflight_callback,
            )
        packet = packet.model_copy(
            update={
                "constraint_params": state.get("constraint_params", {}),
                "raw_constraints": state.get("policy_constraints", ""),
            }
        )
        run_dir = Path(state["run_dir"])
        write_json(run_dir / "context.json", packet)
        return {
            "context": packet.model_dump(mode="json"),
            "run_dir": str(run_dir),
            "run_id": run_dir.name,
            "stage_seconds": _timed(state, "ingest", started),
        }

    def domain_map_node(state: MinerState) -> dict[str, Any]:
        _mark_stage("domain_map")
        started = time.time()
        ctx = ContextPacket.model_validate(state["context"])
        assessment = InputAssessment.model_validate(state["input_assessment"])
        requested = AnalysisMode(state.get("requested_mode", AnalysisMode.AUTO))
        mode = (
            AnalysisMode(assessment.recommended_mode)
            if requested is AnalysisMode.AUTO
            else requested
        )
        result = model.call_json(
            "mapper",
            DOMAIN_MAP_SYSTEM,
            domain_map_prompt(
                ctx.domain,
                ctx.constraints,
                ctx.overview,
                mode.value,
                assessment.model_dump_json(indent=2),
            ),
            DomainMap,
        )
        result = result.model_copy(update={"analysis_mode": mode.value})
        write_json(Path(state["run_dir"]) / "domain_map.json", result)
        return {
            "domain_map": result.model_dump(mode="json"),
            "analysis_mode": mode.value,
            "stage_seconds": _timed(state, "domain_map", started),
        }

    def assess_input_node(state: MinerState) -> dict[str, Any]:
        _mark_stage("input_assessment")
        started = time.time()
        ctx = ContextPacket.model_validate(state["context"])
        result = model.call_json(
            "mapper",
            INPUT_ASSESSMENT_SYSTEM,
            input_assessment_prompt(ctx.overview, state.get("requested_mode", "auto")),
            InputAssessment,
        )
        write_json(Path(state["run_dir"]) / "input_assessment.json", result)
        return {
            "input_assessment": result.model_dump(mode="json"),
            "stage_seconds": _timed(state, "input_assessment", started),
        }

    def fanout_layers(state: MinerState) -> list[Send]:
        shared = {
            "context": state["context"],
            "domain_map": state["domain_map"],
            "run_dir": state["run_dir"],
            "constraints": state["constraints"],
            "analysis_mode": state["analysis_mode"],
        }
        return [Send("analyze_layer", {**shared, "layer": layer.value}) for layer in LAYER_ORDER]

    def analyze_layer_node(state: MinerState) -> dict[str, Any]:
        _mark_stage("layer_analysis")
        started = time.time()
        ctx = ContextPacket.model_validate(state["context"])
        layer = Layer(state["layer"])
        domain_map = DomainMap.model_validate(state["domain_map"])
        selected = _index(state).select(
            layer_query(layer, ctx.domain, domain_map.manual_friction),
            budget.layer_tokens,
        )
        evidence = render_chunks(
            selected,
            header=(
                "Domain map:\n<untrusted-artifact>\n"
                f"{escape(domain_map.model_dump_json(indent=2), quote=False)}\n"
                "</untrusted-artifact>"
            ),
        )
        result = model.call_json(
            "layer_analyst",
            LAYER_ANALYST_SYSTEM,
            layer_analysis_prompt(
                layer.value,
                ctx.domain,
                ctx.constraints,
                evidence,
                state["analysis_mode"],
            ),
            LayerAnalysis,
        )
        result = result.model_copy(update={"layer": layer})
        write_json(Path(state["run_dir"]) / "layers" / f"{layer.value}.json", result)
        execution = getattr(model, "execution", None)
        if execution is not None:
            execution.record_stage("layer_analysis", time.time() - started)
            execution.remaining_seconds()
        return {"layer_analyses": [result.model_dump(mode="json")]}

    def _prior_ideas(domain_slug: str) -> list[dict[str, Any]]:
        path = workspace.root / "registry.json"
        if not path.is_file():
            return []
        try:
            entries = read_json(path).get("entries", [])
        except (OSError, ValueError):
            return []
        same_domain = [entry for entry in entries if entry.get("d") == domain_slug]
        selected = same_domain or entries
        return [
            {
                "id": entry.get("i", ""),
                "title": entry.get("t", ""),
                "layer": entry.get("l", ""),
                "domain": entry.get("d", ""),
            }
            for entry in selected[-50:]
        ]

    def plan_portfolio_node(state: MinerState) -> dict[str, Any]:
        _mark_stage("plan_portfolio")
        started = time.time()
        ctx = ContextPacket.model_validate(state["context"])
        analyses = sorted(
            state["layer_analyses"], key=lambda a: LAYER_ORDER.index(Layer(str(a["layer"])))
        )
        result = model.call_json(
            "drafter",
            PORTFOLIO_PLANNER_SYSTEM,
            portfolio_plan_prompt(
                _json(state["domain_map"]),
                _json(analyses),
                ctx.overview,
                ctx.constraints,
                _json(_prior_ideas(ctx.domain_slug)),
            ),
            CandidatePortfolio,
        )
        write_json(Path(state["run_dir"]) / "candidate_portfolio.json", result)
        return {
            "candidates": [candidate.model_dump(mode="json") for candidate in result.candidates],
            "candidate_portfolio": result.model_dump(mode="json"),
            "stage_seconds": _timed(state, "plan_portfolio", started),
        }

    def fanout_candidates(state: MinerState) -> list[Send]:
        shared = {
            "context": state["context"],
            "domain_map": state["domain_map"],
            "run_dir": state["run_dir"],
            "constraints": state["constraints"],
            "analysis_mode": state["analysis_mode"],
            "candidate_portfolio": state["candidate_portfolio"],
        }
        return [
            Send("draft_candidate", {**shared, "candidate": candidate})
            for candidate in state["candidates"]
        ]

    def draft_candidate_node(state: MinerState) -> dict[str, Any]:
        _mark_stage("draft_opportunities")
        started = time.time()
        ctx = ContextPacket.model_validate(state["context"])
        candidate = OpportunityCandidate.model_validate(state["candidate"])
        selected = _index(state).select(
            draft_query(
                candidate.layer,
                [candidate.title, candidate.value_thesis, candidate.differentiation],
                ctx.domain,
            ),
            budget.draft_tokens,
            pinned=candidate.evidence_refs,
        )
        draft = model.call_json(
            "drafter",
            DRAFTER_SYSTEM,
            candidate_draft_prompt(
                candidate.model_dump_json(indent=2),
                _json(state["candidate_portfolio"]),
                render_chunks(selected),
                ctx.constraints,
                _json(state["domain_map"]),
                state["analysis_mode"],
            ),
            OpportunityDraft,
        )
        draft = draft.model_copy(update={"layer": candidate.layer})
        write_json(
            Path(state["run_dir"])
            / "drafts"
            / f"candidate-{title_slug(candidate.title)}.json",
            draft,
        )
        execution = getattr(model, "execution", None)
        if execution is not None:
            execution.record_stage("draft_opportunities", time.time() - started)
            execution.remaining_seconds()
        return {"drafts": [draft.model_dump(mode="json")]}

    def critique_refine_node(state: MinerState) -> dict[str, Any]:
        _mark_stage("critique_refine")
        started = time.time()
        run_dir = Path(state["run_dir"])
        ctx = ContextPacket.model_validate(state["context"])
        index = _index(state)
        ordered = sorted(
            state["drafts"],
            key=lambda d: (LAYER_ORDER.index(Layer(str(d["layer"]))), str(d["title"])),
        )
        reserved = workspace.reserve_am_numbers(len(ordered))
        titles = [str(d["title"]) for d in ordered]

        def process(position: int) -> dict[str, Any]:
            raw = ordered[position]
            am_id = f"AM-{reserved[position]:03d}"
            draft = OpportunityDraft.model_validate(raw)
            others = [t for i, t in enumerate(titles) if i != position]
            # Built once per opportunity, reused across every critique round.
            evidence = render_chunks(
                index.select(
                    draft_query(draft.layer, [draft.title, draft.problem], ctx.domain),
                    budget.critique_tokens,
                    pinned=draft.evidence_refs,
                )
            )
            final, history = run_critique_loop(
                model,
                draft,
                others,
                state["max_iterations"],
                evidence=evidence,
                constraints=ctx.constraints,
            )
            for entry in history:
                write_json(run_dir / "drafts" / f"{am_id}.v{entry['version']}.json", entry)
            return {
                "am_id": am_id,
                "domain": ctx.domain,
                "domain_slug": ctx.domain_slug,
                "draft": final.model_dump(mode="json"),
                "critique_overall": next(
                    entry["overall"] for entry in history if entry["selected"]
                ),
                "quality_gate_reasons": next(
                    entry["gate_reasons"] for entry in history if entry["selected"]
                ),
                "iterations": len(history),
            }

        refined = _parallel_map(
            process, range(len(ordered)), model.config.workers_for("critique")
        )
        return {"refined": refined, "stage_seconds": _timed(state, "critique_refine", started)}

    def score_node(state: MinerState) -> dict[str, Any]:
        _mark_stage("score")
        started = time.time()
        constraints = state["constraints"]
        policy = parse_constraint_policy(
            state.get("policy_constraints", constraints), state.get("constraint_params")
        )
        known_ids = ContextPacket.model_validate(state["context"]).chunk_ids()

        def process(item: dict[str, Any]) -> dict[str, Any]:
            draft = OpportunityDraft.model_validate(item["draft"])
            source_risk = draft.risk_level
            proposed = model.call_json(
                "scorer",
                SCORER_SYSTEM,
                score_prompt(draft.model_dump_json(indent=2), constraints),
                ICEScore,
            )
            unresolved = [ref for ref in draft.evidence_refs if ref not in known_ids]
            score, calibration = validate_coherence(proposed, draft, unresolved)
            score, risk, applied = apply_constraint_overrides(score, draft.risk_level, policy)
            draft = draft.model_copy(update={"risk_level": risk})
            ice = compute_ice(score.impact, score.confidence, score.ease)
            return Opportunity(
                am_id=item["am_id"],
                domain=item["domain"],
                domain_slug=item["domain_slug"],
                draft=draft,
                score=score,
                ice=ice,
                tier=Tier.for_ice(ice),
                critique_overall=item["critique_overall"],
                iterations=item["iterations"],
                overrides_applied=applied,
                calibration=calibration,
                unresolved_refs=unresolved,
                quality_gate_reasons=item["quality_gate_reasons"],
                source_risk_level=source_risk,
            ).model_dump(mode="json")

        opportunities = _parallel_map(
            process, state["refined"], model.config.workers_for("score")
        )
        write_json(
            Path(state["run_dir"]) / "scores.json",
            {"opportunities": opportunities},
        )
        return {
            "opportunities": opportunities,
            "stage_seconds": _timed(state, "score", started),
        }

    def rank_filter_node(state: MinerState) -> dict[str, Any]:
        _mark_stage("rank_filter")
        started = time.time()
        ranked = apply_portfolio_policy(
            [Opportunity.model_validate(o) for o in state["opportunities"]],
            state.get("policy_constraints", state["constraints"]),
            state.get("constraint_params"),
        )
        payload = [o.model_dump(mode="json") for o in ranked]
        write_json(
            Path(state["run_dir"]) / "ranked.json",
            {
                "opportunities": payload,
                "stats": portfolio_stats(ranked).model_dump(mode="json"),
            },
        )
        return {
            "opportunities": payload,
            "stage_seconds": _timed(state, "rank_filter", started),
        }

    def publish_node(state: MinerState) -> dict[str, Any]:
        _mark_stage("publish")
        started = time.time()
        run_dir = Path(state["run_dir"])
        ctx = ContextPacket.model_validate(state["context"])
        ranked = [Opportunity.model_validate(o) for o in state["opportunities"]]
        live = published(ranked)
        stats = portfolio_stats(ranked)

        staging_dir = run_dir / "publication" / ctx.domain_slug
        opp_dir = workspace.opps_dir / ctx.domain_slug
        brief_paths: dict[str, str] = {}
        publication_files: list[dict[str, str]] = []
        for opp in live:
            fname = f"{opp.am_id}-{title_slug(opp.draft.title)}.md"
            staged_path = staging_dir / fname
            target_path = opp_dir / fname
            write_text(
                staged_path,
                render_brief(opp, state["run_id"], input_quality=ctx.input_quality),
            )
            brief_paths[opp.am_id] = str(target_path)
            publication_files.append(
                {
                    "staged": str(staged_path.relative_to(run_dir)),
                    "target": str(target_path.relative_to(workspace.root)),
                }
            )

        write_json(
            run_dir / "opportunities.json",
            {
                "run_id": state["run_id"],
                "domain": ctx.domain,
                "opportunities": [o.model_dump(mode="json") for o in ranked],
                "stats": stats.model_dump(mode="json"),
                "filters": stats.filters,
            },
        )

        usage = model.usage.snapshot()
        run_budget = RunBudget.model_validate(state["run_budget"])
        duration = time.time() - state.get("start_ts", time.time())
        stage_seconds = _timed(state, "publish", started)
        execution = getattr(model, "execution", None)
        if execution is not None:
            stage_seconds = {**execution.snapshot().stage_seconds, **stage_seconds}

        manifest = RunManifest(
            run_id=state["run_id"],
            domain=ctx.domain,
            domain_slug=ctx.domain_slug,
            constraints=ctx.constraints,
            raw_constraints=ctx.raw_constraints,
            constraint_params=ctx.constraint_params,
            source_kind=ctx.source_kind,
            source_value=state["input_value"],
            analysis_mode=state["analysis_mode"],
            requested_mode=state["requested_mode"],
            created=state["created"],
            finished=f"{datetime.now():%Y-%m-%dT%H:%M:%S}",
            duration_seconds=round(duration, 2),
            max_iterations=state["max_iterations"],
            profile=state.get("profile", "default"),
            config_source=model.config.source,
            prompt_version=PROMPT_VERSION,
            dry_run=model.dry_run,
            models=model.routing_table(),
            opportunities=[o.am_id for o in live],
            filtered=[o.am_id for o in ranked if not o.published],
            stage_seconds=stage_seconds,
            usage=usage,
            context=ctx.stats,
            input_quality=ctx.input_quality,
            retained_quality=ctx.retained_quality,
            status="completed",
            publication_status="pending",
            budget=run_budget,
        )
        write_json(run_dir / "run.json", manifest)
        write_publication_journal(run_dir, "staged", files=publication_files)
        promote_publication(run_dir, workspace.root, publication_files)

        summary = render_summary(
            run_id=state["run_id"],
            context=ctx,
            ranked=ranked,
            stats=stats,
            usage=usage,
            created=state["created"],
            duration_seconds=round(duration, 2),
            dry_run=model.dry_run,
            brief_paths=brief_paths,
            status="completed",
            publication_status="pending",
            budget=run_budget,
        )
        write_json(run_dir / "summary.json", summary)
        write_text(
            run_dir / "run.md",
            render_run_md(
                state["run_id"],
                ctx,
                DomainMap.model_validate(state["domain_map"]),
                [LayerAnalysis.model_validate(a) for a in state["layer_analyses"]],
                ranked,
                stats,
                usage,
            ),
        )
        write_text(
            run_dir / "report.md",
            render_report(
                run_id=state["run_id"],
                context=ctx,
                ranked=ranked,
                stats=stats,
                usage=usage,
                models=model.routing_table(),
                status="completed",
                publication_status="pending",
                budget=run_budget,
            ),
        )
        write_publication_journal(run_dir, "views_written", files=publication_files)
        if execution is not None:
            execution.remaining_seconds()
        with workspace_transaction_lock(workspace.root):
            write_json(
                run_dir / "run.json",
                manifest.model_copy(
                    update={
                        "finished": f"{datetime.now():%Y-%m-%dT%H:%M:%S}",
                        "publication_status": "complete",
                    }
                ),
            )
            write_publication_journal(run_dir, "manifest_complete", files=publication_files)
            from automation_miner.artifacts.publication import complete_publication_views

            complete_publication_views(run_dir)
            reindex_locked(workspace.root)
            write_publication_journal(run_dir, "complete", files=publication_files)
        if execution is not None:
            execution.remaining_seconds()
        return {
            "report_path": str(run_dir / "report.md"),
            "summary_path": str(run_dir / "summary.json"),
            "status": "completed",
            "stage_seconds": stage_seconds,
        }

    graph = StateGraph(MinerState)
    graph.add_node("ingest", ingest_node)
    graph.add_node("assess_input", assess_input_node)
    graph.add_node("domain_map", domain_map_node)
    graph.add_node("analyze_layer", analyze_layer_node)
    graph.add_node("plan_portfolio", plan_portfolio_node)
    graph.add_node("draft_candidate", draft_candidate_node)
    graph.add_node("critique_refine", critique_refine_node)
    graph.add_node("score", score_node)
    graph.add_node("rank_filter", rank_filter_node)
    graph.add_node("publish", publish_node)

    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "assess_input")
    graph.add_edge("assess_input", "domain_map")
    graph.add_conditional_edges("domain_map", fanout_layers, ["analyze_layer"])
    graph.add_edge("analyze_layer", "plan_portfolio")
    graph.add_conditional_edges("plan_portfolio", fanout_candidates, ["draft_candidate"])
    graph.add_edge("draft_candidate", "critique_refine")
    graph.add_edge("critique_refine", "score")
    graph.add_edge("score", "rank_filter")
    graph.add_edge("rank_filter", "publish")
    graph.add_edge("publish", END)
    return graph.compile()


def _parallel_map(
    fn: Callable[[Any], dict[str, Any]], items: Any, workers: int
) -> list[dict[str, Any]]:
    """Map over items, preserving input order so runs stay reproducible."""
    materialized = list(items)
    if workers <= 1 or len(materialized) <= 1:
        return [fn(item) for item in materialized]
    with ThreadPoolExecutor(max_workers=min(workers, len(materialized))) as pool:
        return list(pool.map(fn, materialized))


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, default=str)


def run_mine(
    *,
    workspace_path: Path,
    idea: str | None = None,
    file: Path | None = None,
    kb: Path | None = None,
    constraints: str = "",
    max_iterations: int = 2,
    profile: str = "default",
    dry_run: bool = False,
    mode: str = "auto",
    constraint_params: dict[str, Any] | None = None,
    model: MinerModel | None = None,
    preflight_callback: Callable[[InputQuality], None] | None = None,
) -> MinerState:
    """Run the full pipeline once. Exactly one of idea/file/kb is required."""
    provided = [x is not None for x in (idea, file, kb)]
    if sum(provided) != 1:
        raise ValueError("Provide exactly one of idea, file, or kb.")
    if not 1 <= max_iterations <= MAX_ITERATIONS:
        raise ValueError(f"max_iterations must be between 1 and {MAX_ITERATIONS}")
    try:
        requested_mode = AnalysisMode(mode)
    except ValueError as exc:
        raise ValueError("mode must be auto, operational, or strategy") from exc
    normalized_params = normalize_constraint_params(constraint_params)
    effective_constraints = render_constraints(constraints, normalized_params)
    kind: Literal["idea", "file", "kb"]
    value: str
    if idea is not None:
        kind, value = "idea", idea
    elif file is not None:
        kind, value = "file", str(file)
    else:
        kind, value = "kb", str(kb)

    owns_model = model is None
    if model is None:
        model = MinerModel(load_config(workspace_path, profile), dry_run=dry_run)
    workspace = Workspace(workspace_path)
    run_budget = RunBudget()
    if idea is not None:
        preliminary_domain = " ".join(idea.split())[: ing.MAX_DOMAIN_CHARS] or "untitled-domain"
    elif file is not None:
        preliminary_domain = file.stem or "untitled-file"
    else:
        preliminary_domain = kb.name if kb is not None else "untitled-kb"
    preliminary_slug = ing.slugify(preliminary_domain)
    initial_analysis_mode = cast(
        Literal["operational", "strategy"],
        requested_mode.value
        if requested_mode is not AnalysisMode.AUTO
        else AnalysisMode.OPERATIONAL.value,
    )
    try:
        workspace.ensure()
        run_dir = workspace.new_run_dir(preliminary_slug)
        run_id = run_dir.name
        created = f"{datetime.now():%Y-%m-%dT%H:%M:%S}"
        budget_error: Exception | None = None
        try:
            run_budget = RunBudget.model_validate(model.config.budget)
        except Exception as exc:
            budget_error = exc
        execution = RunExecutionContext(run_id, run_budget)
        scoped_model = RunScopedModel(model, execution)
        source_value = value or "(empty input)"
        models: dict[str, str] = {}
        try:
            models = model.routing_table()
        except Exception:
            pass
        initial_manifest = RunManifest(
            run_id=run_id,
            domain=preliminary_domain,
            domain_slug=preliminary_slug,
            constraints=effective_constraints,
            raw_constraints=constraints,
            constraint_params=normalized_params,
            source_kind=kind,
            source_value=source_value,
            analysis_mode=initial_analysis_mode,
            requested_mode=requested_mode.value,
            status="running",
            budget=run_budget,
            created=created,
            max_iterations=max_iterations,
            profile=profile,
            config_source=model.config.source,
            prompt_version=PROMPT_VERSION,
            dry_run=model.dry_run,
            models=models,
        )
        try:
            write_json(run_dir / "run.json", initial_manifest)
        except Exception as exc:
            _record_failure(run_dir, exc, execution)
            setattr(exc, "run_id", run_id)
            setattr(exc, "run_dir", str(run_dir))
            raise
        if budget_error is not None:
            _record_failure(run_dir, budget_error, execution)
            setattr(budget_error, "run_id", run_id)
            setattr(budget_error, "run_dir", str(run_dir))
            raise budget_error
        initial: dict[str, Any] = {
            "workspace": str(workspace_path),
            "run_dir": str(run_dir),
            "run_id": run_id,
            "input_kind": kind,
            "input_value": value,
            "constraints": effective_constraints,
            "policy_constraints": constraints,
            "constraint_params": normalized_params,
            "run_budget": run_budget.model_dump(mode="json"),
            "status": "running",
            "max_iterations": max_iterations,
            "profile": profile,
            "requested_mode": requested_mode.value,
            "created": created,
            "start_ts": time.time(),
            "layer_analyses": [],
            "drafts": [],
            "stage_seconds": {},
        }
        try:
            graph = build_graph(scoped_model, workspace, preflight_callback=preflight_callback)
            result: MinerState = graph.invoke(initial)
        except Exception as exc:
            _record_failure(run_dir, exc, execution)
            setattr(exc, "run_id", run_id)
            setattr(exc, "run_dir", str(run_dir))
            raise
        return result
    finally:
        if owns_model:
            model.close()


def _record_failure(
    run_dir: Path, exc: BaseException, execution: RunExecutionContext
) -> None:
    """Persist terminal failure state into the exact run that raised."""
    snapshot = execution.snapshot()
    status: Literal["failed", "budget_exhausted"] = (
        "budget_exhausted" if isinstance(exc, BudgetExceeded) else "failed"
    )
    quarantined: list[str] = []
    try:
        with workspace_transaction_lock(run_dir.parent.parent):
            quarantined = quarantine_run_briefs(run_dir.parent.parent, run_dir)
            reindex_locked(run_dir.parent.parent)
    except Exception:
        LOGGER.exception(
            "Unable to quarantine or rebuild registry while recording failed run %s at %s",
            run_dir.name,
            run_dir,
        )
    if (run_dir / "publication.json").is_file():
        try:
            write_publication_journal(run_dir, "quarantined")
        except Exception:
            LOGGER.exception(
                "Unable to close publication journal for failed run %s at %s",
                run_dir.name,
                run_dir,
            )
    written = sorted(str(p.relative_to(run_dir)) for p in run_dir.rglob("*") if p.is_file())
    failure = StageFailure(
        run_id=run_dir.name,
        stage=snapshot.stage,
        error_type=type(exc).__name__,
        error=str(exc)[:2_000],
        created=f"{datetime.now():%Y-%m-%dT%H:%M:%S}",
        status=status,
        budget=execution.budget,
        budget_limit=getattr(exc, "limit", ""),
        observed_attempts=snapshot.attempts,
        observed_tokens=snapshot.tokens,
        stage_seconds=snapshot.stage_seconds,
        usage=execution.usage.snapshot(),
        artifacts_written=written,
        quarantined_artifacts=quarantined,
    )
    try:
        write_json(run_dir / "error.json", failure)
    except Exception:
        LOGGER.exception(
            "Unable to persist failure artifact for run %s at %s",
            run_dir.name,
            run_dir,
        )

    manifest_path = run_dir / "run.json"
    try:
        raw_manifest = read_json(manifest_path) if manifest_path.is_file() else {}
    except (OSError, ValueError):
        LOGGER.exception("Unable to read manifest while recording failed run %s at %s", run_dir.name, run_dir)
        raw_manifest = {}
    manifest_data = raw_manifest if isinstance(raw_manifest, dict) else {}
    if manifest_data:
        mark_manifest_failed(manifest_data, status)
        manifest_data.update(
            {
                "duration_seconds": snapshot.elapsed_seconds,
                "usage": execution.usage.snapshot().model_dump(mode="json"),
                "stage_seconds": snapshot.stage_seconds,
            }
        )
        try:
            write_json(manifest_path, manifest_data)
        except Exception:
            LOGGER.exception(
                "Unable to update terminal manifest for run %s at %s", run_dir.name, run_dir
            )

    summary_path = run_dir / "summary.json"
    try:
        summary = read_json(summary_path) if summary_path.is_file() else _failure_summary(
            run_dir, manifest_data, status, execution, snapshot.elapsed_seconds, exc
        )
        if isinstance(summary, dict):
            mark_summary_failed(summary, status)
            summary.update(
                {
                    "duration_seconds": snapshot.elapsed_seconds,
                    "usage": execution.usage.snapshot().model_dump(mode="json"),
                }
            )
            write_json(summary_path, summary)
    except Exception:
        LOGGER.exception(
            "Unable to persist failure summary for run %s at %s", run_dir.name, run_dir
        )

    portfolio_path = run_dir / "opportunities.json"
    try:
        portfolio = read_json(portfolio_path) if portfolio_path.is_file() else {}
        if isinstance(portfolio, dict):
            mark_portfolio_failed(portfolio, status)
            write_json(portfolio_path, portfolio)
    except Exception:
        LOGGER.exception(
            "Unable to persist failure portfolio for run %s at %s", run_dir.name, run_dir
        )

    report_path = run_dir / "report.md"
    try:
        domain = str(manifest_data.get("domain", run_dir.name))
        report = (
            f"# Automation Mining Report — {domain}\n\n"
            f"> **Run:** `{run_dir.name}`  \n"
            f"> **Status:** {status}  \n"
            "> **Publication:** pending  \n"
            "> **Published opportunities:** 0  \n\n"
            "## Failure\n\n"
            f"- **Stage:** {snapshot.stage}\n"
            f"- **Error:** {type(exc).__name__}: {str(exc)[:2_000]}\n"
            "- **Details:** see `error.json` and `run.json`.\n"
        )
        write_text(report_path, report)
    except Exception:
        LOGGER.exception(
            "Unable to persist failure report for run %s at %s", run_dir.name, run_dir
        )


def _failure_summary(
    run_dir: Path,
    manifest: dict[str, Any],
    status: str,
    execution: RunExecutionContext,
    duration: float,
    exc: BaseException,
) -> dict[str, Any]:
    """Create a valid minimal summary when failure precedes normal rendering."""
    return {
        "run_id": run_dir.name,
        "domain": str(manifest.get("domain", run_dir.name)),
        "domain_slug": str(manifest.get("domain_slug", "unknown")),
        "constraints": str(manifest.get("constraints", "")),
        "raw_constraints": str(manifest.get("raw_constraints", "")),
        "constraint_params": manifest.get("constraint_params", {}),
        "created": str(manifest.get("created", "")),
        "status": status,
        "publication_status": "pending",
        "budget": execution.budget.model_dump(mode="json"),
        "duration_seconds": duration,
        "dry_run": bool(manifest.get("dry_run", False)),
        "stats": {
            "total": 0,
            "published": 0,
            "filtered": 0,
            "by_layer": {},
            "by_tier": {},
            "avg_ice": 0.0,
            "median_ice": 0.0,
            "top_ice": 0,
            "top_id": "",
            "filters": {},
        },
        "usage": execution.usage.snapshot().model_dump(mode="json"),
        "opportunities": [],
        "notes": [f"{type(exc).__name__}: {str(exc)[:2_000]}", "See error.json for details."],
    }
