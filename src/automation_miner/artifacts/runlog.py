"""The phase-by-phase human run log (trace/run-log.md)."""

from __future__ import annotations


from automation_miner.artifacts.briefs import title_slug
from automation_miner.artifacts.report_parts import (
    FILTER_HEADINGS,
    cell,
    excluded_section,
    ice_row,
    run_notes,
    skipped_section,
    strategic_key,
    tokens,
    top_layer,
    usage_lines,
)
from automation_miner.schemas import (
    LAYER_ORDER,
    LAYER_TITLES,
    ContextPacket,
    Layer,
    DomainMap,
    LayerAnalysis,
    Opportunity,
    PortfolioStats,
    RunUsage,
)
from automation_miner.scoring import (
    FILTER_KEYS,
    context_policy,
    published,
)

def _domain_rows(domain_map: DomainMap) -> list[tuple[str, str]]:
    initiatives = "; ".join(claim.claim for claim in domain_map.proposed_initiatives)
    return [
        ("Analysis mode", domain_map.analysis_mode),
        ("Core function", domain_map.core_function),
        ("Key stakeholders", ", ".join(domain_map.stakeholders)),
        ("Information flow", domain_map.information_flow),
        ("Decision density", domain_map.decision_density),
        ("Compliance surface", domain_map.compliance_surface),
        ("Technology maturity", domain_map.technology_maturity),
        ("Scale indicators", domain_map.scale_indicators),
        ("Manual friction points", "; ".join(domain_map.manual_friction)),
        ("Workflow patterns", domain_map.workflow_patterns),
        ("Proposed initiatives", initiatives or "(none evidenced)"),
        ("Unknowns", "; ".join(domain_map.unknowns) or "(none recorded)"),
    ]


def _header(run_id: str, context: ContextPacket) -> list[str]:
    date = run_id.split("_", 1)[0]
    quality = context.input_quality
    return [
        f"# Automation Mining Run — {date}",
        "",
        f"> **Domain:** {context.domain}",
        f"> **Constraints:** {context.constraints or 'none'}",
        f"> **Context provided:** {context.source_kind} input "
        f"({context.stats.included_files} files, {context.stats.chunks} evidence chunks, "
        f"{tokens(context.stats.evidence_tokens)} tokens)",
        f"> **Input quality:** {quality.level} ({quality.score}/100) — {quality.warning}",
        f"> **Date:** {date}",
        "> **Engineer:** automation-miner engine",
        "",
        "---",
    ]


def _phase_one(domain_map: DomainMap, by_layer: dict[Layer, LayerAnalysis]) -> list[str]:
    lines = ["", "## Phase 1: Domain Map", "", "### Domain Characterization", ""]
    lines += ["| Dimension | Analysis |", "|-----------|----------|"]
    lines += [f"| {cell(k)} | {cell(v)} |" for k, v in _domain_rows(domain_map)]
    flows = "\n".join(
        f"{row.stakeholder} -> {' -> '.join(row.processes)}"
        for row in domain_map.stakeholder_processes
    )
    lines += ["", "### Stakeholder-Process Map", "", "```", flows, "```", ""]
    lines += ["### Five-Layer Analysis", ""]
    lines += ["| Layer | Key Findings | Pain Level |", "|-------|--------------|------------|"]
    for layer in LAYER_ORDER:
        analysis = by_layer.get(layer)
        if analysis:
            findings = cell("; ".join(analysis.findings[:2]))
            level = analysis.pain_level.value.upper()[0]
            lines.append(f"| {LAYER_TITLES[layer]} | {findings} | {level} |")
    return lines


def _phase_two(ranked: list[Opportunity], by_layer: dict[Layer, LayerAnalysis]) -> list[str]:
    lines = ["", "---", "", "## Phase 2: Run Log — Layer Agent Outputs", ""]
    for index, layer in enumerate(LAYER_ORDER, 1):
        analysis = by_layer.get(layer)
        lines += [f"### Layer {index}: {LAYER_TITLES[layer]}", "", "**AM candidate(s) identified:**"]
        opps = [o for o in ranked if o.draft.layer == layer]
        if opps:
            lines += [
                f"- {o.am_id}: {o.draft.title}" + ("" if o.published else " *(filtered)*")
                for o in opps
            ]
        elif analysis:
            lines += [f"- {point.pain}" for point in analysis.pain_points]
        else:
            lines.append("- (none)")
        lines.append("")
    return lines


def _phase_three(ranked: list[Opportunity], context: ContextPacket) -> list[str]:
    live = published(ranked)
    lines = ["---", "", "## Phase 3: Scoring", "", "### ICE Scores", ""]
    lines += [
        "| Rank | ID | Name | I | C | E | ICE | Tier | Layer | Effort | Risk | Critique |",
        "|------|----|------|---|---|---|-----|------|-------|--------|------|----------|",
    ]
    lines += [ice_row(index, opp) for index, opp in enumerate(live, 1)]
    lines += ["", "### Strategic Filters Applied", ""]
    for key in FILTER_KEYS:
        members = [o for o in live if strategic_key(o, key)]
        lines.append(f"**{FILTER_HEADINGS[key]}:**")
        lines += [f"- {o.am_id}: {o.draft.title}" for o in members] or ["- (none)"]
        lines.append("")
    return lines + excluded_section(ranked) + skipped_section(context)


def _created(ranked: list[Opportunity]) -> list[str]:
    lines = ["", "---", "", "## Opportunities Created", ""]
    lines += ["| ID | File | ICE | Tier | Status |", "|----|------|-----|------|--------|"]
    for opp in published(ranked):
        fname = f"opps/{opp.domain_slug}/{opp.am_id}-{title_slug(opp.draft.title)}.md"
        lines.append(
            f"| {opp.am_id} | `{fname}` | {opp.ice} | {opp.tier.value} | {opp.status.value} |"
        )
    return lines


def _closing(
    context: ContextPacket, ranked: list[Opportunity], stats: PortfolioStats, usage: RunUsage
) -> list[str]:
    policy = context_policy(context)
    notes = run_notes(context, ranked, policy)
    lines = ["", "---", "", "## Notes & Observations", ""]
    lines += [f"- {note}" for note in notes] or ["- Nothing unusual."]
    if usage.calls:
        lines += ["", "### Cost", "", *usage_lines(usage)]
    lines += ["", "---", "", "## Self-Improvement Feedback", ""]
    lines += [
        f"- Highest-scoring layer this run: {top_layer(stats)}.",
        "- Tune ICE calibration if systematic over/under-estimation is observed.",
    ]
    if any(o.calibration for o in ranked):
        lines.append(
            "- Code adjusted at least one score for incoherence with the draft's own "
            "effort/impact/risk estimates; see Notes."
        )
    return lines


def render_run_md(
    run_id: str,
    context: ContextPacket,
    domain_map: DomainMap,
    analyses: list[LayerAnalysis],
    ranked: list[Opportunity],
    stats: PortfolioStats | None = None,
    usage: RunUsage | None = None,
) -> str:
    """Human run log following the spec 07 template."""
    by_layer = {a.layer: a for a in analyses}
    lines = _header(run_id, context)
    lines += _phase_one(domain_map, by_layer)
    lines += _phase_two(ranked, by_layer)
    lines += _phase_three(ranked, context)
    lines += _created(ranked)
    lines += _closing(context, ranked, stats or PortfolioStats(), usage or RunUsage())
    return "\n".join(lines) + "\n"
