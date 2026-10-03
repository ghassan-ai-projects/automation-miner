"""Pipeline stages: one method per LangGraph node, grouped by phase.

Each stage reads typed artifacts from ``MinerState``, makes its model calls,
persists its JSON artifact through ``RunLayout`` (artifacts are the source of
truth), and returns only the state channels it owns. Wiring lives in
``graph/build.py``; the run lifecycle in ``graph/runner.py``; the publication
transaction in ``graph/publish.py``.

Each stage draws its own evidence: it selects the chunks most relevant to its
question within its own token budget instead of re-sending one shared blob.
Critique runs in parallel over opportunities; AM-ids are reserved before
fan-out, so ids stay stable and results are re-sorted deterministically.
"""

from __future__ import annotations

from automation_miner.graph.stages.analysis import AnalysisStages
from automation_miner.graph.stages.planning import PlanningStages
from automation_miner.graph.stages.review import ReviewStages


class PipelineStages(AnalysisStages, PlanningStages, ReviewStages):
    """The mining pipeline's nodes, bound to one model client and workspace."""


__all__ = ["PipelineStages"]
