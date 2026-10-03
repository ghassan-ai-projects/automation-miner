"""Prose hygiene: evidence commentary is detected in code, not by the critic."""

from __future__ import annotations

from automation_miner.hygiene import draft_hedges, find_hedges, hygiene_feedback
from automation_miner.models import mock
from automation_miner.schemas import OpportunityDraft


def test_detects_every_observed_hedge_form() -> None:
    text = (
        "GPS data – inferred from S2: 'GPS tracking'; API not explicitly stated. "
        "No evidence provided for this. The evidence does not describe the volume "
        "(inferred). Not confirmed in evidence. Clerks re-key claims [S3, S4]. Per S7: 'manual'."
    )
    codes = {hedge.code for hedge in find_hedges(text)}
    assert codes == {
        "quoted-source",
        "not-explicitly-stated",
        "no-evidence-provided",
        "evidence-does-not",
        "inferred-label",
        "not-in-evidence",
        "inferred-from-source",
        "inline-citation",
    }


def test_clean_expert_prose_has_no_hedges() -> None:
    text = (
        "ArbZG caps daily working time at 10 hours. Clerks re-key 1,850 FNOLs per "
        "week into ClaimsDesk, about 9 minutes each for email and paper claims."
    )
    assert find_hedges(text) == []


def test_draft_hedges_cover_nested_fields_and_feedback_is_bounded() -> None:
    draft = OpportunityDraft.model_validate(mock.call_json("drafter", "OpportunityDraft", ""))
    draft = draft.model_copy(
        update={"steps": [f"Step {i} (inferred: x)" for i in range(20)]}
    )
    hedges = draft_hedges(draft)
    assert len(hedges) == 20
    assert {hedge.field for hedge in hedges} == {"steps"}
    feedback = hygiene_feedback(hedges, limit=5)
    assert len(feedback) == 6
    assert feedback[-1].startswith("... and 15 more")
