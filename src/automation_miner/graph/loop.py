"""The per-opportunity critique-refine quality loop.

Critic scores each draft on the rubric (threshold 7.5). Below threshold, the
refiner rewrites the draft with the critique as input, up to
``max_iterations`` critique rounds. Every version is recorded so callers can
persist drafts/AM-XXX.v{n}.json artifacts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from automation_miner.prompts import (
    CRITIC_SYSTEM,
    REFINER_SYSTEM,
    critique_prompt,
    refine_prompt,
)
from automation_miner.schemas import Critique, OpportunityDraft

if TYPE_CHECKING:
    from automation_miner.models.client import MinerModel


def run_critique_loop(
    model: MinerModel,
    draft: OpportunityDraft,
    other_titles: list[str],
    max_iterations: int,
) -> tuple[OpportunityDraft, list[dict[str, Any]]]:
    """Run critique ⇄ refine until pass or max_iterations critique rounds.

    Returns the final draft and the full iteration history
    (one entry per critique round: version, draft, critique, overall).
    """
    current = draft
    history: list[dict[str, Any]] = []
    for round_no in range(1, max_iterations + 1):
        critique = model.call_json(
            "critic",
            CRITIC_SYSTEM,
            critique_prompt(current.model_dump_json(), other_titles),
            Critique,
        )
        history.append(
            {
                "version": round_no,
                "draft": current.model_dump(mode="json"),
                "critique": critique.model_dump(mode="json"),
                "overall": critique.overall,
                "passed": critique.passed,
            }
        )
        if critique.passed or round_no == max_iterations:
            break
        current = model.call_json(
            "refiner",
            REFINER_SYSTEM,
            refine_prompt(current.model_dump_json(), critique.model_dump_json()),
            OpportunityDraft,
        )
        current = current.model_copy(update={"layer": draft.layer})
    return current, history
