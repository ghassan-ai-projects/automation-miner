"""Hard portfolio exclusions: quality gates and every constraint policy rule.

Each rule returns its own reasons, so an excluded opportunity always says
exactly why — and nothing is filtered without a recorded reason.
"""

from __future__ import annotations

import re

from automation_miner.schemas import PUBLICATION_QUALITY_FLOOR, Layer, Level, Opportunity
from automation_miner.scoring.policy import ConstraintPolicy

EXTERNAL_CHANNELS = ("email-to-sms", "sms gateway", "carrier gateway", "twilio")
_AUTONOMOUS_PAYMENT = re.compile(
    r"\b(?:automat(?:e|ed|ically)|autonom(?:ous|ously))"
    r".{0,30}\b(?:release|execute|send|initiate).{0,15}\bpayment"
)


def _draft_text(opp: Opportunity) -> str:
    d = opp.draft
    return " ".join(
        [d.proposed_automation, *d.steps, *d.outputs, *d.technical_requirements, *d.dependencies]
    ).casefold()


def quality_exclusions(opp: Opportunity) -> list[str]:
    reasons: list[str] = []
    if opp.unresolved_refs:
        reasons.append(
            "grounding: cited evidence ids do not resolve: "
            + ", ".join(sorted(opp.unresolved_refs))
        )
    reasons.extend(f"quality gate: {reason}" for reason in opp.quality_gate_reasons)
    if opp.critique_overall < PUBLICATION_QUALITY_FLOOR:
        reasons.append(
            f"critic score {opp.critique_overall:g} is below the "
            f"{PUBLICATION_QUALITY_FLOOR:g} inspiration quality floor after "
            f"{opp.iterations} iteration{'s' if opp.iterations != 1 else ''}"
        )
    return reasons


def scope_exclusions(opp: Opportunity, policy: ConstraintPolicy) -> list[str]:
    reasons: list[str] = []
    ease, layer = opp.score.ease, opp.draft.layer
    if policy.low_budget and ease < 4:
        reasons.append(f"budget low/zero requires Ease >= 4 (has {ease})")
    if policy.no_coding and ease < 4:
        reasons.append(f"no-coding requires Ease >= 4 (has {ease})")
    if policy.compliance and (opp.source_risk_level or opp.draft.risk_level) is Level.HIGH:
        reasons.append("compliance excludes unresolved high-risk items")
    if policy.no_infrastructure and layer not in {Layer.DOCUMENT, Layer.KNOWLEDGE}:
        reasons.append(
            f"no existing infrastructure limits to Document/Knowledge (is {layer.value})"
        )
    if policy.mature_stack and layer not in {Layer.COMMUNICATION, Layer.DECISION, Layer.MONITORING}:
        reasons.append(
            f"existing mature stack limits to Communication/Decision/Monitoring (is {layer.value})"
        )
    if policy.agent_limit is not None and opp.draft.agent_count > policy.agent_limit:
        reasons.append(f"agent limit {policy.agent_limit} exceeded (needs {opp.draft.agent_count})")
    return reasons


def residency_exclusions(opp: Opportunity) -> list[str]:
    declared = opp.draft.external_data_channels
    reasons: list[str] = []
    unverified = [channel.name for channel in declared if not channel.eu_hosting_verified]
    if unverified:
        reasons.append(
            "EU data residency excludes unverified external data channel(s): "
            + ", ".join(unverified)
        )
    text = _draft_text(opp)
    proposed = next((channel for channel in EXTERNAL_CHANNELS if channel in text), "")
    if proposed and not declared:
        reasons.append(
            "EU data residency requires a structured verified channel declaration; "
            f"unstructured external data channel {proposed!r}"
        )
    return reasons


def payment_exclusions(opp: Opportunity) -> list[str]:
    actions = opp.draft.payment_actions
    if actions:
        reasons = []
        if any(not action.human_approval_required for action in actions):
            reasons.append("payments require an explicit human approval checkpoint")
        if any(action.autonomous for action in actions):
            reasons.append("payments may not be released autonomously")
        return reasons
    hitl = " ".join(opp.draft.hitl_points).casefold()
    text = _draft_text(opp)
    reasons = []
    if not (
        ("payment" in hitl or "invoice" in hitl) and re.search(r"\b(?:human|review|approv)", hitl)
    ):
        reasons.append("payments require an explicit human approval checkpoint")
    if _AUTONOMOUS_PAYMENT.search(text):
        reasons.append("payments may not be released autonomously")
    if "payment" in text or "invoice" in text:
        reasons.append("payment actions require a structured declaration")
    return reasons


def exclusions(opp: Opportunity, policy: ConstraintPolicy) -> list[str]:
    """Every reason this opportunity fails the hard portfolio constraints."""
    reasons = quality_exclusions(opp) + scope_exclusions(opp, policy)
    if policy.eu_data_residency:
        reasons += residency_exclusions(opp)
    if policy.human_payment_approval:
        reasons += payment_exclusions(opp)
    return reasons
