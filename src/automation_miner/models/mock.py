"""Deterministic mock provider — the whole graph runs offline against it.

Every role returns canned, schema-valid JSON. Content is fixed except that the
active layer is parsed out of the prompt so per-layer artifacts look sane.
"""

from __future__ import annotations

import re
from typing import Any

_LAYER_RE = re.compile(r"^Layer:\s*(\w+)", re.MULTILINE)

_LAYERS = ("document", "communication", "decision", "monitoring", "knowledge")


def _layer_from_prompt(prompt: str) -> str:
    m = _LAYER_RE.search(prompt)
    if m and m.group(1).lower() in _LAYERS:
        return m.group(1).lower()
    return "document"


def digest(filename: str, content: str) -> str:
    """Mapper-role file digest (plain text, not JSON)."""
    head = " ".join(content.split())[:200]
    return f"Digest of {filename}: {head}"


def _domain_map() -> dict[str, Any]:
    return {
        "core_function": "Deliver the domain's core service through coordinated operational work.",
        "stakeholders": ["Operations team", "Customers", "Management", "Regulators"],
        "stakeholder_processes": [
            {
                "stakeholder": "Operations team",
                "processes": ["Intake", "Validation", "Service delivery", "Reporting"],
            },
            {"stakeholder": "Customers", "processes": ["Request submission", "Review"]},
            {"stakeholder": "Management", "processes": ["Approval", "Performance review"]},
            {"stakeholder": "Regulators", "processes": ["Audit", "Compliance review"]},
        ],
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
    }


def _layer_analysis(layer: str) -> dict[str, Any]:
    return {
        "layer": layer,
        "findings": [
            f"The {layer} layer relies on recurring manual work between systems.",
            f"Existing tools cover part of the {layer} workflow but are not integrated.",
        ],
        "pain_points": [
            f"Repetitive manual handling in the {layer} layer",
            f"Errors introduced at {layer} handoff points",
        ],
        "pain_level": "high",
    }


def _draft(layer: str) -> dict[str, Any]:
    title = f"Automated {layer.replace('_', ' ').title()} Workflow"
    return {
        "layer": layer,
        "title": title,
        "problem": (
            f"Teams handle the {layer} workflow manually: work is copy-pasted between "
            "systems, reviewed by email, and re-entered on change, costing several "
            "hours per week and causing avoidable errors."
        ),
        "proposed_automation": (
            f"An agent that watches the {layer} inputs, applies the domain rules, "
            "produces the standard output artifact, and routes exceptions to a human."
        ),
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
        "technical_requirements": [
            "API access to the primary system of record",
            "LLM with tool calling",
            "Persistent storage for logs and outputs",
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
            },
            {
                "dimension": "Error rate",
                "current": "~5% rework",
                "automated": "<1% with validation",
                "improvement": "80%",
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
        "agents_required": "1 agent with a rule-checking tool",
        "effort": "medium",
        "impact_estimate": "high",
        "risk_level": "medium",
    }


def _critique() -> dict[str, Any]:
    return {
        "groundedness": 8,
        "specificity": 8,
        "quantified_impact": 8,
        "feasibility": 8,
        "hitl_clarity": 8,
        "differentiation": 8,
        "feedback": "Draft is grounded, specific, and quantified. Approved.",
    }


def _ice() -> dict[str, Any]:
    return {
        "impact": 4,
        "confidence": 4,
        "ease": 4,
        "rationale": (
            "Department-level transformation with a validated pattern and "
            "config-plus-API implementation effort."
        ),
    }


def call_json(role: str, schema_name: str, prompt: str) -> dict[str, Any]:
    """Return canned valid JSON for a role + schema pair."""
    layer = _layer_from_prompt(prompt)
    if schema_name == "DomainMap":
        return _domain_map()
    if schema_name == "LayerAnalysis":
        return _layer_analysis(layer)
    if schema_name == "DraftBatch":
        return {"drafts": [_draft(layer)]}
    if schema_name == "OpportunityDraft":
        return _draft(layer)
    if schema_name == "Critique":
        return _critique()
    if schema_name == "ICEScore":
        return _ice()
    raise ValueError(f"Mock provider has no canned response for schema {schema_name!r}")
