"""Deterministic mock provider — the whole graph runs offline against it.

Every role returns canned, schema-valid JSON. Two things are read out of the
prompt so artifacts look realistic rather than uniform: the active layer, and
the evidence ids on offer (so drafts cite refs that actually resolve).

The digest mock honours the requested target size. That matters: the real
failure it stands in for was a digester that ignored its budget and returned 4%
of it, so a mock that always returned a fixed 200 characters would hide exactly
the regression these tests exist to catch.
"""

from __future__ import annotations

import re
from typing import Any

_LAYER_RE = re.compile(r"^Layer:\s*(\w+)", re.MULTILINE)
_JSON_LAYER_RE = re.compile(r'"layer"\s*:\s*"(\w+)"')
_TARGET_RE = re.compile(r"approximately ([\d,]+) characters")
_CONTENT_RE = re.compile(r"\nContent:\n(.*)\n\nWrite a dense digest", re.DOTALL)
_REF_RE = re.compile(r"\[(S\d+)\]")
_TITLE_RE = re.compile(r'"title"\s*:\s*"([^"]+)"')
_IDEAS_RE = re.compile(r"^-\s*ideas\s*=\s*(\d+)\s*$", re.MULTILINE | re.IGNORECASE)

_LAYERS = ("document", "communication", "decision", "monitoring", "knowledge")


def _layer_from_prompt(prompt: str) -> str:
    match = _LAYER_RE.search(prompt)
    if not match:
        match = _JSON_LAYER_RE.search(prompt)
    if match and match.group(1).lower() in _LAYERS:
        return match.group(1).lower()
    return "document"


def _refs_from_prompt(prompt: str, limit: int = 3) -> list[str]:
    """Cite evidence ids that genuinely appear in the prompt."""
    seen: list[str] = []
    for ref in _REF_RE.findall(prompt):
        if ref not in seen:
            seen.append(ref)
        if len(seen) >= limit:
            break
    return seen


def digest(prompt: str) -> str:
    """Mapper-role digest (plain text). Fills the requested target size."""
    target_match = _TARGET_RE.search(prompt)
    target = int(target_match.group(1).replace(",", "")) if target_match else 800
    content_match = _CONTENT_RE.search(prompt)
    body = content_match.group(1) if content_match else prompt
    source_match = re.search(r"<untrusted-source>\s*(.*?)\s*</untrusted-source>", body, re.DOTALL)
    if source_match:
        body = source_match.group(1)
    condensed = " ".join(body.split())
    if len(condensed) <= target:
        return condensed
    head = condensed[:target]
    cut = head.rfind(". ")
    return head[: cut + 1] if cut > target // 2 else head


def _domain_map(refs: list[str]) -> dict[str, Any]:
    evidence_refs = refs[:1] or ["S1"]
    return {
        "analysis_mode": "operational",
        "core_function": "Deliver the domain's core service through coordinated operational work.",
        "stakeholders": ["Operations team", "Customers", "Management", "Regulators"],
        "stakeholder_processes": [
            {
                "stakeholder": "Operations team",
                "processes": ["Intake", "Validation", "Service delivery", "Reporting"],
                "evidence_refs": evidence_refs,
            },
            {"stakeholder": "Customers", "processes": ["Request submission", "Review"], "evidence_refs": evidence_refs},
            {"stakeholder": "Management", "processes": ["Approval", "Performance review"], "evidence_refs": evidence_refs},
            {"stakeholder": "Regulators", "processes": ["Audit", "Compliance review"], "evidence_refs": evidence_refs},
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
        "verified_current_state": [
            {"claim": "Recurring operational work is described.", "evidence_refs": evidence_refs}
        ],
        "stated_gaps": [],
        "proposed_initiatives": [],
        "benchmarks": [],
        "unknowns": [],
    }


def _layer_analysis(layer: str, refs: list[str]) -> dict[str, Any]:
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
        "evidence_refs": refs,
    }


def _candidate_portfolio(refs: list[str], prompt: str) -> dict[str, Any]:
    count_match = _IDEAS_RE.search(prompt)
    count = max(1, min(12, int(count_match.group(1)))) if count_match else 5
    layers = [_LAYERS[index % len(_LAYERS)] for index in range(count)]
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
                "evidence_refs": refs,
            }
            for index, layer in enumerate(layers)
        ]
    }


def _draft(layer: str, refs: list[str], prompt: str = "") -> dict[str, Any]:
    title_match = _TITLE_RE.search(prompt)
    title = (
        title_match.group(1)
        if title_match
        else f"Automated {layer.replace('_', ' ').title()} Workflow"
    )
    openclaw = "agent = openclaw" in prompt.casefold()
    agent_label = "An OpenClaw agent" if openclaw else "An agent"
    return {
        "layer": layer,
        "title": title,
        "problem": (
            f"Teams handle the {layer} workflow manually: work is copy-pasted between "
            "systems, reviewed by email, and re-entered on change, costing several "
            "hours per week and causing avoidable errors."
        ),
        "proposed_automation": (
            f"{agent_label} that watches the {layer} inputs, applies the domain rules, "
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
            *(["OpenClaw agent runtime"] if openclaw else []),
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
        "evidence_refs": refs,
        "assumptions": ["Current effort and error-rate baselines require validation."],
        "validation_questions": ["What are the measured weekly effort and rework rate?"],
    }


def _critique() -> dict[str, Any]:
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


def _ice() -> dict[str, Any]:
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


def call_json(role: str, schema_name: str, prompt: str) -> dict[str, Any]:
    """Return canned valid JSON for a role + schema pair."""
    layer = _layer_from_prompt(prompt)
    refs = _refs_from_prompt(prompt)
    if schema_name == "InputAssessment":
        return {
            "recommended_mode": "operational",
            "source_type": "operational evidence",
            "rationale": "The source describes recurring work.",
            "operational_evidence_refs": refs,
            "strategic_evidence_refs": [],
            "evidence_gaps": [],
        }
    if schema_name == "DomainMap":
        return _domain_map(refs)
    if schema_name == "CandidatePortfolio":
        return _candidate_portfolio(refs, prompt)
    if schema_name == "LayerAnalysis":
        return _layer_analysis(layer, refs)
    if schema_name == "OpportunityDraft":
        return _draft(layer, refs, prompt)
    if schema_name == "Critique":
        return _critique()
    if schema_name == "ICEScore":
        return _ice()
    raise ValueError(f"Mock provider has no canned response for schema {schema_name!r}")
