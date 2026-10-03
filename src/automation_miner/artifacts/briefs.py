"""Opportunity brief markdown renderer — spec 01 / sample 08a format, extended.

Reading order follows how a process owner decides; the computed quality
sections come from ``brief_sections``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from automation_miner.artifacts.brief_sections import (
    bullets,
    cell,
    evidence_section,
    numbered,
    scoring_section,
    validation_criteria,
    validation_section,
    yaml_scalar,
    is_discovery_hypothesis,
    title_slug,
)
from automation_miner.schemas import LAYER_TITLES, InputQuality, Opportunity

__all__ = ["is_discovery_hypothesis", "render_brief", "title_slug"]


_FRONTMATTER = """---
am-id: "{am_id}"
title: {title}
domain: {domain}
layer: "{layer}"
status: "{status}"
ice-score: {ice}
tier: "{tier}"
impact: {impact}
confidence: {confidence}
ease: {ease}
effort: "{effort}"
risk: "{risk}"
critique: {critique}
iterations: {iterations}
eligibility: "{eligibility}"
artifact-type: "{artifact_type}"
agent-count: {agent_count}
created: "{date}"
updated: "{date}"
source: {source}
tags: [automation, {layer}, {domain_slug}]
---
"""

_PROCESS = """## Impact Analysis

| Dimension | Current State | Automated State | Improvement | Basis |
|-----------|--------------|----------------|-------------|-------|
{impact_rows}

## Process Details

### Inputs
{inputs}

### Steps
{steps}

### Outputs
{outputs}

### Human-in-the-Loop Points
{hitl}

## Feasibility Assessment

### Technical Requirements
{requirements}

### Dependencies
{dependencies}

### Constraints
{constraints}
"""

_PLAN = """## Implementation Path

### Phase 1: MVP (1-2 weeks)
{mvp}

### Phase 2: Expansion (2-4 weeks)
{expansion}

### Phase 3: Autonomy (4-8 weeks)
{autonomy}

## Risk & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
{risk_rows}
"""

_FOOTER = """---

## Self-Improvement

Lifecycle: identified → evaluating → designing → implementing → live.
Move it with `automation-miner status {am_id} <status>`; record each measured
result with `automation-miner outcome {am_id} <measure #> <value>`.

Success measures:
{criteria}
"""

_HYPOTHESIS_NOTE = (
    "\n>\n> **Discovery Hypothesis** — a promising direction, not yet an "
    "implementation brief. Answer the questions under *Validate First* "
    "before committing build effort."
)


def _frontmatter(opp: Opportunity, run_id: str, date: str, artifact_type: str) -> str:
    d, s = opp.draft, opp.score
    return _FRONTMATTER.format(
        am_id=opp.am_id, title=yaml_scalar(d.title), domain=yaml_scalar(opp.domain),
        layer=d.layer.value, status=opp.status.value, ice=opp.ice, tier=opp.tier.value,
        impact=s.impact, confidence=s.confidence, ease=s.ease, effort=d.effort.value,
        risk=d.risk_level.value, critique=opp.critique_overall, iterations=opp.iterations,
        eligibility=opp.eligibility.value, artifact_type=artifact_type,
        agent_count=d.agent_count, date=date, source=yaml_scalar(run_id),
        domain_slug=opp.domain_slug,
    )


def _overview(opp: Opportunity, hypothesis: bool) -> str:
    """Title, headline score, problem, and proposal — what a reader decides on."""
    d, s = opp.draft, opp.score
    headline = (
        f"> **ICE {opp.ice} · {opp.tier.label}** — Impact {s.impact} × Confidence "
        f"{s.confidence} × Ease {s.ease} · {LAYER_TITLES[d.layer]} · "
        f"effort {d.effort.value} · risk {d.risk_level.value}"
    ) + (_HYPOTHESIS_NOTE if hypothesis else "")
    agents = f"{d.agent_count} agent{'s' if d.agent_count != 1 else ''}"
    early = f"\n{validation_section(opp, 'Validate First')}" if hypothesis else ""
    return (
        f"# {opp.am_id}: {d.title}\n\n{headline}\n\n"
        f"## Problem Statement\n\n{d.problem}\n\n"
        f"## Proposed Automation\n\n{d.proposed_automation}\n\n"
        f"**Agent topology:** {agents} — {d.agent_topology}\n{early}"
    )


def _process(opp: Opportunity) -> str:
    d = opp.draft
    impact_rows = "\n".join(
        f"| {cell(r.dimension)} | {cell(r.current)} | {cell(r.automated)} | "
        f"{cell(r.improvement)} | {cell(r.basis)}{' *(estimate)*' if r.assumption else ''} |"
        for r in d.impact_analysis
    ) or "| — | — | — | — | — |"
    return _PROCESS.format(
        impact_rows=impact_rows, inputs=bullets(d.inputs), steps=numbered(d.steps),
        outputs=bullets(d.outputs), hitl=bullets(d.hitl_points),
        requirements=bullets(d.technical_requirements), dependencies=bullets(d.dependencies),
        constraints=bullets(d.constraints),
    )


def _plan(opp: Opportunity) -> str:
    d = opp.draft
    risk_rows = "\n".join(
        f"| {cell(r.risk)} | {r.likelihood.value.upper()[0]} | "
        f"{r.impact.value.upper()[0]} | {cell(r.mitigation)} |"
        for r in d.risks
    ) or "| — | | | |"
    return _PLAN.format(
        mvp=bullets(d.implementation.mvp), expansion=bullets(d.implementation.expansion),
        autonomy=bullets(d.implementation.autonomy), risk_rows=risk_rows,
    )


def render_brief(
    opp: Opportunity,
    run_id: str,
    date: str | None = None,
    input_quality: InputQuality | None = None,
    evidence_labels: Mapping[str, str] | None = None,
) -> str:
    """Render one AM-XXX brief as self-contained markdown with YAML frontmatter.

    Reading order follows how a process owner decides: what is broken, what we
    would build, what it is worth, how it works, how to get there, what could go
    wrong — then the audit trail (scoring, evidence). A discovery hypothesis
    moves its validation questions directly under the proposal.
    """
    hypothesis = is_discovery_hypothesis(opp, input_quality)
    artifact_type = "discovery_hypothesis" if hypothesis else "opportunity_brief"
    late = "" if hypothesis else f"{validation_section(opp, 'Assumptions and Validation')}\n"
    parts = [
        _frontmatter(opp, run_id, date or f"{datetime.now():%Y-%m-%d}", artifact_type),
        _overview(opp, hypothesis),
        _process(opp),
        _plan(opp),
        f"{late}## Scoring & Confidence\n\n{scoring_section(opp)}\n",
        f"## Evidence\n\n{evidence_section(opp, run_id, evidence_labels)}\n",
        _FOOTER.format(criteria=validation_criteria(opp), am_id=opp.am_id),
    ]
    return "\n".join(parts)
