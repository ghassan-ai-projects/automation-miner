"""Portfolio policy: strategic filters, hard exclusions, total ordering, stats."""

from __future__ import annotations

import statistics
from collections.abc import Mapping
from typing import Iterable

from automation_miner.schemas import (
    Eligibility,
    Level,
    Opportunity,
    PortfolioStats,
    Tier,
)
from automation_miner.scoring.exclusions import exclusions
from automation_miner.scoring.policy import (
    URGENT_PORTFOLIO_SIZE,
    ConstraintPolicy,
    parse_constraint_policy,
)

FILTER_KEYS = ("low_hanging", "high_value", "vision")


def ease_first(constraints: str, constraint_params: Mapping[str, str] | None = None) -> bool:
    """Whether constraints force Ease-first ranking (urgent / tight timeline)."""
    return parse_constraint_policy(constraints, constraint_params).urgent


def strategic_filters(opp: Opportunity) -> dict[str, bool]:
    """The three strategic filters from the spec, applied in order."""
    s = opp.score
    return {
        "low_hanging": s.ease >= 4 and s.impact >= 3,
        "high_value": opp.ice >= 40 and opp.draft.risk_level.rank <= Level.MEDIUM.rank,
        "vision": s.impact == 5 and s.ease <= 2,
    }


def active_filters(opp: Opportunity) -> list[str]:
    return [key for key, active in strategic_filters(opp).items() if active]


def sort_key(opp: Opportunity, urgent: bool = False) -> tuple[object, ...]:
    """Total ordering over opportunities.

    Ties at equal ICE are the common case, not the exception — five layers
    scoring 4/4/4 all land on 64. A single-key sort left their order to upstream
    insertion, so the ranking was not reproducible. Every tie is broken here,
    ending with ``am_id`` so the order is total.
    """
    if urgent:
        return (
            -opp.score.ease,
            -opp.ice,
            -opp.score.impact,
            -opp.critique_overall,
            opp.am_id,
        )
    return (
        -opp.ice,
        -opp.score.impact,
        -opp.score.ease,
        -opp.score.confidence,
        -opp.critique_overall,
        opp.am_id,
    )


def _urgent_cut(marked: list[Opportunity]) -> list[Opportunity]:
    """Under an urgent timeline only the top few eligible opportunities publish."""
    result: list[Opportunity] = []
    rank = 0
    for opp in marked:
        if opp.published:
            rank += 1
            if rank > URGENT_PORTFOLIO_SIZE:
                reason = (
                    f"urgent timeline publishes only the top {URGENT_PORTFOLIO_SIZE} "
                    f"by Ease then ICE (ranked {rank})"
                )
                opp = opp.model_copy(
                    update={
                        "eligibility": Eligibility.FILTERED,
                        "exclusion_reasons": [*opp.exclusion_reasons, reason],
                    }
                )
        result.append(opp)
    return result


def apply_portfolio_policy(
    opportunities: list[Opportunity],
    constraints: str = "",
    constraint_params: Mapping[str, str] | None = None,
    *,
    policy: ConstraintPolicy | None = None,
) -> list[Opportunity]:
    """Rank and mark eligibility, retaining every opportunity.

    A resolved ``policy`` (the run's, see ``context_policy``) wins over
    re-parsing ``constraints`` and ``constraint_params``.

    Returns published opportunities in rank order, followed by filtered ones in
    rank order. Nothing is discarded: a filtered opportunity was still drafted,
    critiqued, refined and scored, and the operator paid for it.
    """
    policy = policy or parse_constraint_policy(constraints, constraint_params)
    marked = []
    for opp in sorted(opportunities, key=lambda o: sort_key(o, policy.urgent)):
        reasons = exclusions(opp, policy)
        eligibility = Eligibility.FILTERED if reasons else Eligibility.PUBLISHED
        marked.append(
            opp.model_copy(update={"eligibility": eligibility, "exclusion_reasons": reasons})
        )
    if policy.urgent:
        marked = _urgent_cut(marked)
    return [o for o in marked if o.published] + [o for o in marked if not o.published]


def published(opportunities: Iterable[Opportunity]) -> list[Opportunity]:
    return [o for o in opportunities if o.published]


def filtered(opportunities: Iterable[Opportunity]) -> list[Opportunity]:
    return [o for o in opportunities if not o.published]


def portfolio_stats(opportunities: list[Opportunity]) -> PortfolioStats:
    """Deterministic portfolio shape over the published set."""
    live = published(opportunities)
    ices = [o.ice for o in live]
    by_layer: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    for opp in live:
        by_layer[opp.draft.layer.value] = by_layer.get(opp.draft.layer.value, 0) + 1
        by_tier[opp.tier.value] = by_tier.get(opp.tier.value, 0) + 1
    # sort_key negates the descending fields, so the best-ranked entry is the minimum.
    top = min(live, key=sort_key) if live else None
    return PortfolioStats(
        total=len(opportunities),
        published=len(live),
        filtered=len(opportunities) - len(live),
        by_layer=by_layer,
        by_tier=by_tier,
        avg_ice=round(sum(ices) / len(ices), 1) if ices else 0.0,
        median_ice=round(statistics.median(ices), 1) if ices else 0.0,
        top_ice=max(ices) if ices else 0,
        top_id=top.am_id if top else "",
        filters={key: [o.am_id for o in live if strategic_filters(o)[key]] for key in FILTER_KEYS},
    )


def tier_for(ice: int) -> Tier:
    """Convenience re-export so callers need not import the schema enum."""
    return Tier.for_ice(ice)
