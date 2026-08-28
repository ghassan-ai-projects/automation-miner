"""Opportunity brief markdown renderer — spec 01 / sample 08a format, extended.

The brief used to render only the draft. Everything the pipeline computed about
*quality* — the per-factor score rationale, the critic's score, how many refine
rounds it took, which constraint overrides fired, which code calibrations were
applied, and which evidence the draft rests on — was persisted to JSON and then
never shown. A published brief could not justify its own ICE score.

Two sections close that gap: **Scoring & Confidence** and **Evidence**.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from automation_miner.schemas import InputQuality, Opportunity
from automation_miner.scoring import active_filters

FILTER_LABELS: dict[str, str] = {
    "low_hanging": "low-hanging fruit",
    "high_value": "high-value",
    "vision": "vision/moonshot",
}


def title_slug(title: str) -> str:
    """Short slug for the brief filename."""
    text = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return text[:60].strip("-") or "opportunity"


def _yaml_scalar(text: str) -> str:
    """JSON strings are valid YAML scalars and preserve quotes, slashes, and newlines."""
    return json.dumps(text, ensure_ascii=False)


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>")


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- (none identified)"


def _numbered(items: list[str]) -> str:
    cleaned = [re.sub(r"^\s*\d+[.)]\s*", "", item) for item in items]
    return "\n".join(f"{i}. {item}" for i, item in enumerate(cleaned, 1))


def is_discovery_hypothesis(
    opp: Opportunity, input_quality: InputQuality | None = None
) -> bool:
    """Frame uncertain output, including all thin-input output, as discovery work."""
    return (
        input_quality is not None and input_quality.level == "thin"
    ) or opp.score.confidence <= 2 or not opp.draft.evidence_refs


def _scoring_section(opp: Opportunity) -> str:
    """Per-factor rationale plus every automated judgement applied to the score."""
    s = opp.score
    lines = [
        f"**ICE {opp.ice}** — {opp.tier.label} · Impact {s.impact} × "
        f"Confidence {s.confidence} × Ease {s.ease}",
        "",
        f"- **Impact {s.impact}** — {s.impact_rationale}",
        f"- **Confidence {s.confidence}** — {s.confidence_rationale}",
        f"- **Ease {s.ease}** — {s.ease_rationale}",
        "",
        f"Critic score **{opp.critique_overall}/10** after "
        f"{opp.iterations} iteration{'s' if opp.iterations != 1 else ''}.",
    ]
    if flags := active_filters(opp):
        labels = ", ".join(FILTER_LABELS.get(key, key) for key in flags)
        lines += ["", f"Strategic filters: {labels}."]
    if opp.calibration:
        lines += [
            "",
            "Automated calibration (code cross-checked the proposed factors against "
            "this draft's own effort, impact and risk estimates):",
            "",
            *[f"- {note}" for note in opp.calibration],
        ]
    if opp.overrides_applied:
        lines += [
            "",
            "Constraint overrides applied:",
            "",
            *[f"- {note}" for note in opp.overrides_applied],
        ]
    if not opp.published:
        lines += [
            "",
            "> **Excluded from the published portfolio for this run:**",
            *[f"> - {reason}" for reason in opp.exclusion_reasons],
        ]
    return "\n".join(lines)


def _evidence_section(opp: Opportunity) -> str:
    """Which evidence ids the draft cites, and any that did not resolve."""
    if not opp.draft.evidence_refs:
        return (
            "No evidence ids were cited. Treat the claims above as inference rather "
            "than grounded findings."
        )

    lines = [
        "Grounded in the following evidence from the source material "
        f"(ids refer to `context.json` in run `{opp.domain_slug}`):",
        "",
        "- " + ", ".join(f"`{ref}`" for ref in opp.draft.evidence_refs),
    ]
    if opp.unresolved_refs:
        lines += [
            "",
            "> **Unverified citations:** "
            + ", ".join(f"`{ref}`" for ref in opp.unresolved_refs)
            + " — these ids do not exist in the run's evidence index, so the claims "
            "attached to them are unsupported.",
        ]
    return "\n".join(lines)


def render_brief(
    opp: Opportunity,
    run_id: str,
    date: str | None = None,
    input_quality: InputQuality | None = None,
) -> str:
    """Render one AM-XXX brief as self-contained markdown with YAML frontmatter."""
    d = opp.draft
    date = date or f"{datetime.now():%Y-%m-%d}"
    tags = f"[automation, {d.layer.value}, {opp.domain_slug}]"
    hypothesis = is_discovery_hypothesis(opp, input_quality)
    artifact_type = "discovery_hypothesis" if hypothesis else "opportunity_brief"
    framing = (
        ""
        if not hypothesis
        else f"> **Discovery Hypothesis**  \n"
        "Validate the current state and assumptions before treating this as an "
        "implementation brief.\n\n"
        "### Validate First\n"
        f"{_bullets(d.validation_questions)}\n"
    )

    impact_rows = "\n".join(
        f"| {_cell(r.dimension)} | {_cell(r.current)} | {_cell(r.automated)} | "
        f"{_cell(r.improvement)} | {_cell(r.basis)}"
        f"{' *(assumption)*' if r.assumption else ''} |"
        for r in d.impact_analysis
    ) or "| — | — | — | — | — |"
    risk_rows = "\n".join(
        f"| {_cell(r.risk)} | {r.likelihood.value.upper()[0]} | "
        f"{r.impact.value.upper()[0]} | {_cell(r.mitigation)} |"
        for r in d.risks
    ) or "| — | | | |"

    return f"""---
am-id: "{opp.am_id}"
title: {_yaml_scalar(d.title)}
domain: {_yaml_scalar(opp.domain)}
layer: "{d.layer.value}"
status: "{opp.status.value}"
ice-score: {opp.ice}
tier: "{opp.tier.value}"
impact: {opp.score.impact}
confidence: {opp.score.confidence}
ease: {opp.score.ease}
effort: "{d.effort.value}"
risk: "{d.risk_level.value}"
critique: {opp.critique_overall}
iterations: {opp.iterations}
eligibility: "{opp.eligibility.value}"
artifact-type: "{artifact_type}"
agent-count: {d.agent_count}
created: "{date}"
updated: "{date}"
source: {_yaml_scalar(run_id)}
tags: {tags}
---

# {opp.am_id}: {d.title}

{framing}

## Problem Statement

{d.problem}

## Proposed Automation

{d.proposed_automation}

**Agent topology:** {d.agent_count} agent{"s" if d.agent_count != 1 else ""} — {d.agent_topology}

## Scoring & Confidence

{_scoring_section(opp)}

## Process Details

### Inputs
{_bullets(d.inputs)}

### Steps
{_numbered(d.steps)}

### Outputs
{_bullets(d.outputs)}

### Human-in-the-Loop Points
{_bullets(d.hitl_points)}

## Feasibility Assessment

### Technical Requirements
{_bullets(d.technical_requirements)}

### Dependencies
{_bullets(d.dependencies)}

### Constraints
{_bullets(d.constraints)}

## Assumptions and Validation

### Assumptions
{_bullets(d.assumptions)}

### Validation Questions
{_bullets(d.validation_questions)}

## Impact Analysis

| Dimension | Current State | Automated State | Improvement | Basis |
|-----------|--------------|----------------|-------------|-------|
{impact_rows}

## Implementation Path

### Phase 1: MVP (1-2 weeks)
{_bullets(d.implementation.mvp)}

### Phase 2: Expansion (2-4 weeks)
{_bullets(d.implementation.expansion)}

### Phase 3: Autonomy (4-8 weeks)
{_bullets(d.implementation.autonomy)}

## Risk & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
{risk_rows}

## Evidence

{_evidence_section(opp)}

---

## Self-Improvement

This opportunity was generated by the Automation Miner engine. Track its lifecycle through the pipeline:

- [ ] **Identified** — opportunity brief created
- [ ] **Evaluating** — domain expert is validating problem/relevance
- [ ] **Designing** — implementation plan complete
- [ ] **Implementing** — prototype or MVP is being built
- [ ] **Live** — running in production
- [ ] **Measured** — actual impact vs. projected impact

Validation criteria:
- Actual time saved vs. the {_first_improvement(opp)} projected above
- Error rate improvement vs. estimate
- User satisfaction with automation
- What was missed in the analysis?
"""


def _first_improvement(opp: Opportunity) -> str:
    """Quote the draft's own headline improvement, so validation has a target."""
    for row in opp.draft.impact_analysis:
        if row.improvement.strip():
            return f"{row.improvement.strip()} {row.dimension.strip().lower()} improvement"
    return "projected"
