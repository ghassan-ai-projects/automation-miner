"""Deterministic ICE math, constraint overrides, strategic filters, ranking.

Everything here is pure code — the LLM proposes scores with rationale, these
functions validate bounds, compute ICE, apply the spec's constraint override
rules, and bucket opportunities into action tiers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from automation_miner.schemas import ICEScore, Layer, Level, Opportunity

SCORE_MIN = 1
SCORE_MAX = 5


@dataclass(frozen=True)
class ConstraintPolicy:
    """Deterministic policy flags parsed from the documented free-form syntax."""

    low_budget: bool = False
    no_coding: bool = False
    compliance: bool = False
    urgent: bool = False
    no_infrastructure: bool = False
    mature_stack: bool = False
    agent_limit: int | None = None


def parse_constraint_policy(constraints: str) -> ConstraintPolicy:
    """Recognize stable constraint phrases without pretending to understand arbitrary prose."""
    text = constraints.casefold()
    agent_match = re.search(r"agent[\s_-]*limit\s*[:=]?\s*(\d+)", text)
    team_match = re.search(r"team\s*[:=]?\s*([1-3])(?:\D|$)", text)
    agent_limit = int(agent_match.group(1)) if agent_match else None
    if agent_limit is None and "agent limit" in text:
        agent_limit = 1
    if agent_limit is None and ("small team" in text or team_match):
        agent_limit = 2
    return ConstraintPolicy(
        low_budget=bool(
            re.search(r"budget\s*[:=]?\s*(?:low|zero)", text)
            or "no budget" in text
        ),
        no_coding="no coding" in text or "no custom dev" in text,
        compliance="compliance" in text or "regulated" in text,
        urgent=bool(
            "urgent" in text
            or "1 week" in text
            or "tight timeline" in text
            or re.search(r"timeline\s*[:=]?\s*tight", text)
        ),
        no_infrastructure="no existing infrastructure" in text,
        mature_stack="existing mature stack" in text or "mature stack" in text,
        agent_limit=agent_limit,
    )


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
    return parse_constraint_policy(constraints).urgent


def strategic_filters(opp: Opportunity) -> dict[str, bool]:
    """The three strategic filters from the spec, applied in order."""
    s = opp.score
    return {
        "low_hanging": s.ease >= 4 and s.impact >= 3,
        "high_value": opp.ice >= 40 and opp.draft.risk_level.rank <= Level.MEDIUM.rank,
        "vision": s.impact == 5 and s.ease <= 2,
    }


def rank(opportunities: list[Opportunity], constraints: str = "") -> list[Opportunity]:
    """Apply hard portfolio constraints, then sort according to the active policy."""
    policy = parse_constraint_policy(constraints)
    eligible = list(opportunities)

    if policy.low_budget or policy.no_coding:
        eligible = [o for o in eligible if o.score.ease >= 4]
    if policy.compliance:
        eligible = [o for o in eligible if o.draft.risk_level != Level.HIGH]
    if policy.no_infrastructure:
        eligible = [
            o for o in eligible if o.draft.layer in {Layer.DOCUMENT, Layer.KNOWLEDGE}
        ]
    if policy.mature_stack:
        eligible = [
            o
            for o in eligible
            if o.draft.layer in {Layer.COMMUNICATION, Layer.DECISION, Layer.MONITORING}
        ]
    if policy.agent_limit is not None:
        eligible = [
            o
            for o in eligible
            if (_agent_count(o.draft.agents_required) or 1) <= policy.agent_limit
        ]

    if policy.urgent:
        ranked = sorted(
            eligible,
            key=lambda o: (o.score.ease, o.ice),
            reverse=True,
        )
        return ranked[:3]
    return sorted(eligible, key=lambda o: o.ice, reverse=True)


def _agent_count(description: str) -> int | None:
    match = re.search(r"\b(\d+)\b", description)
    return int(match.group(1)) if match else None
