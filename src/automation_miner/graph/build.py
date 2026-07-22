"""LangGraph pipeline: ingest → domain_map → 5 layer analyses → 5 drafters
→ critique/refine loop → ICE scoring → rank + filters → publish.

Every node persists JSON artifacts into the run directory; artifacts are the
source of truth. Fan-out over the five layers uses langgraph's Send API.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from automation_miner import ingest as ing
from automation_miner.artifacts.briefs import render_brief, title_slug
from automation_miner.artifacts.registry import reindex
from automation_miner.artifacts.reports import render_report, render_run_md
from automation_miner.artifacts.workspace import Workspace, write_json, write_text
from automation_miner.graph.loop import run_critique_loop
from automation_miner.graph.state import MinerState
from automation_miner.models.client import MinerModel
from automation_miner.models.config import load_config
from automation_miner.prompts import (
    DOMAIN_MAP_SYSTEM,
    DRAFTER_SYSTEM,
    LAYER_ANALYST_SYSTEM,
    PROMPT_VERSION,
    SCORER_SYSTEM,
    domain_map_prompt,
    draft_prompt,
    layer_analysis_prompt,
    score_prompt,
)
from automation_miner.schemas import (
    LAYER_ORDER,
    ContextPacket,
    DomainMap,
    DraftBatch,
    ICEScore,
    Layer,
    LayerAnalysis,
    Opportunity,
    OpportunityDraft,
    RunManifest,
)
from automation_miner.scoring import (
    apply_constraint_overrides,
    calibrate,
    compute_ice,
    rank,
    strategic_filters,
)

MAX_ITERATIONS = 10


def build_graph(model: MinerModel, workspace: Workspace) -> Any:
    """Build the compiled mining pipeline for one model client + workspace."""

    def ingest_node(state: MinerState) -> dict[str, Any]:
        kind, value = state["input_kind"], state["input_value"]
        if kind == "idea":
            packet = ing.ingest_idea(value, state["constraints"])
        elif kind == "file":
            packet = ing.ingest_file(Path(value), state["constraints"])
        else:
            packet = ing.ingest_kb(Path(value), state["constraints"], model)
        run_dir = workspace.new_run_dir(packet.domain_slug)
        write_json(run_dir / "context.json", packet)
        return {
            "context": packet.model_dump(mode="json"),
            "run_dir": str(run_dir),
            "run_id": run_dir.name,
        }

    def domain_map_node(state: MinerState) -> dict[str, Any]:
        ctx = ContextPacket.model_validate(state["context"])
        result = model.call_json(
            "mapper",
            DOMAIN_MAP_SYSTEM,
            domain_map_prompt(ctx.domain, ctx.constraints, ctx.content),
            DomainMap,
        )
        write_json(Path(state["run_dir"]) / "domain_map.json", result)
        return {"domain_map": result.model_dump(mode="json")}

    def fanout_layers(state: MinerState) -> list[Send]:
        shared = {
            "context": state["context"],
            "domain_map": state["domain_map"],
            "run_dir": state["run_dir"],
            "constraints": state["constraints"],
        }
        return [Send("analyze_layer", {**shared, "layer": layer.value}) for layer in LAYER_ORDER]

    def analyze_layer_node(state: MinerState) -> dict[str, Any]:
        ctx = ContextPacket.model_validate(state["context"])
        layer = Layer(state["layer"])
        evidence = ctx.content + "\n\nDomain map:\n" + DomainMap.model_validate(
            state["domain_map"]
        ).model_dump_json()
        result = model.call_json(
            "layer_analyst",
            LAYER_ANALYST_SYSTEM,
            layer_analysis_prompt(layer.value, ctx.domain, ctx.constraints, evidence),
            LayerAnalysis,
        )
        result = result.model_copy(update={"layer": layer})
        write_json(Path(state["run_dir"]) / "layers" / f"{layer.value}.json", result)
        return {"layer_analyses": [result.model_dump(mode="json")]}

    def fanout_drafts(state: MinerState) -> list[Send]:
        analyses = sorted(
            state["layer_analyses"], key=lambda a: LAYER_ORDER.index(Layer(a["layer"]))
        )
        shared = {
            "context": state["context"],
            "domain_map": state["domain_map"],
            "run_dir": state["run_dir"],
        }
        return [
            Send("draft_layer", {**shared, "layer": a["layer"], "analysis": a})
            for a in analyses
        ]

    def draft_layer_node(state: MinerState) -> dict[str, Any]:
        ctx = ContextPacket.model_validate(state["context"])
        layer = Layer(state["layer"])
        batch = model.call_json(
            "drafter",
            DRAFTER_SYSTEM,
            draft_prompt(
                layer.value,
                _json(state["analysis"]),
                ctx.content,
                ctx.constraints,
                _json(state["domain_map"]),
            ),
            DraftBatch,
        )
        drafts = [
            d.model_copy(update={"layer": layer}).model_dump(mode="json") for d in batch.drafts
        ]
        write_json(
            Path(state["run_dir"]) / "drafts" / f"{layer.value}.batch.json",
            {"layer": layer.value, "drafts": drafts},
        )
        return {"drafts": drafts}

    def critique_refine_node(state: MinerState) -> dict[str, Any]:
        run_dir = Path(state["run_dir"])
        ctx = ContextPacket.model_validate(state["context"])
        ordered = sorted(
            state["drafts"],
            key=lambda d: (LAYER_ORDER.index(Layer(d["layer"])), d["title"]),
        )
        reserved_numbers = workspace.reserve_am_numbers(len(ordered))
        refined: list[dict[str, Any]] = []
        for i, raw in enumerate(ordered):
            am_id = f"AM-{reserved_numbers[i]:03d}"
            draft = OpportunityDraft.model_validate(raw)
            others = [d["title"] for d in ordered if d is not raw]
            evidence = f"{ctx.content}\n\nDomain map:\n{_json(state['domain_map'])}"
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
            refined.append(
                {
                    "am_id": am_id,
                    "domain": ctx.domain,
                    "domain_slug": ctx.domain_slug,
                    "draft": final.model_dump(mode="json"),
                    "critique_overall": history[-1]["overall"],
                    "iterations": len(history),
                }
            )
        return {"refined": refined}

    def score_node(state: MinerState) -> dict[str, Any]:
        constraints = state["constraints"]
        opportunities: list[dict[str, Any]] = []
        for item in state["refined"]:
            draft = OpportunityDraft.model_validate(item["draft"])
            proposed = model.call_json(
                "scorer",
                SCORER_SYSTEM,
                score_prompt(draft.model_dump_json(), constraints),
                ICEScore,
            )
            score = calibrate(proposed)
            score, risk, applied = apply_constraint_overrides(
                score, draft.risk_level, constraints
            )
            draft = draft.model_copy(update={"risk_level": risk})
            opp = Opportunity(
                am_id=item["am_id"],
                domain=item["domain"],
                domain_slug=item["domain_slug"],
                draft=draft,
                score=score,
                ice=compute_ice(score.impact, score.confidence, score.ease),
                critique_overall=item["critique_overall"],
                iterations=item["iterations"],
                overrides_applied=applied,
            )
            opportunities.append(opp.model_dump(mode="json"))
        write_json(
            Path(state["run_dir"]) / "scores.json",
            {"opportunities": opportunities},
        )
        return {"opportunities": opportunities}

    def rank_filter_node(state: MinerState) -> dict[str, Any]:
        ranked = rank(
            [Opportunity.model_validate(o) for o in state["opportunities"]],
            state["constraints"],
        )
        write_json(
            Path(state["run_dir"]) / "ranked.json",
            {"opportunities": [o.model_dump(mode="json") for o in ranked]},
        )
        return {"opportunities": [o.model_dump(mode="json") for o in ranked]}

    def publish_node(state: MinerState) -> dict[str, Any]:
        run_dir = Path(state["run_dir"])
        ctx = ContextPacket.model_validate(state["context"])
        ranked = [Opportunity.model_validate(o) for o in state["opportunities"]]

        opp_dir = workspace.opp_dir(ctx.domain_slug)
        brief_files = []
        for opp in ranked:
            fname = f"{opp.am_id}-{title_slug(opp.draft.title)}.md"
            write_text(opp_dir / fname, render_brief(opp, state["run_id"]))
            brief_files.append(str(opp_dir / fname))

        filters = {
            key: [o.am_id for o in ranked if strategic_filters(o)[key]]
            for key in ("low_hanging", "high_value", "vision")
        }
        write_json(
            run_dir / "opportunities.json",
            {
                "run_id": state["run_id"],
                "domain": ctx.domain,
                "opportunities": [o.model_dump(mode="json") for o in ranked],
                "filters": filters,
            },
        )
        write_text(
            run_dir / "run.md",
            render_run_md(
                state["run_id"],
                ctx,
                DomainMap.model_validate(state["domain_map"]),
                [LayerAnalysis.model_validate(a) for a in state["layer_analyses"]],
                ranked,
            ),
        )
        report = render_report(ranked)
        write_text(run_dir / "report.md", report)

        duration = time.time() - state.get("start_ts", time.time())
        manifest = RunManifest(
            run_id=state["run_id"],
            domain=ctx.domain,
            domain_slug=ctx.domain_slug,
            constraints=ctx.constraints,
            source_kind=ctx.source_kind,
            source_value=state["input_value"],
            created=state["created"],
            finished=f"{datetime.now():%Y-%m-%dT%H:%M:%S}",
            duration_seconds=round(duration, 2),
            max_iterations=state["max_iterations"],
            profile=state.get("profile", "default"),
            config_source=model.config.source,
            prompt_version=PROMPT_VERSION,
            dry_run=model.dry_run,
            models=model.routing_table(),
            opportunities=[o.am_id for o in ranked],
        )
        write_json(run_dir / "run.json", manifest)
        reindex(workspace.root)
        return {"report_path": str(run_dir / "report.md")}

    graph = StateGraph(MinerState)
    graph.add_node("ingest", ingest_node)
    graph.add_node("domain_map", domain_map_node)
    graph.add_node("analyze_layer", analyze_layer_node)
    graph.add_node("draft_layer", draft_layer_node)
    graph.add_node("critique_refine", critique_refine_node)
    graph.add_node("score", score_node)
    graph.add_node("rank_filter", rank_filter_node)
    graph.add_node("publish", publish_node)

    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "domain_map")
    graph.add_conditional_edges("domain_map", fanout_layers, ["analyze_layer"])
    graph.add_conditional_edges("analyze_layer", fanout_drafts, ["draft_layer"])
    graph.add_edge("draft_layer", "critique_refine")
    graph.add_edge("critique_refine", "score")
    graph.add_edge("score", "rank_filter")
    graph.add_edge("rank_filter", "publish")
    graph.add_edge("publish", END)
    return graph.compile()


def _json(value: Any) -> str:
    import json

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
    model: MinerModel | None = None,
) -> MinerState:
    """Run the full pipeline once. Exactly one of idea/file/kb is required."""
    provided = [x is not None for x in (idea, file, kb)]
    if sum(provided) != 1:
        raise ValueError("Provide exactly one of idea, file, or kb.")
    if not 1 <= max_iterations <= MAX_ITERATIONS:
        raise ValueError(f"max_iterations must be between 1 and {MAX_ITERATIONS}")
    if idea is not None:
        kind, value = "idea", idea
    elif file is not None:
        kind, value = "file", str(file)
    else:
        kind, value = "kb", str(kb)

    owns_model = model is None
    if model is None:
        model = MinerModel(load_config(workspace_path, profile), dry_run=dry_run)
    try:
        workspace = Workspace(workspace_path)
        workspace.ensure()
        initial: dict[str, Any] = {
            "workspace": str(workspace_path),
            "input_kind": kind,
            "input_value": value,
            "constraints": constraints,
            "max_iterations": max_iterations,
            "profile": profile,
            "created": f"{datetime.now():%Y-%m-%dT%H:%M:%S}",
            "start_ts": time.time(),
            "layer_analyses": [],
            "drafts": [],
        }
        graph = build_graph(model, workspace)
        result: MinerState = graph.invoke(initial)  # type: ignore[assignment]
        return result
    finally:
        if owns_model:
            model.close()
