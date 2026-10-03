"""Portfolio policy: strategic filters, ranking, exclusions, statistics."""

from __future__ import annotations

from factories import make_opportunity

from automation_miner.schemas import Eligibility, Layer, Level
from automation_miner.scoring import (
    URGENT_PORTFOLIO_SIZE,
    active_filters,
    apply_portfolio_policy,
    filtered,
    portfolio_stats,
    published,
    sort_key,
    strategic_filters,
)


def _ids(opportunities: list) -> list[str]:
    return [o.am_id for o in opportunities]


# ---------------------------------------------------------------------------
# Math
# ---------------------------------------------------------------------------


def test_strategic_filters() -> None:
    low_hanging = make_opportunity("AM-001", 3, 2, 4)
    assert strategic_filters(low_hanging) == {
        "low_hanging": True,
        "high_value": False,
        "vision": False,
    }

    high_value = make_opportunity("AM-002", 4, 4, 4, risk=Level.MEDIUM)
    flags = strategic_filters(high_value)
    assert flags["high_value"] and flags["low_hanging"] and not flags["vision"]

    risky = make_opportunity("AM-003", 5, 5, 3, risk=Level.HIGH)
    assert not strategic_filters(risky)["high_value"]

    vision = make_opportunity("AM-004", 5, 1, 2)
    assert strategic_filters(vision)["vision"]
    assert active_filters(vision) == ["vision"]


# ---------------------------------------------------------------------------
# Ranking and eligibility
# ---------------------------------------------------------------------------


def test_rank_by_ice_desc() -> None:
    opps = [
        make_opportunity("AM-001", 3, 3, 3),
        make_opportunity("AM-002", 5, 5, 5),
        make_opportunity("AM-003", 4, 4, 4),
    ]
    assert _ids(apply_portfolio_policy(opps)) == ["AM-002", "AM-003", "AM-001"]


def test_equal_ice_ties_break_deterministically() -> None:
    """Five layers at 4/4/4 all land on ICE 64; insertion order must not decide."""
    opps = [
        make_opportunity("AM-009", 4, 4, 4),
        make_opportunity("AM-007", 4, 4, 4),
        make_opportunity("AM-008", 4, 4, 4),
    ]
    assert _ids(apply_portfolio_policy(opps)) == ["AM-007", "AM-008", "AM-009"]
    assert _ids(apply_portfolio_policy(list(reversed(opps)))) == [
        "AM-007",
        "AM-008",
        "AM-009",
    ]


def test_tiebreak_prefers_impact_then_ease_at_equal_ice() -> None:
    by_impact = make_opportunity("AM-001", 5, 2, 4)  # ICE 40
    by_ease = make_opportunity("AM-002", 2, 4, 5)  # ICE 40
    assert sort_key(by_impact) < sort_key(by_ease)


def test_rank_ease_first_when_urgent() -> None:
    opps = [make_opportunity("AM-001", 5, 5, 2), make_opportunity("AM-002", 3, 3, 5)]
    assert _ids(published(apply_portfolio_policy(opps, "urgent")))[0] == "AM-002"
    assert _ids(apply_portfolio_policy(opps)) == ["AM-001", "AM-002"]


def test_urgent_policy_publishes_three_but_retains_the_rest() -> None:
    """Ranking used to delete the surplus; every scored opportunity is kept now."""
    opps = [make_opportunity(f"AM-{i:03d}", 3, 3, i) for i in range(1, 6)]
    ranked = apply_portfolio_policy(opps, "timeline:tight")

    assert len(ranked) == 5
    live = published(ranked)
    assert len(live) == URGENT_PORTFOLIO_SIZE
    assert [o.score.ease for o in live] == [5, 4, 3]
    for opp in filtered(ranked):
        assert opp.eligibility is Eligibility.FILTERED
        assert any("urgent timeline" in reason for reason in opp.exclusion_reasons)


def test_low_budget_policy_filters_low_ease_with_a_reason() -> None:
    opps = [make_opportunity("AM-001", 5, 5, 3), make_opportunity("AM-002", 3, 3, 4)]
    ranked = apply_portfolio_policy(opps, "budget:low")
    assert _ids(published(ranked)) == ["AM-002"]
    excluded = filtered(ranked)[0]
    assert excluded.am_id == "AM-001"
    assert "Ease >= 4" in excluded.exclusion_reasons[0]


def test_only_materially_weak_inspiration_is_not_published() -> None:
    weak = make_opportunity("AM-001", 5, 5, 5).model_copy(
        update={"critique_overall": 5.99, "iterations": 2}
    )
    strong = make_opportunity("AM-002", 3, 3, 3).model_copy(
        update={"critique_overall": 6.0}
    )

    ranked = apply_portfolio_policy([weak, strong])

    assert _ids(published(ranked)) == ["AM-002"]
    excluded = filtered(ranked)[0]
    assert excluded.am_id == "AM-001"
    assert excluded.exclusion_reasons == [
        "critic score 5.99 is below the 6 inspiration quality floor after 2 iterations"
    ]


def test_infrastructure_policy_limits_layers() -> None:
    document = make_opportunity("AM-001", 3, 3, 3, layer=Layer.DOCUMENT)
    monitoring = make_opportunity("AM-002", 3, 3, 3, layer=Layer.MONITORING)
    pool = [document, monitoring]
    assert _ids(published(apply_portfolio_policy(pool, "no existing infrastructure"))) == [
        "AM-001"
    ]
    assert _ids(published(apply_portfolio_policy(pool, "existing mature stack"))) == [
        "AM-002"
    ]


def test_compliance_policy_filters_high_risk() -> None:
    safe = make_opportunity("AM-001", 3, 3, 3, risk=Level.MEDIUM)
    risky = make_opportunity("AM-002", 5, 5, 5, risk=Level.HIGH)
    ranked = apply_portfolio_policy([safe, risky], "compliance:heavy")
    assert _ids(published(ranked)) == ["AM-001"]
    assert "high-risk" in filtered(ranked)[0].exclusion_reasons[0]


def test_agent_limit_uses_the_structured_count() -> None:
    """agents_required was free text parsed by first-integer regex."""
    single = make_opportunity("AM-001", 3, 3, 3, agent_count=1)
    swarm = make_opportunity("AM-002", 5, 5, 5, agent_count=3)
    ranked = apply_portfolio_policy([single, swarm], "agent limit: 1")
    assert _ids(published(ranked)) == ["AM-001"]
    assert "needs 3" in filtered(ranked)[0].exclusion_reasons[0]


def test_eu_residency_filters_unverified_external_messaging() -> None:
    unsafe = make_opportunity(
        "AM-001",
        3,
        3,
        4,
        technical_requirements=["Carrier email-to-SMS gateway"],
    )
    safe = make_opportunity(
        "AM-002",
        3,
        3,
        4,
        technical_requirements=["Microsoft Teams in the existing EU tenant"],
    )

    ranked = apply_portfolio_policy([unsafe, safe], "EU data residency")

    assert _ids(published(ranked)) == ["AM-002"]
    assert "email-to-sms" in filtered(ranked)[0].exclusion_reasons[0]


def test_payment_policy_requires_hitl_and_rejects_autonomous_release() -> None:
    safe = make_opportunity(
        "AM-001",
        3,
        3,
        4,
        hitl_points=["Partner reviews and approves every invoice payment"],
    )
    no_checkpoint = make_opportunity("AM-002", 3, 3, 4)
    autonomous = make_opportunity(
        "AM-003",
        3,
        3,
        4,
        hitl_points=["Partner reviews and approves every invoice payment"],
        steps=["Automatically release payment after validation"],
    )

    ranked = apply_portfolio_policy(
        [safe, no_checkpoint, autonomous], "payments require human approval"
    )

    assert _ids(published(ranked)) == ["AM-001"]
    reasons = {opp.am_id: opp.exclusion_reasons for opp in filtered(ranked)}
    assert any("checkpoint" in reason for reason in reasons["AM-002"])
    assert any("autonomously" in reason for reason in reasons["AM-003"])


def test_multiple_exclusion_reasons_accumulate() -> None:
    opp = make_opportunity(
        "AM-001", 5, 5, 2, risk=Level.HIGH, layer=Layer.MONITORING, agent_count=4
    )
    ranked = apply_portfolio_policy(
        [opp], "budget: low, compliance: heavy, no existing infrastructure, agent limit: 1"
    )
    assert len(ranked[0].exclusion_reasons) == 4


# ---------------------------------------------------------------------------
# Portfolio stats
# ---------------------------------------------------------------------------


def test_portfolio_stats_counts_only_published() -> None:
    opps = [
        make_opportunity("AM-001", 5, 5, 5, layer=Layer.DOCUMENT),
        make_opportunity("AM-002", 4, 4, 4, layer=Layer.DECISION),
        make_opportunity("AM-003", 3, 3, 3, layer=Layer.DOCUMENT),
    ]
    ranked = apply_portfolio_policy(opps, "budget:low")
    stats = portfolio_stats(ranked)

    assert stats.total == 3
    assert stats.published == 2
    assert stats.filtered == 1
    assert stats.by_layer == {"document": 1, "decision": 1}
    assert stats.by_tier == {"vision": 1, "high": 1}
    assert stats.top_ice == 125
    assert stats.top_id == "AM-001"
    assert stats.median_ice == 94.5
    assert stats.filters["low_hanging"] == ["AM-001", "AM-002"]


def test_portfolio_stats_on_empty_portfolio() -> None:
    stats = portfolio_stats([])
    assert stats.total == 0
    assert stats.avg_ice == 0.0
    assert stats.top_id == ""
