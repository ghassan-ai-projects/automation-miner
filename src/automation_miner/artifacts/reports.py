"""Run log (run.md, spec 07 template) and ranked report (report.md) renderers."""

from __future__ import annotations

from automation_miner.artifacts.briefs import title_slug
from automation_miner.schemas import (
    LAYER_ORDER,
    LAYER_TITLES,
    ContextPacket,
    DomainMap,
    LayerAnalysis,
    Opportunity,
)
from automation_miner.scoring import strategic_filters


def _filter_lists(ranked: list[Opportunity]) -> dict[str, list[Opportunity]]:
    out: dict[str, list[Opportunity]] = {"low_hanging": [], "high_value": [], "vision": []}
    for opp in ranked:
        flags = strategic_filters(opp)
        for key, active in flags.items():
            if active:
                out[key].append(opp)
    return out


def render_report(ranked: list[Opportunity]) -> str:
    """Ranked ICE table plus the three strategic filters."""
    lines = [
        "# Automation Mining Report",
        "",
        "## ICE Ranking",
        "",
        "| Rank | ID | Name | I | C | E | ICE | Layer | Effort | Risk |",
        "|------|----|------|---|---|---|------|-------|--------|------|",
    ]
    for i, opp in enumerate(ranked, 1):
        d = opp.draft
        lines.append(
            f"| {i} | {opp.am_id} | {d.title} | {opp.score.impact} | "
            f"{opp.score.confidence} | {opp.score.ease} | {opp.ice} | "
            f"{d.layer.value} | {d.effort.value.title()} | {d.risk_level.value.title()} |"
        )

    filters = _filter_lists(ranked)
    sections = [
        ("Low-hanging fruit (Ease ≥ 4, Impact ≥ 3) — immediate action", "low_hanging"),
        ("High-value (ICE ≥ 40, Risk ≤ Medium) — prioritized backlog", "high_value"),
        ("Vision/moonshot (Impact = 5, Ease ≤ 2) — strategic, note for future", "vision"),
    ]
    lines += ["", "## Strategic Filters", ""]
    for heading, key in sections:
        lines.append(f"**{heading}:**")
        if filters[key]:
            lines += [f"- {o.am_id}: {o.draft.title} (ICE {o.ice})" for o in filters[key]]
        else:
            lines.append("- (none)")
        lines.append("")
    return "\n".join(lines) + "\n"


def render_run_md(
    run_id: str,
    context: ContextPacket,
    domain_map: DomainMap,
    analyses: list[LayerAnalysis],
    ranked: list[Opportunity],
) -> str:
    """Human run log following the spec 07 template."""
    date = run_id.split("_", 1)[0]
    dm_rows = [
        ("Core function", domain_map.core_function),
        ("Key stakeholders", ", ".join(domain_map.stakeholders)),
        ("Information flow", domain_map.information_flow),
        ("Decision density", domain_map.decision_density),
        ("Compliance surface", domain_map.compliance_surface),
        ("Technology maturity", domain_map.technology_maturity),
        ("Scale indicators", domain_map.scale_indicators),
        ("Manual friction points", "; ".join(domain_map.manual_friction)),
        ("Workflow patterns", domain_map.workflow_patterns),
    ]
    lines = [
        f"# Automation Mining Run — {date}",
        "",
        f"> **Domain:** {context.domain}",
        f"> **Constraints:** {context.constraints or 'none'}",
        f"> **Context provided:** {context.source_kind} input "
        f"({len(context.content)} chars, {len(context.files)} files)",
        f"> **Date:** {date}",
        "> **Engineer:** automation-miner engine",
        "",
        "---",
        "",
        "## Phase 1: Domain Map",
        "",
        "### Domain Characterization",
        "",
        "| Dimension | Analysis |",
        "|-----------|----------|",
    ]
    lines += [f"| {k} | {v} |" for k, v in dm_rows]
    lines += [
        "",
        "### Stakeholder-Process Map",
        "",
        "```",
        "\n".join(f"{s} -> primary processes" for s in domain_map.stakeholders),
        "```",
        "",
        "### Five-Layer Analysis",
        "",
        "| Layer | Key Findings | Pain Level |",
        "|-------|--------------|------------|",
    ]
    by_layer = {a.layer: a for a in analyses}
    for layer in LAYER_ORDER:
        a = by_layer.get(layer)
        if a:
            findings = "; ".join(a.findings[:2])
            lines.append(f"| {LAYER_TITLES[layer]} | {findings} | {a.pain_level.value.upper()[0]} |")

    lines += ["", "---", "", "## Phase 2: Run Log — Layer Agent Outputs", ""]
    for i, layer in enumerate(LAYER_ORDER, 1):
        a = by_layer.get(layer)
        lines.append(f"### Layer {i}: {LAYER_TITLES[layer]}")
        lines.append("")
        lines.append("**AM candidate(s) identified:**")
        opps = [o for o in ranked if o.draft.layer == layer]
        if opps:
            lines += [f"- {o.am_id}: {o.draft.title}" for o in opps]
        elif a:
            lines += [f"- {p}" for p in a.pain_points]
        else:
            lines.append("- (none)")
        lines.append("")

    lines += [
        "---",
        "",
        "## Phase 3: Scoring",
        "",
        "### ICE Scores",
        "",
        "| Rank | ID | Name | I | C | E | ICE | Effort | Risk |",
        "|------|----|------|---|---|---|------|--------|------|",
    ]
    for i, opp in enumerate(ranked, 1):
        d = opp.draft
        lines.append(
            f"| {i} | {opp.am_id} | {d.title} | {opp.score.impact} | "
            f"{opp.score.confidence} | {opp.score.ease} | {opp.ice} | "
            f"{d.effort.value.title()} | {d.risk_level.value.title()} |"
        )

    filters = _filter_lists(ranked)
    lines += ["", "### Strategic Filters Applied", ""]
    for heading, key in [
        ("Low-hanging fruit (Ease ≥ 4, Impact ≥ 3)", "low_hanging"),
        ("High-value (ICE ≥ 40, Risk ≤ Medium)", "high_value"),
        ("Vision/moonshot (Impact = 5, Ease ≤ 2)", "vision"),
    ]:
        lines.append(f"**{heading}:**")
        lines += [f"- {o.am_id}: {o.draft.title}" for o in filters[key]] or ["- (none)"]
        lines.append("")

    lines += [
        "---",
        "",
        "## Opportunities Created",
        "",
        "| ID | File | ICE | Status |",
        "|----|------|-----|--------|",
    ]
    for opp in ranked:
        fname = f"opps/{opp.domain_slug}/{opp.am_id}-{title_slug(opp.draft.title)}.md"
        lines.append(f"| {opp.am_id} | `{fname}` | {opp.ice} | {opp.status.value} |")

    notes = []
    if context.constraints:
        notes.append(f"Constraints applied: {context.constraints}")
    overridden = [o for o in ranked if o.overrides_applied]
    for o in overridden:
        notes.append(f"{o.am_id}: {'; '.join(o.overrides_applied)}")
    if context.digested:
        notes.append("KB input was digested map-reduce style to fit the context budget.")
    if context.truncated:
        notes.append("Input was truncated to fit the context budget.")

    notes_lines = [f"- {n}" for n in notes] if notes else ["- Nothing unusual."]
    lines += [
        "",
        "---",
        "",
        "## Notes & Observations",
        "",
        *notes_lines,
        "",
        "---",
        "",
        "## Self-Improvement Feedback",
        "",
        "- Review which layers produced the highest ICE scores this run.",
        "- Tune ICE calibration if systematic over/under-estimation is observed.",
    ]
    return "\n".join(lines) + "\n"
