"""The per-opportunity critique-refine quality loop.

Critic scores each draft on the rubric (threshold 7.5). Below threshold, the
refiner rewrites the draft with the critique as input, up to
``max_iterations`` critique rounds. Every version is recorded so callers can
persist drafts/AM-XXX.v{n}.json artifacts.

Prose hygiene and arithmetic are checked in code, not left to the critic: a
draft that writes evidence commentary into its prose, or states a derived
number its own formula does not produce, does not pass a round, and the exact
findings are added to the critique's ``writing_issues`` for the refiner. The
critic is told which derivations code verified, so it does not re-derive them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from automation_miner.derivations import (
    arithmetic_issues,
    check_derivations,
    derivation_record,
    verified_notes,
)
from automation_miner.hygiene import draft_hedges, hygiene_feedback
from automation_miner.prompts import (
    CRITIC_SYSTEM,
    REFINER_SYSTEM,
    critique_prompt,
    refine_prompt,
)
from automation_miner.schemas import Critique, OpportunityDraft

if TYPE_CHECKING:
    from automation_miner.models.client import MinerModel, RunScopedModel


def _critique_round(
    model: MinerModel | RunScopedModel, draft: OpportunityDraft, round_no: int,
    other_titles: list[str], evidence: str, constraints: str,
) -> tuple[Critique, dict[str, Any]]:
    """One critic call plus the code-side hygiene check, as a history entry."""
    checks = check_derivations(draft)
    prompt = critique_prompt(
        draft.model_dump_json(), other_titles, evidence, constraints, verified_notes(checks)
    )
    critique = model.call_json("critic", CRITIC_SYSTEM, prompt, Critique)
    hedges, arithmetic = draft_hedges(draft), arithmetic_issues(checks)
    if hedges or arithmetic:
        issues = [*critique.writing_issues, *hygiene_feedback(hedges), *arithmetic]
        critique = critique.model_copy(update={"writing_issues": issues})
    entry = {
        "version": round_no,
        "draft": draft.model_dump(mode="json"),
        "critique": critique.model_dump(mode="json"),
        "overall": critique.overall,
        "passed": critique.passed and not hedges and not arithmetic,
        "hedges": len(hedges),
        "derivations": derivation_record(checks),
        "gate_reasons": critique.gate_reasons,
        "selected": False,
    }
    return critique, entry


def _refine(
    model: MinerModel | RunScopedModel, draft: OpportunityDraft, critique: Critique,
    original: OpportunityDraft, evidence: str, constraints: str,
) -> OpportunityDraft:
    prompt = refine_prompt(draft.model_dump_json(), critique.model_dump_json(), evidence, constraints)
    refined = model.call_json("refiner", REFINER_SYSTEM, prompt, OpportunityDraft)
    # Plan links are owned by code, not by the model's rewrite.
    return refined.model_copy(
        update={"layer": original.layer, "addresses_pains": original.addresses_pains}
    )


def _select(history: list[dict[str, Any]]) -> OpportunityDraft:
    """A refiner is not assumed to be monotonic: keep the strongest version."""
    pool = [entry for entry in history if entry["passed"]] or history
    selected = max(
        pool,
        key=lambda e: (not e["gate_reasons"], e["overall"] - 0.1 * e["hedges"], -e["version"]),
    )
    selected["selected"] = True
    return OpportunityDraft.model_validate(selected["draft"])


def run_critique_loop(
    model: MinerModel | RunScopedModel, draft: OpportunityDraft, other_titles: list[str],
    max_iterations: int, evidence: str = "", constraints: str = "",
) -> tuple[OpportunityDraft, list[dict[str, Any]]]:
    """Run critique ⇄ refine until pass or max_iterations critique rounds.

    Returns the final draft and the full iteration history
    (one entry per critique round: version, draft, critique, overall).
    """
    if max_iterations < 1:
        raise ValueError("max_iterations must be at least 1")
    current = draft
    history: list[dict[str, Any]] = []
    for round_no in range(1, max_iterations + 1):
        critique, entry = _critique_round(
            model, current, round_no, other_titles, evidence, constraints
        )
        history.append(entry)
        if entry["passed"] or round_no == max_iterations:
            break
        current = _refine(model, current, critique, draft, evidence, constraints)
    return _select(history), history
