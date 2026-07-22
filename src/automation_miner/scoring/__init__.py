"""Deterministic ICE math, constraint overrides, strategic filters, ranking.

Everything here is pure code — the LLM proposes scores with rationale, these
functions validate bounds, compute ICE, apply the spec's constraint override
rules, and bucket opportunities into action tiers.
"""

from __future__ import annotations

from automation_miner.schemas import ICEScore, Level, Opportunity

SCORE_MIN = 1
SCORE_MAX = 5


def validate_score(value: int) -> int:
    """Clamp an ICE factor into the valid 1-5 range (calibration)."""
    return max(SCORE_MIN, min(SCORE_MAX, int(value)))


def compute_ice(impact: int, confidence: int, ease: int) -> int:
    """ICE = Impact x Confidence x Ease, range 1-125."""
    return (
        validate_score(impact) * validate_score(confidence) * validate_score(ease)
    )


def calibrate(score: ICEScore) -> ICEScore:
    """Return a copy of the score with every factor clamped to 1-5."""
    return score.model_copy(
        update={
            "impact": validate_score(score.impact),
            "confidence": validate_score(score.confidence),
            "ease": validate_score(score.ease),
        }
    )


def apply_constraint_overrides(
    score: ICEScore, risk: Level, constraints: str
) -> tuple[ICEScore, Level, list[str]]:
    """Apply the spec's Constraint Override Rules to a score/risk pair.

    Returns the (possibly adjusted) score, risk, and the list of applied rules.
    """
    text = constraints.lower()
    applied: list[str] = []

    if "compliance" in text or "regulated" in text:
        if risk == Level.HIGH:
            risk = Level.MEDIUM
            applied.append("compliance: risk hard-capped at Medium (flagged for review)")
        else:
            applied.append("compliance: risk cap active")

    if "no coding" in text or "no custom dev" in text:
        if score.ease > 4:
            score = score.model_copy(update={"ease": 4})
        applied.append("no-coding: ease capped at 4 (configuration-level only)")

    if "agent limit" in text:
        applied.append("agent-limit: multi-agent spots rerouted to single-agent with queuing")

    if "urgent" in text or "1 week" in text:
        applied.append("urgent: ranking by Ease first (quick wins)")

    return score, risk, applied


def ease_first(constraints: str) -> bool:
    """Whether constraints force Ease-first ranking (urgent / 1 week)."""
    text = constraints.lower()
    return "urgent" in text or "1 week" in text


def strategic_filters(opp: Opportunity) -> dict[str, bool]:
    """The three strategic filters from the spec, applied in order."""
    s = opp.score
    return {
        "low_hanging": s.ease >= 4 and s.impact >= 3,
        "high_value": opp.ice >= 40 and opp.draft.risk_level.rank <= Level.MEDIUM.rank,
        "vision": s.impact == 5 and s.ease <= 2,
    }


def rank(opportunities: list[Opportunity], constraints: str = "") -> list[Opportunity]:
    """Sort by ICE descending; with urgent constraints, Ease first then ICE."""
    if ease_first(constraints):
        return sorted(
            opportunities,
            key=lambda o: (o.score.ease, o.ice),
            reverse=True,
        )
    return sorted(opportunities, key=lambda o: o.ice, reverse=True)
