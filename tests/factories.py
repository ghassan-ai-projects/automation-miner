"""Object factories for tests.

Opportunities have a lot of required structure, and most tests care about three
numbers. These build coherent defaults so a test that wants incoherence has to
ask for it explicitly.
"""

from __future__ import annotations

from typing import Any

from automation_miner.schemas import (
    ICEScore,
    Layer,
    Level,
    Opportunity,
    OpportunityDraft,
    Tier,
)


def make_score(impact: int = 4, confidence: int = 4, ease: int = 4) -> ICEScore:
    return ICEScore(
        impact=impact,
        confidence=confidence,
        ease=ease,
        impact_rationale="department-level transformation",
        confidence_rationale="adjacent domain proven",
        ease_rationale="config plus API wiring",
    )


def make_draft(**overrides: Any) -> OpportunityDraft:
    data: dict[str, Any] = {
        "layer": "document",
        "title": "Automated Intake",
        "problem": "Clerks re-key 400 claims/day between SAP and Excel.",
        "proposed_automation": "An agent extracts, validates, and files each claim.",
        "inputs": ["claim records"],
        "steps": ["extract", "validate", "file"],
        "outputs": ["filed claim"],
        "hitl_points": ["low-confidence cases"],
        "technical_requirements": ["SAP API"],
        "dependencies": ["API credentials"],
        "constraints": [],
        "impact_analysis": [
            {
                "dimension": "Time",
                "current": "5 h/week",
                "automated": "30 min/week",
                "improvement": "90%",
                "basis": "Measured process baseline",
                "assumption": False,
            }
        ],
        "implementation": {"mvp": ["m"], "expansion": ["e"], "autonomy": ["a"]},
        "risks": [],
        "agent_count": 1,
        "agent_topology": "single agent with a validation tool",
        "effort": "medium",
        "impact_estimate": "high",
        "risk_level": "medium",
        "evidence_refs": ["S1"],
        "assumptions": [],
        "validation_questions": ["Confirm the baseline with the process owner."],
    }
    data.update(overrides)
    return OpportunityDraft.model_validate(data)


def make_opportunity(
    am_id: str = "AM-001",
    impact: int = 4,
    confidence: int = 4,
    ease: int = 4,
    *,
    risk: Level = Level.MEDIUM,
    layer: Layer = Layer.DOCUMENT,
    critique: float = 8.0,
    draft: OpportunityDraft | None = None,
    **draft_overrides: Any,
) -> Opportunity:
    draft = draft or make_draft(
        layer=layer.value, risk_level=risk.value, title=f"Opp {am_id}", **draft_overrides
    )
    score = make_score(impact, confidence, ease)
    return Opportunity(
        am_id=am_id,
        domain="German healthcare back office",
        domain_slug="german-healthcare-back-office",
        draft=draft,
        score=score,
        ice=score.ice,
        tier=Tier.for_ice(score.ice),
        critique_overall=critique,
        iterations=1,
    )
