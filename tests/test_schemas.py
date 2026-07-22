"""Schema validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from automation_miner.schemas import (
    CRITIQUE_THRESHOLD,
    ContextPacket,
    Critique,
    ICEScore,
    Layer,
    Level,
    OpportunityDraft,
    Opportunity,
)


def test_layer_enum_values() -> None:
    assert [layer.value for layer in Layer] == [
        "document",
        "communication",
        "decision",
        "monitoring",
        "knowledge",
    ]


def test_context_packet_minimal() -> None:
    packet = ContextPacket(
        domain="X", domain_slug="x", source_kind="idea", content="hello"
    )
    assert packet.constraints == ""
    assert packet.digested is False


def test_critique_weighted_overall_and_threshold() -> None:
    perfect = Critique(
        groundedness=10,
        specificity=10,
        quantified_impact=10,
        feasibility=10,
        hitl_clarity=10,
        differentiation=10,
        feedback="ok",
    )
    assert perfect.overall == 10.0
    assert perfect.passed

    weak = Critique(
        groundedness=10,  # heaviest weight
        specificity=5,
        quantified_impact=5,
        feasibility=5,
        hitl_clarity=5,
        differentiation=5,
        feedback="meh",
    )
    assert weak.overall == pytest.approx(6.25)
    assert weak.passed is (weak.overall >= CRITIQUE_THRESHOLD)


def test_critique_bounds_enforced() -> None:
    with pytest.raises(ValidationError):
        Critique(
            groundedness=11,
            specificity=0,
            quantified_impact=0,
            feasibility=0,
            hitl_clarity=0,
            differentiation=0,
            feedback="x",
        )


def test_ice_score_product_and_bounds() -> None:
    score = ICEScore(impact=4, confidence=3, ease=5, rationale="r")
    assert score.ice == 60
    with pytest.raises(ValidationError):
        ICEScore(impact=0, confidence=3, ease=3, rationale="r")
    with pytest.raises(ValidationError):
        ICEScore(impact=6, confidence=3, ease=3, rationale="r")


def test_level_rank_ordering() -> None:
    assert Level.LOW.rank < Level.MEDIUM.rank < Level.HIGH.rank


def test_draft_requires_layer(sample_draft: OpportunityDraft) -> None:
    assert sample_draft.layer == Layer.DOCUMENT
    data = sample_draft.model_dump(mode="json")
    data["layer"] = "bogus"
    with pytest.raises(ValidationError):
        OpportunityDraft.model_validate(data)


def test_schemas_reject_extra_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ICEScore(impact=3, confidence=3, ease=3, rationale="r", surprise=True)


def test_opportunity_rejects_inconsistent_ice(sample_draft: OpportunityDraft) -> None:
    score = ICEScore(impact=3, confidence=3, ease=3, rationale="r")
    with pytest.raises(ValidationError, match="ice must equal"):
        Opportunity(
            am_id="AM-001",
            domain="D",
            domain_slug="d",
            draft=sample_draft,
            score=score,
            ice=99,
            critique_overall=8,
            iterations=1,
        )
