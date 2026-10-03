"""LangGraph wiring for the mining pipeline.

ingest → assess_input → domain_map → 5 layer analyses (Send fan-out)
→ plan_portfolio → draft candidates (Send fan-out) → critique/refine
→ score → rank_filter → publish

Stage behaviour lives in ``graph/stages.py``; the run lifecycle in
``graph/runner.py``.
"""

from __future__ import annotations

from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from automation_miner.artifacts.workspace import Workspace
from automation_miner.context import ContextBudget
from automation_miner.graph.stages import PipelineStages
from automation_miner.graph.state import MinerState
from automation_miner.models.client import MinerModel, RunScopedModel
from automation_miner.schemas import InputQuality


# Linear edges in pipeline order; the two fan-outs are conditional edges.
_EDGES = (
    (START, "ingest"),
    ("ingest", "assess_input"),
    ("assess_input", "domain_map"),
    ("analyze_layer", "plan_portfolio"),
    ("draft_candidate", "critique_refine"),
    ("critique_refine", "score"),
    ("score", "rank_filter"),
    ("rank_filter", "publish"),
    ("publish", END),
)
_NODES = (
    "ingest", "assess_input", "domain_map", "analyze_layer", "plan_portfolio",
    "draft_candidate", "critique_refine", "score", "rank_filter", "publish",
)


def build_graph(
    model: MinerModel | RunScopedModel,
    workspace: Workspace,
    budget: ContextBudget | None = None,
    preflight_callback: Callable[[InputQuality], None] | None = None,
) -> Any:
    """Build the compiled mining pipeline for one model client + workspace."""
    stages = PipelineStages(model, workspace, budget, preflight_callback)
    graph = StateGraph(MinerState)
    for name in _NODES:
        graph.add_node(name, getattr(stages, name))
    for source, target in _EDGES:
        graph.add_edge(source, target)
    graph.add_conditional_edges("domain_map", stages.fanout_layers, ["analyze_layer"])
    graph.add_conditional_edges("plan_portfolio", stages.fanout_candidates, ["draft_candidate"])
    return graph.compile()
