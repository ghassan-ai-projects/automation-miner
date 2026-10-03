"""Comparative scoring: one scorer call grades the whole portfolio side by side.

Scored one draft at a time, the flash scorer anchored every brief on the
middle rung: a real strategy run produced four briefs at ICE 18-27 and a
fifth at 36, all in the "low" tier, so tiers and strategic filters never
fired. Seeing every opportunity at once, the scorer can use the scale
relatively. Any opportunity the comparative call misses or duplicates falls
back to an individual call, so every opportunity is always scored.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from automation_miner.prompts import SCORER_SYSTEM, portfolio_score_prompt, score_prompt
from automation_miner.schemas import ICEScore, OpportunityDraft, PortfolioScores

if TYPE_CHECKING:
    from automation_miner.models.client import MinerModel, RunScopedModel


def _digest(am_id: str, draft: OpportunityDraft, critique: float) -> dict[str, Any]:
    """What a scorer needs to compare value, certainty, and difficulty."""
    return {
        "am_id": am_id,
        "title": draft.title,
        "layer": draft.layer.value,
        "problem": draft.problem,
        "proposed_automation": draft.proposed_automation,
        "impact_analysis": [row.model_dump(mode="json") for row in draft.impact_analysis],
        "technical_requirements": draft.technical_requirements,
        "dependencies": draft.dependencies,
        "effort": draft.effort.value,
        "impact_estimate": draft.impact_estimate.value,
        "risk_level": draft.risk_level.value,
        "agent_count": draft.agent_count,
        "assumptions": draft.assumptions,
        "cited_evidence_blocks": len(draft.evidence_refs),
        "critic_score": critique,
    }


def _unique_scores(
    result: PortfolioScores, wanted: set[str]
) -> dict[str, ICEScore]:
    """Scores for requested ids that appear exactly once in the comparative call."""
    counts: dict[str, int] = {}
    for entry in result.scores:
        counts[entry.am_id] = counts.get(entry.am_id, 0) + 1
    return {
        entry.am_id: ICEScore.model_validate(entry.model_dump(exclude={"am_id"}))
        for entry in result.scores
        if entry.am_id in wanted and counts[entry.am_id] == 1
    }


def score_portfolio(
    model: MinerModel | RunScopedModel,
    items: list[tuple[str, OpportunityDraft, float]],
    constraints: str,
) -> tuple[dict[str, ICEScore], list[str]]:
    """Return one proposed ICE score per am_id and the ids that needed fallback."""
    digests = [_digest(am_id, draft, critique) for am_id, draft, critique in items]
    prompt = portfolio_score_prompt(json.dumps(digests, indent=2), constraints)
    result = model.call_json("scorer", SCORER_SYSTEM, prompt, PortfolioScores)
    scores = _unique_scores(result, {am_id for am_id, _, _ in items})
    fallback = [am_id for am_id, _, _ in items if am_id not in scores]
    drafts = {am_id: draft for am_id, draft, _ in items}
    for am_id in fallback:
        single = score_prompt(drafts[am_id].model_dump_json(indent=2), constraints)
        scores[am_id] = model.call_json("scorer", SCORER_SYSTEM, single, ICEScore)
    return scores, fallback
