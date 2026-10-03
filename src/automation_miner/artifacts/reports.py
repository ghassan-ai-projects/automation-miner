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

from typing import Literal

from automation_miner.artifacts.briefs import is_discovery_hypothesis
from automation_miner.artifacts.runlog import render_run_md
from automation_miner.artifacts.report_parts import (
    pain_coverage,
    FILTER_HEADINGS,
    TIER_ORDER,
    at_a_glance,
    context_lines,
    excluded_section,
    first_sentence,
    ice_row,
    recommendation,
    run_notes,
    skipped_section,
    strategic_key,
    usage_lines,
)
from automation_miner.schemas import (
    RankedPain,
    LAYER_ORDER,
    ContextPacket,
    Opportunity,
    PortfolioStats,
    RunSummary,
    RunBudget,
    RunUsage,
    SummaryEntry,
)
from automation_miner.scoring import (
    FILTER_KEYS,
    active_filters,
    parse_constraint_policy,
    published,
)

RunStatus = Literal["running", "completed", "failed", "budget_exhausted"]
PublicationStatus = Literal["pending", "complete"]


def _header(run_id: str, context: ContextPacket, stats: PortfolioStats, status: str,
            publication_status: str) -> list[str]:
    filtered = f", {stats.filtered} filtered" if stats.filtered else ""
    return [
        f"# Automation Mining Report: {context.domain}",
        "",
        f"> **Run:** `{run_id}`  ",
        f"> **Date:** {run_id.split('_', 1)[0]}  ",
        f"> **Status:** {status}  ",
        f"> **Publication:** {publication_status}  ",
        f"> **Constraints:** {context.constraints or 'none'}  ",
        f"> **Opportunities:** {stats.published} published{filtered}",
    ]


def _summary_section(stats: PortfolioStats) -> list[str]:
    top = f" ({stats.top_id})" if stats.top_id else ""
    lines = [
        "", "## Summary", "",
        f"- **Portfolio:** {stats.published} published, average ICE {stats.avg_ice}, "
        f"median {stats.median_ice}, top {stats.top_ice}{top}",
    ]
    tiers = [f"{t.value} {stats.by_tier[t.value]}" for t in TIER_ORDER if stats.by_tier.get(t.value)]
    if tiers:
        lines.append(f"- **Tiers:** {', '.join(tiers)}")
    layers = [
        f"{layer.value} {stats.by_layer[layer.value]}"
        for layer in LAYER_ORDER
        if stats.by_layer.get(layer.value)
    ]
    if layers:
        lines.append(f"- **Layers covered:** {', '.join(layers)}")
    return lines


def _ranking(ranked: list[Opportunity]) -> list[str]:
    live = published(ranked)
    lines = ["", "## ICE Ranking", ""]
    lines += [
        "| Rank | ID | Name | I | C | E | ICE | Tier | Layer | Effort | Risk | Critique |",
        "|------|----|------|---|---|---|-----|------|-------|--------|------|----------|",
    ]
    lines += [ice_row(index, opp) for index, opp in enumerate(live, 1)]
    if not live:
        lines.append("| — | — | *(no opportunity passed the constraint policy)* | | | | | | | | | |")
    lines += ["", "## Strategic Filters", ""]
    for key in FILTER_KEYS:
        members = [o for o in live if strategic_key(o, key)]
        lines.append(f"**{FILTER_HEADINGS[key]}:**")
        lines += [f"- {o.am_id}: {o.draft.title} (ICE {o.ice})" for o in members] or ["- (none)"]
        lines.append("")
    return lines


def render_report(
    *, run_id: str, context: ContextPacket, ranked: list[Opportunity], stats: PortfolioStats,
    usage: RunUsage | None = None, models: dict[str, str] | None = None,
    status: RunStatus = "completed", publication_status: PublicationStatus = "complete",
    budget: RunBudget | None = None, pain_ledger: list[RankedPain] | None = None,
) -> str:
    """Ranked ICE table with run metadata, portfolio shape, and exclusions."""
    lines = _header(run_id, context, stats, status, publication_status)
    lines += at_a_glance(ranked, context) + recommendation(ranked)
    lines += pain_coverage(ranked, pain_ledger or [])
    lines += _summary_section(stats) + context_lines(context)
    lines += usage_lines(usage or RunUsage(), budget)
    if models:
        routes = ", ".join(f"{role}={name}" for role, name in sorted(models.items()))
        lines.append(f"- **Models:** {routes}")
    lines += _ranking(ranked) + excluded_section(ranked) + skipped_section(context)
    policy = parse_constraint_policy(context.raw_constraints, context.constraint_params)
    notes = run_notes(context, ranked, policy)
    if notes:
        lines += ["", "## Notes", "", *[f"- {note}" for note in notes]]
    return "\n".join(lines) + "\n"


def _entry(opp: Opportunity, context: ContextPacket, brief_path: str) -> SummaryEntry:
    hypothesis = is_discovery_hypothesis(opp, context.input_quality)
    return SummaryEntry(
        am_id=opp.am_id, title=opp.draft.title, layer=opp.draft.layer, ice=opp.ice,
        tier=opp.tier, impact=opp.score.impact, confidence=opp.score.confidence,
        ease=opp.score.ease, effort=opp.draft.effort, risk_level=opp.draft.risk_level,
        critique=opp.critique_overall, iterations=opp.iterations,
        eligibility=opp.eligibility, exclusion_reasons=opp.exclusion_reasons,
        filters=active_filters(opp), problem=first_sentence(opp.draft.problem),
        brief_path=brief_path,
        artifact_type="discovery_hypothesis" if hypothesis else "opportunity_brief",
    )


def render_summary(
    *, run_id: str, context: ContextPacket, ranked: list[Opportunity], stats: PortfolioStats,
    usage: RunUsage, created: str, duration_seconds: float, dry_run: bool,
    brief_paths: dict[str, str] | None = None, status: RunStatus = "completed",
    publication_status: PublicationStatus = "complete", budget: RunBudget | None = None,
) -> RunSummary:
    """Compact, agent-facing view of a run — the payload MCP returns inline."""
    paths = brief_paths or {}
    policy = parse_constraint_policy(context.raw_constraints, context.constraint_params)
    return RunSummary(
        run_id=run_id, domain=context.domain, domain_slug=context.domain_slug,
        constraints=context.constraints, raw_constraints=context.raw_constraints,
        constraint_params=context.constraint_params, created=created,
        duration_seconds=duration_seconds, dry_run=dry_run, status=status,
        publication_status=publication_status, budget=budget or RunBudget(), stats=stats,
        context=context.stats, input_quality=context.input_quality,
        retained_quality=context.retained_quality, usage=usage,
        opportunities=[_entry(opp, context, paths.get(opp.am_id, "")) for opp in ranked],
        notes=run_notes(context, ranked, policy),
    )


__all__ = ["render_report", "render_run_md", "render_summary"]
