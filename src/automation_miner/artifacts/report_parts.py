"""Shared building blocks for the run report, summary, and run log."""

from __future__ import annotations


from automation_miner.artifacts.briefs import is_discovery_hypothesis
from automation_miner.schemas import (
    RankedPain,
    LAYER_TITLES,
    ContextPacket,
    Opportunity,
    PortfolioStats,
    RunBudget,
    RunUsage,
    Tier,
)
from automation_miner.scoring import (
    active_filters,
    published,
)

FILTER_HEADINGS: dict[str, str] = {
    "low_hanging": "Low-hanging fruit (Ease ≥ 4, Impact ≥ 3) — immediate action",
    "high_value": "High-value (ICE ≥ 40, Risk ≤ Medium) — prioritized backlog",
    "vision": "Vision/moonshot (Impact = 5, Ease ≤ 2) — strategic, note for future",
}

TIER_ORDER: tuple[Tier, ...] = (Tier.VISION, Tier.HIGH, Tier.MEDIUM, Tier.LOW)


def cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>")


def tokens(count: int) -> str:
    if count >= 1_000_000:
        return f"{count / 1_000_000:.2f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}k"
    return str(count)


def ice_row(index: int, opp: Opportunity, with_tier: bool = True) -> str:
    d = opp.draft
    tier = f" {opp.tier.value} |" if with_tier else ""
    return (
        f"| {index} | {opp.am_id} | {cell(d.title)} | {opp.score.impact} | "
        f"{opp.score.confidence} | {opp.score.ease} | {opp.ice} |{tier} "
        f"{d.layer.value} | {d.effort.value.title()} | {d.risk_level.value.title()} | "
        f"{opp.critique_overall} |"
    )


def _budget_line(budget: RunBudget) -> str:
    spend = f", ${budget.max_cost_usd:g}" if budget.max_cost_usd else ""
    return (
        f"- **Run budget:** {budget.max_attempts} attempts, "
        f"{tokens(budget.max_tokens)} tokens, {budget.max_seconds:g}s wall clock{spend}"
    )


def usage_lines(usage: RunUsage, budget: RunBudget | None = None) -> list[str]:
    if not usage.calls and not usage.attempts:
        return []
    exactness = "provider-reported" if usage.exact else "estimated"
    retried = f" ({usage.retries} retried)" if usage.retries else ""
    lines = [
        f"- **Model calls:** {usage.calls}{retried}",
        f"- **Admission:** {usage.logical_calls} logical call(s), {usage.attempts} attempt(s)",
        f"- **Tokens ({exactness}):** {tokens(usage.prompt_tokens)} in, "
        f"{tokens(usage.completion_tokens)} out, {tokens(usage.total_tokens)} total",
    ]
    if usage.cost_usd:
        lines.append(f"- **Spend (provider-reported):** ${usage.cost_usd:.4f}")
    if usage.attempted_tokens:
        lines.append(
            f"- **Observed attempt tokens:** {tokens(usage.attempted_tokens)} "
            "(includes failed or conservatively bounded attempts)"
        )
    if budget is not None:
        lines.append(_budget_line(budget))
    busiest = sorted(usage.by_role.items(), key=lambda kv: -kv[1].total_tokens)[:3]
    if busiest:
        detail = ", ".join(f"{role} {c.calls}×/{tokens(c.total_tokens)}" for role, c in busiest)
        lines.append(f"- **Heaviest roles:** {detail}")
    return lines


def context_lines(context: ContextPacket) -> list[str]:
    stats = context.stats
    lines = [
        f"- **Source:** {context.source_kind} input, {stats.included_files} file(s) read"
        + (f", {stats.skipped_files} skipped" if stats.skipped_files else ""),
        f"- **Evidence index:** {stats.chunks} chunks, {tokens(stats.evidence_tokens)} tokens "
        f"({stats.budget_used_pct}% of a {tokens(stats.budget_tokens)} budget)",
        f"- **Input quality:** {context.input_quality.level} "
        f"({context.input_quality.score}/100) — {context.input_quality.warning}",
        f"- **Retained-evidence quality:** {context.retained_quality.level} "
        f"({context.retained_quality.score}/100) — {context.retained_quality.warning}",
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


def skipped_section(context: ContextPacket) -> list[str]:
    if not context.skipped:
        return []
    lines = ["", "## Files Not Read", "", "| File | Reason |", "|------|--------|"]
    for skip in context.skipped:
        name = skip.path.rsplit("/", 1)[-1]
        lines.append(f"| `{cell(name)}` | {cell(skip.reason)} |")
    return lines


def excluded_section(ranked: list[Opportunity]) -> list[str]:
    excluded = [o for o in ranked if not o.published]
    if not excluded:
        return []
    lines = [
        "",
        "## Excluded from Published Portfolio",
        "",
        "These were fully drafted, critiqued and scored, then held back by the "
        "constraints or quality gates for this run. They are retained in `opportunities.json` "
        "and `summary.json`.",
        "",
        "| ID | Name | ICE | Reason |",
        "|----|------|-----|--------|",
    ]
    for opp in excluded:
        reasons = "; ".join(opp.exclusion_reasons) or "policy"
        lines.append(
            f"| {opp.am_id} | {cell(opp.draft.title)} | {opp.ice} | {cell(reasons)} |"
        )
    return lines


def recommendation(ranked: list[Opportunity]) -> list[str]:
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


def _glance(position: int, opp: Opportunity, context: ContextPacket) -> list[str]:
    hypothesis = is_discovery_hypothesis(opp, context.input_quality)
    kind = "discovery hypothesis" if hypothesis else "opportunity brief"
    lines = [
        f"### {position}. {opp.am_id} — {opp.draft.title}",
        "",
        f"ICE {opp.ice} ({opp.tier.value}) · {LAYER_TITLES[opp.draft.layer]} · "
        f"effort {opp.draft.effort.value} · {kind}",
        "",
        f"- **Problem:** {first_sentence(opp.draft.problem)}",
        f"- **Automation:** {first_sentence(opp.draft.proposed_automation)}",
    ]
    row = next((r for r in opp.draft.impact_analysis if r.improvement.strip()), None)
    if row is not None:
        label = "estimate" if row.assumption else "observed baseline"
        lines.append(
            f"- **Headline impact:** {row.dimension.strip()} — {row.current.strip()} → "
            f"{row.automated.strip()} ({row.improvement.strip()}; {label})"
        )
    return lines + [""]


def at_a_glance(ranked: list[Opportunity], context: ContextPacket, limit: int = 5) -> list[str]:
    """The decision view: what each top opportunity fixes, how, and what it is worth."""
    live = published(ranked)
    if not live:
        return []
    lines = ["", "## At a Glance", ""]
    for position, opp in enumerate(live[:limit], 1):
        lines += _glance(position, opp, context)
    if len(live) > limit:
        lines.append(f"…and {len(live) - limit} more in the ranking below.")
    return lines


def strategic_key(opp: Opportunity, key: str) -> bool:
    return key in active_filters(opp)


def run_notes(context: ContextPacket, ranked: list[Opportunity], policy: object) -> list[str]:
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


def first_sentence(text: str, limit: int = 240) -> str:
    """First sentence, or the text cut at a word boundary with an ellipsis."""
    flat = " ".join(text.split())
    cut = flat.find(". ")
    if 0 < cut <= limit:
        return flat[: cut + 1]
    if len(flat) <= limit:
        return flat
    return flat[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def top_layer(stats: PortfolioStats) -> str:
    if not stats.by_layer:
        return "none"
    layer, count = max(stats.by_layer.items(), key=lambda kv: (kv[1], kv[0]))
    return f"{layer} ({count} opportunit{'y' if count == 1 else 'ies'})"


_PAIN_HEADER = [
    "",
    "## Biggest Pains Found",
    "",
    "Ranked by code from the layer analyses: observed weekly hours first, then other "
    "quantified costs.",
    "",
    "| ID | Pain | Size | Basis | Addressed by |",
    "|----|------|------|-------|--------------|",
]


def pain_coverage(ranked: list[Opportunity], ledger: list[RankedPain], top: int = 8) -> list[str]:
    """The biggest quantified pains and which published brief addresses each."""
    if not ledger:
        return []
    by_pain: dict[str, list[str]] = {}
    for opp in published(ranked):
        for pid in opp.draft.addresses_pains:
            by_pain.setdefault(pid, []).append(opp.am_id)
    lines = list(_PAIN_HEADER)
    for pain in ledger[:top]:
        hours = f"~{pain.weekly_hours:g} h/week" if pain.weekly_hours is not None else ""
        size = "; ".join(part for part in (hours, pain.other_cost) if part) or "—"
        addressed = ", ".join(by_pain.get(pain.id, [])) or "**not addressed**"
        basis = "observed" if pain.observed else "estimated"
        lines.append(f"| {pain.id} | {cell(pain.pain)} | {cell(size)} | {basis} | {addressed} |")
    return lines