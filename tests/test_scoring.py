"""Scoring math, constraint overrides, strategic filters, ranking."""

from __future__ import annotations

from automation_miner.schemas import ICEScore, Level, Opportunity, OpportunityDraft
from automation_miner.scoring import (
    apply_constraint_overrides,
    calibrate,
    compute_ice,
    ease_first,
    rank,
    strategic_filters,
    validate_score,
)


def _opp(
    am_id: str,
    impact: int,
    confidence: int,
    ease: int,
    risk: Level = Level.MEDIUM,
) -> Opportunity:
    draft = OpportunityDraft.model_validate(
        {
            "layer": "document",
            "title": f"Opp {am_id}",
            "problem": "p",
            "proposed_automation": "a",
            "inputs": ["i"],
            "steps": ["s"],
            "outputs": ["o"],
            "hitl_points": ["h"],
            "technical_requirements": ["t"],
            "dependencies": ["d"],
            "constraints": [],
            "impact_analysis": [],
            "implementation": {"mvp": ["m"], "expansion": ["e"], "autonomy": ["a"]},
            "risks": [],
            "agents_required": "1",
            "effort": "low",
            "impact_estimate": "high",
            "risk_level": risk.value,
        }
    )
    score = ICEScore(impact=impact, confidence=confidence, ease=ease, rationale="r")
    return Opportunity(
        am_id=am_id,
        domain="D",
        domain_slug="d",
        draft=draft,
        score=score,
        ice=compute_ice(impact, confidence, ease),
        critique_overall=8.0,
        iterations=1,
    )


def test_validate_score_clamps() -> None:
    assert validate_score(0) == 1
    assert validate_score(3) == 3
    assert validate_score(99) == 5


def test_compute_ice() -> None:
    assert compute_ice(5, 5, 5) == 125
    assert compute_ice(1, 1, 1) == 1
    assert compute_ice(4, 4, 5) == 80


def test_calibrate_clamps_via_model_copy() -> None:
    score = ICEScore(impact=3, confidence=3, ease=3, rationale="r")
    assert calibrate(score).ice == 27


def test_compliance_override_caps_high_risk() -> None:
    score = ICEScore(impact=4, confidence=4, ease=4, rationale="r")
    new_score, new_risk, applied = apply_constraint_overrides(
        score, Level.HIGH, "compliance:heavy"
    )
    assert new_risk == Level.MEDIUM
    assert new_score == score
    assert any("compliance" in a for a in applied)


def test_no_coding_override_caps_ease() -> None:
    score = ICEScore(impact=4, confidence=4, ease=5, rationale="r")
    new_score, _, applied = apply_constraint_overrides(score, Level.LOW, "no custom dev")
    assert new_score.ease == 4
    assert any("no-coding" in a for a in applied)


def test_no_overrides_for_plain_constraints() -> None:
    score = ICEScore(impact=4, confidence=4, ease=4, rationale="r")
    _, risk, applied = apply_constraint_overrides(score, Level.LOW, "budget:high")
    assert risk == Level.LOW
    assert applied == []


def test_ease_first_detection() -> None:
    assert ease_first("urgent rollout")
    assert ease_first("needed in 1 week")
    assert not ease_first("budget:low")


def test_strategic_filters() -> None:
    low_hanging = _opp("AM-001", impact=3, confidence=2, ease=4)
    flags = strategic_filters(low_hanging)
    assert flags == {"low_hanging": True, "high_value": False, "vision": False}

    high_value = _opp("AM-002", impact=4, confidence=4, ease=4, risk=Level.MEDIUM)
    flags = strategic_filters(high_value)
    assert flags["high_value"] and flags["low_hanging"] and not flags["vision"]

    risky = _opp("AM-003", impact=5, confidence=5, ease=3, risk=Level.HIGH)
    assert not strategic_filters(risky)["high_value"]

    vision = _opp("AM-004", impact=5, confidence=1, ease=2)
    flags = strategic_filters(vision)
    assert flags["vision"] and not flags["low_hanging"]


def test_rank_by_ice_desc() -> None:
    opps = [
        _opp("AM-001", 3, 3, 3),
        _opp("AM-002", 5, 5, 5),
        _opp("AM-003", 4, 4, 4),
    ]
    assert [o.am_id for o in rank(opps)] == ["AM-002", "AM-003", "AM-001"]


def test_rank_ease_first_when_urgent() -> None:
    opps = [
        _opp("AM-001", 5, 5, 2),  # ICE 50, ease 2
        _opp("AM-002", 3, 3, 5),  # ICE 45, ease 5
    ]
    ranked = rank(opps, constraints="urgent")
    assert ranked[0].am_id == "AM-002"
    assert [o.am_id for o in rank(opps)] == ["AM-001", "AM-002"]
