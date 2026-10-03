"""ICE math and coherence validation. Adjustments only ever lower a factor."""

from __future__ import annotations

from typing import Iterable

from automation_miner.scoring.policy import ConstraintPolicy
from automation_miner.schemas import ICEScore, Level, OpportunityDraft

SCORE_MIN = 1
SCORE_MAX = 5


def validate_score(value: int) -> int:
    """Clamp an ICE factor into the valid 1-5 range."""
    return max(SCORE_MIN, min(SCORE_MAX, int(value)))


def compute_ice(impact: int, confidence: int, ease: int) -> int:
    """ICE = Impact x Confidence x Ease, range 1-125."""
    return validate_score(impact) * validate_score(confidence) * validate_score(ease)


# Maximum Ease that each effort level can justify (spec Phase 3 ladder:
# High effort is a 1-4 week integration, which cannot also be "already have the
# tools"). ``None`` means no ceiling.
_EFFORT_EASE_CEILING: dict[Level, int] = {Level.HIGH: 2, Level.MEDIUM: 4}
# Maximum Impact each impact_estimate can justify.
_ESTIMATE_IMPACT_CEILING: dict[Level, int] = {Level.LOW: 2, Level.MEDIUM: 4}
# High risk contradicts maximum confidence.
_RISK_CONFIDENCE_CEILING: dict[Level, int] = {Level.HIGH: 4}
# A draft with no quantified impact rows cannot support high confidence.
_UNQUANTIFIED_CONFIDENCE_CEILING = 3
# A draft citing no evidence is an inference, not a validated pattern.
_UNGROUNDED_CONFIDENCE_CEILING = 3


def _cap_ease(ease: int, draft: OpportunityDraft, notes: list[str]) -> int:
    ceiling = _EFFORT_EASE_CEILING.get(draft.effort)
    if ceiling is not None and ease > ceiling:
        notes.append(f"ease {ease} -> {ceiling}: incompatible with {draft.effort.value} effort")
        return ceiling
    if draft.effort is Level.LOW and ease <= 2:
        notes.append(f"flagged: ease {ease} is pessimistic for low effort (left unchanged)")
    return ease


def _cap_impact(impact: int, draft: OpportunityDraft, notes: list[str]) -> int:
    ceiling = _ESTIMATE_IMPACT_CEILING.get(draft.impact_estimate)
    if ceiling is not None and impact > ceiling:
        notes.append(
            f"impact {impact} -> {ceiling}: exceeds the draft's "
            f"{draft.impact_estimate.value} impact estimate"
        )
        return ceiling
    if draft.impact_estimate is Level.HIGH and impact <= 2:
        notes.append(
            f"flagged: impact {impact} contradicts a high impact estimate (left unchanged)"
        )
    return impact


def _cap_confidence(confidence: int, draft: OpportunityDraft, notes: list[str]) -> int:
    rules = (
        (_RISK_CONFIDENCE_CEILING.get(draft.risk_level), "high risk implies residual uncertainty"),
        (
            None if draft.impact_analysis else _UNQUANTIFIED_CONFIDENCE_CEILING,
            "no quantified impact rows",
        ),
        (
            None if draft.evidence_refs else _UNGROUNDED_CONFIDENCE_CEILING,
            "draft cites no evidence",
        ),
    )
    for ceiling, reason in rules:
        if ceiling is not None and confidence > ceiling:
            notes.append(f"confidence {confidence} -> {ceiling}: {reason}")
            confidence = ceiling
    return confidence


def validate_coherence(
    score: ICEScore, draft: OpportunityDraft, unresolved_refs: Iterable[str] = ()
) -> tuple[ICEScore, list[str]]:
    """Cross-check LLM factors against the draft's own estimates.

    Returns the adjusted score and a note per adjustment or flagged
    inconsistency. Adjustments only ever lower a factor.
    """
    notes: list[str] = []
    ease = _cap_ease(score.ease, draft, notes)
    impact = _cap_impact(score.impact, draft, notes)
    confidence = _cap_confidence(score.confidence, draft, notes)
    unresolved = sorted(unresolved_refs)
    if unresolved:
        notes.append(f"flagged: cited evidence ids do not exist: {', '.join(unresolved)}")
    if (impact, confidence, ease) == (score.impact, score.confidence, score.ease):
        return score, notes
    update = {"impact": impact, "confidence": confidence, "ease": ease}
    return score.model_copy(update=update), notes


# Rules that change nothing in the score but are recorded on every brief.
_POLICY_NOTES: tuple[tuple[str, str], ...] = (
    ("urgent", "urgent: ranking by Ease first (quick wins)"),
    ("low_budget", "budget low/zero: only existing-tool, config-level work eligible"),
    ("eu_data_residency", "EU data residency: external data channels require verified EU hosting"),
    ("human_payment_approval", "payments: explicit human approval required"),
)


def apply_constraint_overrides(
    score: ICEScore, risk: Level, policy: ConstraintPolicy
) -> tuple[ICEScore, Level, list[str]]:
    """Apply the spec's Constraint Override Rules to a score/risk pair.

    Returns the (possibly adjusted) score, risk, and the list of applied rules.
    """
    applied: list[str] = []
    if policy.compliance:
        applied.append(
            "compliance: risk hard-capped at Medium (flagged for review)"
            if risk is Level.HIGH
            else "compliance: risk cap active"
        )
        risk = Level.MEDIUM if risk is Level.HIGH else risk
    if policy.no_coding:
        applied.append(
            "no-coding: ease capped at 4 (configuration-level only)"
            if score.ease > 4
            else "no-coding: configuration-level only"
        )
        score = score.model_copy(update={"ease": min(score.ease, 4)})
    if policy.agent_limit is not None:
        applied.append(
            f"agent-limit {policy.agent_limit}: multi-agent spots rerouted to single-agent with queuing"
        )
    applied += [note for flag, note in _POLICY_NOTES if getattr(policy, flag)]
    return score, risk, applied


def evidence_confidence_cap(
    draft: OpportunityDraft, input_level: str, analysis_mode: str
) -> tuple[int, str]:
    """The highest Confidence the evidence behind one brief can justify.

    Confidence is about whether the value is real. A model rates its own
    brief's premise generously; code knows how much of the brief rests on
    observed numbers and how rich the input was, so it bounds the factor.
    """
    if input_level == "thin":
        return 2, "thin input: the problem itself is not observed"
    if not any(not row.assumption for row in draft.impact_analysis):
        return 3, "no impact row rests on an observed baseline"
    if analysis_mode == "strategy":
        return 3, "strategy evidence states intent, not observed operations"
    return SCORE_MAX, ""


def apply_confidence_cap(score: ICEScore, cap: int, reason: str) -> tuple[ICEScore, list[str]]:
    if score.confidence <= cap:
        return score, []
    note = f"confidence {score.confidence} -> {cap}: {reason}"
    return score.model_copy(update={"confidence": cap}), [note]


def artifact_type_for(
    score: ICEScore, draft: OpportunityDraft, input_level: str, analysis_mode: str
) -> str:
    """Decide once, in code, whether a brief is ready or a discovery hypothesis.

    Thin input, strategy material, low confidence, or no cited evidence all
    mean the current state has not been observed: the brief must lead with
    what to validate rather than read as an implementation plan.
    """
    if (
        input_level == "thin"
        or analysis_mode == "strategy"
        or score.confidence <= 2
        or not draft.evidence_refs
    ):
        return "discovery_hypothesis"
    return "opportunity_brief"
