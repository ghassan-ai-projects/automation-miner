"""Schema validation tests."""

from __future__ import annotations

import pytest
from factories import make_opportunity, make_score
from pydantic import ValidationError

from automation_miner.schemas import (
    CRITIQUE_THRESHOLD,
    Chunk,
    ContextPacket,
    Critique,
    Eligibility,
    ICEScore,
    Layer,
    Level,
    Opportunity,
    OpportunityDraft,
    Tier,
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
    packet = ContextPacket(domain="X", domain_slug="x", source_kind="idea", overview="hello")
    assert packet.constraints == ""
    assert packet.stats.digested is False
    assert packet.chunks == []
    assert packet.chunk_ids() == set()


def test_chunk_label_is_citable() -> None:
    chunk = Chunk(id="S12", source="claims.pdf", locator="p.4", text="body", tokens=1)
    assert chunk.label == "[S12] claims.pdf p.4"
    assert Chunk(id="S1", source="a.md", text="b", tokens=1).label == "[S1] a.md"


def test_chunk_id_must_be_well_formed() -> None:
    with pytest.raises(ValidationError):
        Chunk(id="12", source="a.md", text="b", tokens=1)


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
    assert make_score(4, 3, 5).ice == 60
    with pytest.raises(ValidationError):
        make_score(0, 3, 3)
    with pytest.raises(ValidationError):
        make_score(6, 3, 3)


def test_ice_score_requires_a_rationale_per_factor() -> None:
    """One shared paragraph made an individual factor unauditable."""
    with pytest.raises(ValidationError, match="ease_rationale"):
        ICEScore(
            impact=4,
            confidence=4,
            ease=4,
            impact_rationale="a",
            confidence_rationale="b",
        )


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
        ICEScore(
            impact=3,
            confidence=3,
            ease=3,
            impact_rationale="a",
            confidence_rationale="b",
            ease_rationale="c",
            surprise=True,
        )


def _opportunity_kwargs(draft: OpportunityDraft, **overrides: object) -> dict[str, object]:
    score = make_score(3, 3, 3)
    data: dict[str, object] = {
        "am_id": "AM-001",
        "domain": "D",
        "domain_slug": "d",
        "draft": draft,
        "score": score,
        "ice": score.ice,
        "tier": Tier.for_ice(score.ice),
        "critique_overall": 8,
        "iterations": 1,
    }
    data.update(overrides)
    return data


def test_opportunity_rejects_inconsistent_ice(sample_draft: OpportunityDraft) -> None:
    with pytest.raises(ValidationError, match="ice must equal"):
        Opportunity(**_opportunity_kwargs(sample_draft, ice=99))


def test_opportunity_rejects_a_tier_that_does_not_match_ice(
    sample_draft: OpportunityDraft,
) -> None:
    with pytest.raises(ValidationError, match="tier must be"):
        Opportunity(**_opportunity_kwargs(sample_draft, tier=Tier.VISION))


def test_filtered_opportunity_must_record_a_reason(sample_draft: OpportunityDraft) -> None:
    """Silent filtering is what hid discarded work; the schema now forbids it."""
    with pytest.raises(ValidationError, match="must record at least one exclusion reason"):
        Opportunity(**_opportunity_kwargs(sample_draft, eligibility=Eligibility.FILTERED))


def test_published_property() -> None:
    assert make_opportunity().published
    filtered = make_opportunity().model_copy(
        update={"eligibility": Eligibility.FILTERED, "exclusion_reasons": ["policy"]}
    )
    assert not filtered.published
