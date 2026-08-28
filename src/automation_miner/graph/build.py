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
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from automation_miner import ingest as ing
from automation_miner.artifacts.briefs import render_brief, title_slug
from automation_miner.artifacts.registry import reindex
from automation_miner.artifacts.reports import render_report, render_run_md, render_summary
from automation_miner.artifacts.workspace import Workspace, read_json, write_json, write_text
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
from automation_miner.models.client import MinerModel
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


def build_graph(
    model: MinerModel,
    workspace: Workspace,
    budget: ContextBudget | None = None,
    preflight_callback: Callable[[InputQuality], None] | None = None,
) -> Any:
    """Build the compiled mining pipeline for one model client + workspace."""
    budget = budget or ContextBudget.from_config(model.config.context)

    def _index(state: MinerState) -> EvidenceIndex:
        return EvidenceIndex([Chunk.model_validate(c) for c in state["context"]["chunks"]])

    def _timed(state: MinerState, stage: str, started: float) -> dict[str, float]:
        return {**state.get("stage_seconds", {}), stage: round(time.time() - started, 2)}

    def ingest_node(state: MinerState) -> dict[str, Any]:
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
            update={"constraint_params": state.get("constraint_params", {})}
        )
        run_dir = workspace.new_run_dir(packet.domain_slug)
        write_json(run_dir / "context.json", packet)
        return {
            "context": packet.model_dump(mode="json"),
            "run_dir": str(run_dir),
            "run_id": run_dir.name,
            "stage_seconds": _timed(state, "ingest", started),
        }

    def domain_map_node(state: MinerState) -> dict[str, Any]:
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
        ctx = ContextPacket.model_validate(state["context"])
        layer = Layer(state["layer"])
        domain_map = DomainMap.model_validate(state["domain_map"])
        selected = _index(state).select(
            layer_query(layer, ctx.domain, domain_map.manual_friction),
            budget.layer_tokens,
        )
        evidence = render_chunks(
            selected, header=f"Domain map:\n{domain_map.model_dump_json(indent=2)}"
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
        started = time.time()
        ctx = ContextPacket.model_validate(state["context"])
        analyses = sorted(
            state["layer_analyses"], key=lambda a: LAYER_ORDER.index(Layer(a["layer"]))
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
        return {"drafts": [draft.model_dump(mode="json")]}

    def critique_refine_node(state: MinerState) -> dict[str, Any]:
        started = time.time()
        run_dir = Path(state["run_dir"])
        ctx = ContextPacket.model_validate(state["context"])
        index = _index(state)
        ordered = sorted(
            state["drafts"],
            key=lambda d: (LAYER_ORDER.index(Layer(d["layer"])), d["title"]),
        )
        reserved = workspace.reserve_am_numbers(len(ordered))
        titles = [d["title"] for d in ordered]

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
        started = time.time()
        constraints = state["constraints"]
        policy = parse_constraint_policy(constraints)
        known_ids = ContextPacket.model_validate(state["context"]).chunk_ids()

        def process(item: dict[str, Any]) -> dict[str, Any]:
            draft = OpportunityDraft.model_validate(item["draft"])
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
        started = time.time()
        ranked = apply_portfolio_policy(
            [Opportunity.model_validate(o) for o in state["opportunities"]],
            state["constraints"],
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
        started = time.time()
        run_dir = Path(state["run_dir"])
        ctx = ContextPacket.model_validate(state["context"])
        ranked = [Opportunity.model_validate(o) for o in state["opportunities"]]
        live = published(ranked)
        stats = portfolio_stats(ranked)

        opp_dir = workspace.opp_dir(ctx.domain_slug)
        brief_paths: dict[str, str] = {}
        for opp in live:
            fname = f"{opp.am_id}-{title_slug(opp.draft.title)}.md"
            write_text(opp_dir / fname, render_brief(opp, state["run_id"]))
            brief_paths[opp.am_id] = str(opp_dir / fname)

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
        duration = time.time() - state.get("start_ts", time.time())
        stage_seconds = _timed(state, "publish", started)

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
            ),
        )

        manifest = RunManifest(
            run_id=state["run_id"],
            domain=ctx.domain,
            domain_slug=ctx.domain_slug,
            constraints=ctx.constraints,
            constraint_params=ctx.constraint_params,
            source_kind=ctx.source_kind,
            source_value=state["input_value"],
            analysis_mode=state["analysis_mode"],
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
        )
        write_json(run_dir / "run.json", manifest)
        reindex(workspace.root)
        return {
            "report_path": str(run_dir / "report.md"),
            "summary_path": str(run_dir / "summary.json"),
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
    try:
        workspace.ensure()
        initial: dict[str, Any] = {
            "workspace": str(workspace_path),
            "input_kind": kind,
            "input_value": value,
            "constraints": effective_constraints,
            "constraint_params": normalized_params,
            "max_iterations": max_iterations,
            "profile": profile,
            "requested_mode": requested_mode.value,
            "created": f"{datetime.now():%Y-%m-%dT%H:%M:%S}",
            "start_ts": time.time(),
            "layer_analyses": [],
            "drafts": [],
            "stage_seconds": {},
        }
        graph = build_graph(model, workspace, preflight_callback=preflight_callback)
        try:
            result: MinerState = graph.invoke(initial)  # type: ignore[assignment]
        except Exception as exc:
            _record_failure(workspace, exc)
            raise
        return result
    finally:
        if owns_model:
            model.close()


def _record_failure(workspace: Workspace, exc: BaseException) -> None:
    """Write error.json into the newest run directory.

    Without this a failed stage left only ``context.json`` behind, with nothing
    explaining what broke — which contradicts artifacts being the source of truth.
    """
    try:
        runs = sorted(
            (p for p in workspace.runs_dir.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
        )
        if not runs:
            return
        run_dir = runs[-1]
        written = sorted(
            str(p.relative_to(run_dir)) for p in run_dir.rglob("*") if p.is_file()
        )
        write_json(
            run_dir / "error.json",
            StageFailure(
                run_id=run_dir.name,
                stage=_infer_stage(written),
                error_type=type(exc).__name__,
                error=str(exc)[:2_000],
                created=f"{datetime.now():%Y-%m-%dT%H:%M:%S}",
                artifacts_written=written,
            ),
        )
    except OSError:
        pass


# Artifact each stage produces, in pipeline order. The last one present tells us
# how far the run got.
_STAGE_ARTIFACTS: tuple[tuple[str, str], ...] = (
    ("context.json", "input_assessment"),
    ("input_assessment.json", "domain_map"),
    ("domain_map.json", "layer_analysis"),
    ("layers", "plan_portfolio"),
    ("candidate_portfolio.json", "draft_opportunities"),
    ("drafts", "critique_refine"),
    ("scores.json", "rank_filter"),
    ("ranked.json", "publish"),
)


def _infer_stage(written: list[str]) -> str:
    """Name the stage that most likely failed, from what was written."""
    stage = "ingest"
    for marker, next_stage in _STAGE_ARTIFACTS:
        if any(path == marker or path.startswith(f"{marker}/") for path in written):
            stage = next_stage
    return stage
