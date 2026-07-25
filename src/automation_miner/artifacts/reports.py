"""Report, run-log, and summary renderers.

``report.md`` was previously a bare ICE table plus three filter lists: no
domain, run id, constraints, tier labels, portfolio shape, cost, or any mention
of opportunities the constraint policy had excluded. It could not answer "what
did this run cost me" or "why are there only three briefs".

``summary.json`` is new and exists for the MCP path. An agent driving
``mine_domain`` previously had to choose between parsing markdown or loading the
full ``opportunities.json`` (every draft, every table) to learn what came out of
a run. The summary is the middle artifact: one compact row per opportunity.
"""

from __future__ import annotations

from automation_miner.artifacts.briefs import title_slug
from automation_miner.schemas import (
    LAYER_ORDER,
    LAYER_TITLES,
    ContextPacket,
    DomainMap,
    LayerAnalysis,
    Opportunity,
    PortfolioStats,
    RunSummary,
    RunUsage,
    SummaryEntry,
    Tier,
)
from automation_miner.scoring import (
    FILTER_KEYS,
    active_filters,
    parse_constraint_policy,
    published,
)

FILTER_HEADINGS: dict[str, str] = {
    "low_hanging": "Low-hanging fruit (Ease ≥ 4, Impact ≥ 3) — immediate action",
    "high_value": "High-value (ICE ≥ 40, Risk ≤ Medium) — prioritized backlog",
    "vision": "Vision/moonshot (Impact = 5, Ease ≤ 2) — strategic, note for future",
}

TIER_ORDER: tuple[Tier, ...] = (Tier.VISION, Tier.HIGH, Tier.MEDIUM, Tier.LOW)


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>")


def _tokens(count: int) -> str:
    if count >= 1_000_000:
        return f"{count / 1_000_000:.2f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}k"
    return str(count)


def _ice_row(index: int, opp: Opportunity, with_tier: bool = True) -> str:
    d = opp.draft
    tier = f" {opp.tier.value} |" if with_tier else ""
    return (
        f"| {index} | {opp.am_id} | {_cell(d.title)} | {opp.score.impact} | "
        f"{opp.score.confidence} | {opp.score.ease} | {opp.ice} |{tier} "
        f"{d.layer.value} | {d.effort.value.title()} | {d.risk_level.value.title()} | "
        f"{opp.critique_overall} |"
    )


def _usage_lines(usage: RunUsage) -> list[str]:
    if not usage.calls:
        return []
    exactness = "provider-reported" if usage.exact else "estimated"
    lines = [
        f"- **Model calls:** {usage.calls}"
        + (f" ({usage.retries} retried)" if usage.retries else ""),
        f"- **Tokens ({exactness}):** {_tokens(usage.prompt_tokens)} in, "
        f"{_tokens(usage.completion_tokens)} out, {_tokens(usage.total_tokens)} total",
    ]
    if usage.by_role:
        busiest = sorted(
            usage.by_role.items(), key=lambda kv: -kv[1].total_tokens
        )[:3]
        detail = ", ".join(
            f"{role} {call.calls}×/{_tokens(call.total_tokens)}" for role, call in busiest
        )
        lines.append(f"- **Heaviest roles:** {detail}")
    return lines


def _context_lines(context: ContextPacket) -> list[str]:
    stats = context.stats
    lines = [
        f"- **Source:** {context.source_kind} input, {stats.included_files} file(s) read"
        + (f", {stats.skipped_files} skipped" if stats.skipped_files else ""),
        f"- **Evidence index:** {stats.chunks} chunks, {_tokens(stats.evidence_tokens)} tokens "
        f"({stats.budget_used_pct}% of a {_tokens(stats.budget_tokens)} budget)",
    ]
    if stats.source_chars:
        lines.append(
            f"- **Retention:** {stats.retention_pct}% of {stats.source_chars:,} source chars"
        )
    if stats.digested:
        cached = f", {stats.digest_cache_hits} cached" if stats.digest_cache_hits else ""
        lines.append(
            f"- **Digested:** yes — {stats.digest_calls} digest call(s){cached}"
        )
    if stats.truncated:
        lines.append("- **Truncated:** yes — evidence exceeded the budget after digesting")
    return lines


def _skipped_section(context: ContextPacket) -> list[str]:
    if not context.skipped:
        return []
    lines = ["", "## Files Not Read", "", "| File | Reason |", "|------|--------|"]
    for skip in context.skipped:
        name = skip.path.rsplit("/", 1)[-1]
        lines.append(f"| `{_cell(name)}` | {_cell(skip.reason)} |")
    return lines


def _excluded_section(ranked: list[Opportunity]) -> list[str]:
    excluded = [o for o in ranked if not o.published]
    if not excluded:
        return []
    lines = [
        "",
        "## Excluded by Constraint Policy",
        "",
        "These were fully drafted, critiqued and scored, then held back by the "
        "constraints given for this run. They are retained in `scores.json` and "
        "`summary.json`.",
        "",
        "| ID | Name | ICE | Reason |",
        "|----|------|-----|--------|",
    ]
    for opp in excluded:
        reasons = "; ".join(opp.exclusion_reasons) or "policy"
        lines.append(
            f"| {opp.am_id} | {_cell(opp.draft.title)} | {opp.ice} | {_cell(reasons)} |"
        )
    return lines


def _recommendation(ranked: list[Opportunity]) -> list[str]:
    """Suggest a starting sequence: quick wins first, then highest value."""
    live = published(ranked)
    if not live:
        return []
    # Quick wins first (already in rank order), then the highest-value remainder.
    quick = [o for o in live if "low_hanging" in active_filters(o)]
    rest = [o for o in live if o not in quick]
    lines = ["", "## Recommended Sequence", ""]
    for position, opp in enumerate((quick + rest)[:3], 1):
        why = (
            "quick win — configuration-level with real impact"
            if "low_hanging" in active_filters(opp)
            else f"highest remaining value at ICE {opp.ice}"
        )
        lines.append(f"{position}. **{opp.am_id}** {opp.draft.title} — {why}")
    return lines


def render_report(
    *,
    run_id: str,
    context: ContextPacket,
    ranked: list[Opportunity],
    stats: PortfolioStats,
    usage: RunUsage | None = None,
    models: dict[str, str] | None = None,
) -> str:
    """Ranked ICE table with run metadata, portfolio shape, and exclusions."""
    usage = usage or RunUsage()
    live = published(ranked)
    date = run_id.split("_", 1)[0]
    policy = parse_constraint_policy(context.constraints)

    lines = [
        f"# Automation Mining Report — {context.domain}",
        "",
        f"> **Run:** `{run_id}`  ",
        f"> **Date:** {date}  ",
        f"> **Constraints:** {context.constraints or 'none'}  ",
        f"> **Opportunities:** {stats.published} published"
        + (f", {stats.filtered} filtered" if stats.filtered else ""),
        "",
        "## Summary",
        "",
        f"- **Portfolio:** {stats.published} published, average ICE {stats.avg_ice}, "
        f"median {stats.median_ice}, top {stats.top_ice}"
        + (f" ({stats.top_id})" if stats.top_id else ""),
    ]
    if stats.by_tier:
        tiers = ", ".join(
            f"{tier.value} {stats.by_tier[tier.value]}"
            for tier in TIER_ORDER
            if stats.by_tier.get(tier.value)
        )
        lines.append(f"- **Tiers:** {tiers}")
    if stats.by_layer:
        layers = ", ".join(
            f"{layer.value} {stats.by_layer[layer.value]}"
            for layer in LAYER_ORDER
            if stats.by_layer.get(layer.value)
        )
        lines.append(f"- **Layers covered:** {layers}")
    lines += _context_lines(context)
    lines += _usage_lines(usage)
    if models:
        lines.append(
            "- **Models:** "
            + ", ".join(f"{role}={name}" for role, name in sorted(models.items()))
        )

    lines += [
        "",
        "## ICE Ranking",
        "",
        "| Rank | ID | Name | I | C | E | ICE | Tier | Layer | Effort | Risk | Critique |",
        "|------|----|------|---|---|---|-----|------|-------|--------|------|----------|",
    ]
    for index, opp in enumerate(live, 1):
        lines.append(_ice_row(index, opp))
    if not live:
        lines.append("| — | — | *(no opportunity passed the constraint policy)* | | | | | | | | | |")

    lines += ["", "## Strategic Filters", ""]
    for key in FILTER_KEYS:
        lines.append(f"**{FILTER_HEADINGS[key]}:**")
        members = [o for o in live if strategic_key(o, key)]
        lines += (
            [f"- {o.am_id}: {o.draft.title} (ICE {o.ice})" for o in members]
            if members
            else ["- (none)"]
        )
        lines.append("")

    lines += _recommendation(ranked)
    lines += _excluded_section(ranked)
    lines += _skipped_section(context)

    notes = _run_notes(context, ranked, policy)
    if notes:
        lines += ["", "## Notes", ""] + [f"- {note}" for note in notes]

    return "\n".join(lines) + "\n"


def strategic_key(opp: Opportunity, key: str) -> bool:
    return key in active_filters(opp)


def _run_notes(context: ContextPacket, ranked: list[Opportunity], policy: object) -> list[str]:
    notes: list[str] = []
    described = getattr(policy, "describe", None)
    if callable(described):
        notes += described()
    calibrated = [o for o in ranked if o.calibration]
    for opp in calibrated:
        notes.append(f"{opp.am_id} calibration: {'; '.join(opp.calibration)}")
    unresolved = [o for o in ranked if o.unresolved_refs]
    for opp in unresolved:
        notes.append(
            f"{opp.am_id} cited unknown evidence ids: {', '.join(opp.unresolved_refs)}"
        )
    if context.reader_errors:
        notes += [f"reader plugin issue: {error}" for error in context.reader_errors]
    return notes


def render_summary(
    *,
    run_id: str,
    context: ContextPacket,
    ranked: list[Opportunity],
    stats: PortfolioStats,
    usage: RunUsage,
    created: str,
    duration_seconds: float,
    dry_run: bool,
    brief_paths: dict[str, str] | None = None,
) -> RunSummary:
    """Compact, agent-facing view of a run — the payload MCP returns inline."""
    paths = brief_paths or {}
    entries = [
        SummaryEntry(
            am_id=opp.am_id,
            title=opp.draft.title,
            layer=opp.draft.layer,
            ice=opp.ice,
            tier=opp.tier,
            impact=opp.score.impact,
            confidence=opp.score.confidence,
            ease=opp.score.ease,
            effort=opp.draft.effort,
            risk_level=opp.draft.risk_level,
            critique=opp.critique_overall,
            iterations=opp.iterations,
            eligibility=opp.eligibility,
            exclusion_reasons=opp.exclusion_reasons,
            filters=active_filters(opp),
            problem=_first_sentence(opp.draft.problem),
            brief_path=paths.get(opp.am_id, ""),
        )
        for opp in ranked
    ]
    policy = parse_constraint_policy(context.constraints)
    return RunSummary(
        run_id=run_id,
        domain=context.domain,
        domain_slug=context.domain_slug,
        constraints=context.constraints,
        created=created,
        duration_seconds=duration_seconds,
        dry_run=dry_run,
        stats=stats,
        context=context.stats,
        usage=usage,
        opportunities=entries,
        notes=_run_notes(context, ranked, policy),
    )


def _first_sentence(text: str, limit: int = 240) -> str:
    flat = " ".join(text.split())
    cut = flat.find(". ")
    sentence = flat[: cut + 1] if 0 < cut <= limit else flat[:limit]
    return sentence.strip()


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
    stats = stats or PortfolioStats()
    usage = usage or RunUsage()
    live = published(ranked)
    date = run_id.split("_", 1)[0]
    dm_rows = [
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
        (
            "Proposed initiatives",
            "; ".join(claim.claim for claim in domain_map.proposed_initiatives)
            or "(none evidenced)",
        ),
        ("Unknowns", "; ".join(domain_map.unknowns) or "(none recorded)"),
    ]
    lines = [
        f"# Automation Mining Run — {date}",
        "",
        f"> **Domain:** {context.domain}",
        f"> **Constraints:** {context.constraints or 'none'}",
        f"> **Context provided:** {context.source_kind} input "
        f"({context.stats.included_files} files, {context.stats.chunks} evidence chunks, "
        f"{_tokens(context.stats.evidence_tokens)} tokens)",
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
    lines += [f"| {_cell(k)} | {_cell(v)} |" for k, v in dm_rows]
    lines += [
        "",
        "### Stakeholder-Process Map",
        "",
        "```",
        "\n".join(
            f"{row.stakeholder} -> {' -> '.join(row.processes)}"
            for row in domain_map.stakeholder_processes
        ),
        "```",
        "",
        "### Five-Layer Analysis",
        "",
        "| Layer | Key Findings | Pain Level |",
        "|-------|--------------|------------|",
    ]
    by_layer = {a.layer: a for a in analyses}
    for layer in LAYER_ORDER:
        analysis = by_layer.get(layer)
        if analysis:
            findings = _cell("; ".join(analysis.findings[:2]))
            level = analysis.pain_level.value.upper()[0]
            lines.append(f"| {LAYER_TITLES[layer]} | {findings} | {level} |")

    lines += ["", "---", "", "## Phase 2: Run Log — Layer Agent Outputs", ""]
    for index, layer in enumerate(LAYER_ORDER, 1):
        analysis = by_layer.get(layer)
        lines.append(f"### Layer {index}: {LAYER_TITLES[layer]}")
        lines.append("")
        lines.append("**AM candidate(s) identified:**")
        opps = [o for o in ranked if o.draft.layer == layer]
        if opps:
            lines += [
                f"- {o.am_id}: {o.draft.title}"
                + ("" if o.published else " *(filtered)*")
                for o in opps
            ]
        elif analysis:
            lines += [f"- {point}" for point in analysis.pain_points]
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
        "| Rank | ID | Name | I | C | E | ICE | Tier | Layer | Effort | Risk | Critique |",
        "|------|----|------|---|---|---|-----|------|-------|--------|------|----------|",
    ]
    for index, opp in enumerate(live, 1):
        lines.append(_ice_row(index, opp))

    lines += ["", "### Strategic Filters Applied", ""]
    for key in FILTER_KEYS:
        lines.append(f"**{FILTER_HEADINGS[key]}:**")
        members = [o for o in live if strategic_key(o, key)]
        lines += [f"- {o.am_id}: {o.draft.title}" for o in members] or ["- (none)"]
        lines.append("")

    lines += _excluded_section(ranked)
    lines += _skipped_section(context)

    lines += [
        "",
        "---",
        "",
        "## Opportunities Created",
        "",
        "| ID | File | ICE | Tier | Status |",
        "|----|------|-----|------|--------|",
    ]
    for opp in live:
        fname = f"opps/{opp.domain_slug}/{opp.am_id}-{title_slug(opp.draft.title)}.md"
        lines.append(
            f"| {opp.am_id} | `{fname}` | {opp.ice} | {opp.tier.value} | {opp.status.value} |"
        )

    notes = _run_notes(context, ranked, parse_constraint_policy(context.constraints))
    lines += [
        "",
        "---",
        "",
        "## Notes & Observations",
        "",
        *([f"- {note}" for note in notes] or ["- Nothing unusual."]),
    ]
    if usage.calls:
        lines += ["", "### Cost", ""] + _usage_lines(usage)

    lines += [
        "",
        "---",
        "",
        "## Self-Improvement Feedback",
        "",
        f"- Highest-scoring layer this run: {_top_layer(stats)}.",
        "- Tune ICE calibration if systematic over/under-estimation is observed.",
    ]
    if any(o.calibration for o in ranked):
        lines.append(
            "- Code adjusted at least one score for incoherence with the draft's own "
            "effort/impact/risk estimates; see Notes."
        )
    return "\n".join(lines) + "\n"


def _top_layer(stats: PortfolioStats) -> str:
    if not stats.by_layer:
        return "none"
    layer, count = max(stats.by_layer.items(), key=lambda kv: (kv[1], kv[0]))
    return f"{layer} ({count} opportunit{'y' if count == 1 else 'ies'})"
