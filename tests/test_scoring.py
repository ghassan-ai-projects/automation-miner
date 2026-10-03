"""Scoring math, coherence validation, constraint policy, ranking, eligibility."""

from __future__ import annotations

from factories import make_draft, make_opportunity, make_score

from automation_miner.schemas import Eligibility, Tier
from automation_miner.scoring import (
    apply_portfolio_policy,
    compute_ice,
    published,
    validate_coherence,
    validate_score,
)


def _ids(opportunities: list) -> list[str]:
    return [o.am_id for o in opportunities]


# ---------------------------------------------------------------------------
# Math
# ---------------------------------------------------------------------------


def test_validate_score_clamps() -> None:
    assert validate_score(0) == 1
    assert validate_score(3) == 3
    assert validate_score(99) == 5


def test_compute_ice() -> None:
    assert compute_ice(5, 5, 5) == 125
    assert compute_ice(1, 1, 1) == 1
    assert compute_ice(4, 4, 5) == 80


def test_tier_boundaries() -> None:
    assert Tier.for_ice(125) is Tier.VISION
    assert Tier.for_ice(80) is Tier.VISION
    assert Tier.for_ice(79) is Tier.HIGH
    assert Tier.for_ice(60) is Tier.HIGH
    assert Tier.for_ice(59) is Tier.MEDIUM
    assert Tier.for_ice(40) is Tier.MEDIUM
    assert Tier.for_ice(39) is Tier.LOW
    assert Tier.for_ice(1) is Tier.LOW


# ---------------------------------------------------------------------------
# Coherence validation — the layer that used to be dead code
# ---------------------------------------------------------------------------


def test_high_effort_cannot_claim_maximum_ease() -> None:
    """The old calibrate() was unreachable because pydantic already bounded 1-5."""
    draft = make_draft(effort="high")
    score, notes = validate_coherence(make_score(4, 4, 5), draft)
    assert score.ease == 2
    assert any("incompatible with high effort" in note for note in notes)
    assert score.ice == 32


def test_medium_effort_caps_ease_at_four() -> None:
    score, notes = validate_coherence(make_score(4, 4, 5), make_draft(effort="medium"))
    assert score.ease == 4
    assert notes


def test_low_effort_with_low_ease_is_flagged_not_inflated() -> None:
    """Adjustments only ever lower a score; a pessimistic factor is flagged."""
    score, notes = validate_coherence(make_score(4, 4, 2), make_draft(effort="low"))
    assert score.ease == 2
    assert any("pessimistic" in note for note in notes)


def test_impact_capped_by_the_drafts_own_estimate() -> None:
    score, notes = validate_coherence(
        make_score(5, 4, 4), make_draft(impact_estimate="low", effort="low")
    )
    assert score.impact == 2
    assert any("impact estimate" in note for note in notes)


def test_high_risk_caps_confidence() -> None:
    score, _ = validate_coherence(
        make_score(4, 5, 4), make_draft(risk_level="high", effort="low")
    )
    assert score.confidence == 4


def test_missing_quantified_impact_caps_confidence() -> None:
    score, notes = validate_coherence(
        make_score(4, 5, 4), make_draft(impact_analysis=[], effort="low")
    )
    assert score.confidence == 3
    assert any("quantified impact" in note for note in notes)


def test_ungrounded_draft_caps_confidence() -> None:
    score, notes = validate_coherence(
        make_score(4, 5, 4), make_draft(evidence_refs=[], effort="low")
    )
    assert score.confidence == 3
    assert any("cites no evidence" in note for note in notes)


def test_unresolved_evidence_refs_are_flagged() -> None:
    _, notes = validate_coherence(make_score(), make_draft(), unresolved_refs=["S99"])
    assert any("do not exist" in note and "S99" in note for note in notes)


def test_unresolved_evidence_refs_are_an_independent_publication_gate() -> None:
    ranked = apply_portfolio_policy(
        [make_opportunity("AM-099").model_copy(update={"unresolved_refs": ["S99"]})]
    )

    assert not published(ranked)
    assert ranked[0].eligibility is Eligibility.FILTERED
    assert ranked[0].exclusion_reasons == [
        "grounding: cited evidence ids do not resolve: S99"
    ]


def test_coherent_score_is_returned_unchanged() -> None:
    score = make_score(4, 4, 4)
    validated, notes = validate_coherence(score, make_draft(effort="medium"))
    assert validated is score
    assert notes == []


# ---------------------------------------------------------------------------
# Constraint policy — one parser for overrides and ranking
# ---------------------------------------------------------------------------
