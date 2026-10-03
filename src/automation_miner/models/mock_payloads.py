"""Canned, schema-valid payloads for the deterministic mock provider."""

from __future__ import annotations

import copy
import re
from typing import Any

# Judge payloads live apart so this module stays within the file-size limit.
from automation_miner.models.mock_judge import (  # noqa: F401
    brief_judgement,
    claim_audit,
    portfolio_judgement,
)

_TITLE_RE = re.compile(r'"title"\s*:\s*"([^"]+)"')
_IDEAS_RE = re.compile(r"^-\s*ideas\s*=\s*(\d+)\s*$", re.MULTILINE | re.IGNORECASE)
_AM_ID_RE = re.compile(r'"am_id"\s*:\s*"(AM-\d+)"')
LAYERS = ("document", "communication", "decision", "monitoring", "knowledge")


_DOMAIN_MAP_STATIC: dict[str, Any] = {
    "analysis_mode": "operational",
    "core_function": "Deliver the domain's core service through coordinated operational work.",
    "stakeholders": ["Operations team", "Customers", "Management", "Regulators"],
    "information_flow": (
        "Documents, approvals, and status reports move between teams "
        "via email and shared systems."
    ),
    "decision_density": "Dozens of rule-based decisions per day, some judgment calls.",
    "compliance_surface": "Standard industry regulations with audit trail requirements.",
    "technology_maturity": "Mix of ERP/CRM systems, spreadsheets, and manual steps.",
    "scale_indicators": "Hundreds of transactions and recurring reports per week.",
    "manual_friction": [
        "Manual data entry between systems",
        "Recurring template-based reports",
        "Email-based status chasing",
    ],
    "workflow_patterns": "Weekly reporting cycle with a month-end crunch.",
    "stated_gaps": [],
    "proposed_initiatives": [],
    "benchmarks": [],
    "unknowns": [],
}
_STAKEHOLDERS = (
    ("Operations team", ["Intake", "Validation", "Service delivery", "Reporting"]),
    ("Customers", ["Request submission", "Review"]),
    ("Management", ["Approval", "Performance review"]),
    ("Regulators", ["Audit", "Compliance review"]),
)


def input_assessment(refs: list[str]) -> dict[str, Any]:
    return {
        "recommended_mode": "operational",
        "source_type": "operational evidence",
        "rationale": "The source describes recurring work.",
        "operational_evidence_refs": refs,
        "strategic_evidence_refs": [],
        "evidence_gaps": [],
    }


def domain_map(refs: list[str]) -> dict[str, Any]:
    evidence_refs = refs[:1] or ["S1"]
    return {
        **copy.deepcopy(_DOMAIN_MAP_STATIC),
        "stakeholder_processes": [
            {"stakeholder": who, "processes": list(processes), "evidence_refs": evidence_refs}
            for who, processes in _STAKEHOLDERS
        ],
        "verified_current_state": [
            {"claim": "Recurring operational work is described.", "evidence_refs": evidence_refs}
        ],
    }


def _pain(text: str, refs: list[str], volume: float | None, minutes: float | None,
          other: str) -> dict[str, Any]:
    return {
        "pain": text, "who": "Operations team", "volume_per_week": volume,
        "minutes_per_item": minutes, "other_cost": other, "observed": False,
        "evidence_refs": refs,
    }


def layer_analysis(layer: str, refs: list[str]) -> dict[str, Any]:
    return {
        "layer": layer,
        "findings": [
            f"The {layer} layer relies on recurring manual work between systems.",
            f"Existing tools cover part of the {layer} workflow but are not integrated.",
        ],
        "pain_points": [
            _pain(f"Repetitive manual handling in the {layer} layer", refs, 400.0, 6.0, ""),
            _pain(f"Errors introduced at {layer} handoff points", refs, None, None,
                  "Rework on about 5% of items"),
        ],
        "pain_level": "high",
        "evidence_refs": refs,
    }


def candidate_portfolio(refs: list[str], prompt: str) -> dict[str, Any]:
    count_match = _IDEAS_RE.search(prompt)
    count = max(1, min(12, int(count_match.group(1)))) if count_match else 5
    layers = [LAYERS[index % len(LAYERS)] for index in range(count)]
    return {
        "candidates": [
            {
                "layer": layer,
                "title": f"High-Value {layer.title()} Opportunity {index + 1}",
                "value_thesis": f"Create distinct value through the {layer} layer.",
                "why_now": "The supplied evidence makes this timely.",
                "differentiation": (
                    f"Candidate {index + 1} focuses uniquely on {layer}, "
                    "not generic documentation."
                ),
                "addresses_pains": [f"P{index + 1}"],
                "evidence_refs": refs,
            }
            for index, layer in enumerate(layers)
        ]
    }


# Every field of the canned draft that does not depend on the prompt.
_DRAFT_STATIC: dict[str, Any] = {
    "inputs": [
        "Source records from the primary system of record",
        "Domain rules and templates",
    ],
    "steps": [
        "Collect new inputs on a schedule or trigger",
        "Validate and normalize the data",
        "Apply business rules and generate the output",
        "Route exceptions to a human reviewer",
        "Log every action for audit",
    ],
    "outputs": [
        "Generated artifact delivered to the consumer",
        "Exception queue with reasons",
        "Audit log entries",
    ],
    "hitl_points": [
        "Review of low-confidence or out-of-policy cases",
        "Weekly sampling of automated outputs",
    ],
    "dependencies": [
        "API credentials for the source system",
        "Agreed business rules from the process owner",
    ],
    "constraints": [
        "Must respect the domain's compliance and audit requirements",
    ],
    "impact_analysis": [
        {
            "dimension": "Time",
            "current": "5 hours/week manual handling",
            "automated": "30 minutes/week review",
            "improvement": "90%",
            "basis": "Assumption to validate during discovery",
            "assumption": True,
        },
        {
            "dimension": "Error rate",
            "current": "~5% rework",
            "automated": "<1% with validation",
            "improvement": "80%",
            "basis": "Assumption to validate during discovery",
            "assumption": True,
        },
    ],
    "implementation": {
        "mvp": [
            "Automate the 80% standard case end to end",
            "Deploy alongside the manual process",
        ],
        "expansion": [
            "Cover edge cases and exception handling",
            "Add monitoring dashboard",
        ],
        "autonomy": [
            "Reduce HITL to exception-only",
            "Self-healing retries and escalation",
        ],
    },
    "risks": [
        {
            "risk": "Source data quality degrades",
            "likelihood": "medium",
            "impact": "medium",
            "mitigation": "Input validation with human fallback queue",
        },
        {
            "risk": "Rule drift as the process evolves",
            "likelihood": "medium",
            "impact": "low",
            "mitigation": "Quarterly rule review with the process owner",
        },
    ],
    "agent_count": 1,
    "agent_topology": "single agent with a rule-checking tool",
    "effort": "medium",
    "impact_estimate": "high",
    "risk_level": "medium",
    "assumptions": ["Current effort and error-rate baselines require validation."],
    "validation_questions": ["What are the measured weekly effort and rework rate?"],
    "success_metrics": [
        "Manual handling time per item: baseline from a one-week time study, target -50%",
        "Exception rate routed to humans: target below 20% after two weeks",
    ],
}
_PROBLEM = (
    "Teams handle the {layer} workflow manually: work is copy-pasted between systems, "
    "reviewed by email, and re-entered on change, costing several hours per week and "
    "causing avoidable errors."
)
_AUTOMATION = (
    "{agent} that watches the {layer} inputs, applies the domain rules, produces the "
    "standard output artifact, and routes exceptions to a human."
)
_BASE_REQUIREMENTS = [
    "API access to the primary system of record",
    "LLM with tool calling",
    "Persistent storage for logs and outputs",
]


def draft(layer: str, refs: list[str], prompt: str = "") -> dict[str, Any]:
    title_match = _TITLE_RE.search(prompt)
    title = (
        title_match.group(1)
        if title_match
        else f"Automated {layer.replace('_', ' ').title()} Workflow"
    )
    openclaw = "agent = openclaw" in prompt.casefold()
    agent_label = "An OpenClaw agent" if openclaw else "An agent"
    return {
        **copy.deepcopy(_DRAFT_STATIC),
        "layer": layer,
        "title": title,
        "problem": _PROBLEM.format(layer=layer),
        "proposed_automation": _AUTOMATION.format(agent=agent_label, layer=layer),
        "technical_requirements": [
            *(["OpenClaw agent runtime"] if openclaw else []), *_BASE_REQUIREMENTS
        ],
        "evidence_refs": refs,
    }


def critique() -> dict[str, Any]:
    return {
        "groundedness": 8,
        "specificity": 8,
        "quantified_impact": 8,
        "feasibility": 8,
        "hitl_clarity": 8,
        "differentiation": 8,
        "grounding_violations": [],
        "constraint_violations": [],
        "feedback": "Draft is grounded, specific, and quantified. Approved.",
    }


def ice() -> dict[str, Any]:
    return {
        "impact": 4,
        "confidence": 4,
        "ease": 4,
        "impact_rationale": (
            "Cross-department shift: the same workflow blocks operations and reporting."
        ),
        "confidence_rationale": "Adjacent domain proven: this pattern ships elsewhere.",
        "ease_rationale": "Configuration plus API wiring against an existing system of record.",
    }


def portfolio_scores(prompt: str) -> dict[str, Any]:
    ids = list(dict.fromkeys(_AM_ID_RE.findall(prompt)))
    return {"scores": [{"am_id": am_id, **ice()} for am_id in ids]}


def repair_verdict() -> dict[str, Any]:
    return {"unresolved": [], "new_violations": []}
