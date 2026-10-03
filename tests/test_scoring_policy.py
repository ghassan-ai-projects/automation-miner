"""Constraint policy parsing and score overrides."""

from __future__ import annotations

from factories import make_score

from automation_miner.schemas import Level
from automation_miner.scoring import (
    apply_constraint_overrides,
    ease_first,
    parse_constraint_policy,
)


def _ids(opportunities: list) -> list[str]:
    return [o.am_id for o in opportunities]


# ---------------------------------------------------------------------------
# Math
# ---------------------------------------------------------------------------


def test_policy_recognizes_every_documented_budget_phrasing() -> None:
    for text in ("budget: low", "budget:zero", "budget = none", "no budget"):
        assert parse_constraint_policy(text).low_budget, text


def test_policy_recognizes_agent_limit_spellings() -> None:
    """agent_limit and agent-limit used to behave differently from 'agent limit'."""
    for text in ("agent limit: 3", "agent_limit: 3", "agent-limit=3"):
        assert parse_constraint_policy(text).agent_limit == 3, text
    assert parse_constraint_policy("small team").agent_limit == 2
    assert parse_constraint_policy("team:3").agent_limit == 2


def test_policy_recognizes_urgency_spellings() -> None:
    for text in ("urgent", "needed in 1 week", "timeline: tight", "tight timeline"):
        assert parse_constraint_policy(text).urgent, text


def test_policy_does_not_activate_on_negated_or_dismissed_prose() -> None:
    policy = parse_constraint_policy(
        "no budget concerns, spend freely; compliance is not relevant; we are not urgent"
    )

    assert not policy.low_budget
    assert not policy.compliance
    assert not policy.urgent


def test_policy_keeps_an_active_clause_after_a_negated_clause() -> None:
    policy = parse_constraint_policy("not urgent, but urgent escalation window")

    assert policy.urgent


def test_payment_and_residency_negations_are_not_constraints() -> None:
    policy = parse_constraint_policy(
        "payments do not require human approval; data do not remain in EU"
    )

    assert not policy.human_payment_approval
    assert not policy.eu_data_residency


def test_structured_policy_overrides_legacy_prose_and_unknowns_stay_advisory() -> None:
    policy = parse_constraint_policy(
        "budget:low urgent",
        {"budget": "high", "urgent": "false", "deployment": "local-only"},
    )

    assert not policy.low_budget
    assert not policy.urgent
    assert policy.advisory_params == ("deployment",)
    assert any("advisory" in note for note in policy.describe())


def test_policy_recognizes_data_residency_and_payment_approval() -> None:
    policy = parse_constraint_policy(
        "EU data residency; payments require human approval"
    )
    assert policy.eu_data_residency
    assert policy.human_payment_approval
    assert len(policy.describe()) == 2


def test_every_active_policy_is_recorded_in_overrides() -> None:
    """The divergence bug: these reshaped the portfolio while recording nothing."""
    for text in ("budget: zero", "no budget", "agent_limit: 3", "team:3", "timeline: tight"):
        policy = parse_constraint_policy(text)
        _, _, applied = apply_constraint_overrides(make_score(), Level.MEDIUM, policy)
        assert applied, f"{text!r} changed the portfolio but recorded no override"
        assert policy.describe(), text


def test_compliance_override_caps_high_risk() -> None:
    score = make_score(4, 4, 4)
    new_score, new_risk, applied = apply_constraint_overrides(
        score, Level.HIGH, parse_constraint_policy("compliance:heavy")
    )
    assert new_risk is Level.MEDIUM
    assert new_score == score
    assert any("compliance" in note for note in applied)


def test_no_coding_override_caps_ease() -> None:
    new_score, _, applied = apply_constraint_overrides(
        make_score(4, 4, 5), Level.LOW, parse_constraint_policy("no custom dev")
    )
    assert new_score.ease == 4
    assert any("no-coding" in note for note in applied)


def test_no_overrides_for_unconstrained_run() -> None:
    policy = parse_constraint_policy("budget:high")
    _, risk, applied = apply_constraint_overrides(make_score(), Level.LOW, policy)
    assert risk is Level.LOW
    assert applied == []
    assert not policy.active


def test_ease_first_detection() -> None:
    assert ease_first("urgent rollout")
    assert ease_first("needed in 1 week")
    assert not ease_first("budget:low")


# ---------------------------------------------------------------------------
# Strategic filters
# ---------------------------------------------------------------------------
