"""Human-readable evaluation, written next to the run report."""

from __future__ import annotations

from automation_miner.evaluation.schemas import JudgedBrief, PortfolioJudgement, RunEvaluation

_BRIEF_TABLE = [
    "## Briefs",
    "",
    "| ID | Title | Overall | Spec | Insight | Action | Domain | Honesty | Read |",
    "|---|---|---|---|---|---|---|---|---|",
]


def _overview(e: RunEvaluation) -> list[str]:
    return [
        f"# Evaluation — `{e.run_id}`",
        "",
        f"- **Status:** {e.status} · **Mode:** {e.analysis_mode}",
        f"- **Published:** {e.published}/{e.total} ({e.publication_rate:.0%}), "
        f"{e.discovery_hypotheses} framed as discovery hypotheses",
        f"- **Cost:** {e.model_calls} model calls, {e.total_tokens:,} tokens, "
        f"{e.duration_seconds / 60:.1f} min",
        f"- **Lint:** {e.lint_errors} errors, {e.hedges} provenance hedges",
    ]


def _brief_rows(briefs: list[JudgedBrief]) -> list[str]:
    rows = []
    for item in briefs:
        j = item.judgement
        rows.append(
            f"| {item.am_id} | {item.title} | {j.overall} | {j.specificity} | {j.insight} | "
            f"{j.actionability} | {j.domain_expertise} | {j.epistemic_honesty} | {j.readability} |"
        )
    for item in briefs:
        j = item.judgement
        rows += ["", f"### {item.am_id} — {item.title}", ""]
        rows += [f"- ➕ {s}" for s in j.strengths] + [f"- ➖ {w}" for w in j.weaknesses]
        rows += [f"- ⚠️ fabricated: {f}" for f in j.fabricated_facts]
    return rows


def _portfolio(p: PortfolioJudgement) -> list[str]:
    lines = ["", "## Portfolio", ""]
    lines.append(f"Diversity {p.diversity}/5 · coverage {p.coverage}/5 · ranking {p.ranking_sanity}/5")
    lines += ["", p.summary]
    lines += [f"- missed: {m}" for m in p.missed_opportunities]
    return lines + [f"- near-duplicate: {d}" for d in p.near_duplicates]


def _judge(e: RunEvaluation) -> list[str]:
    lines = [
        f"- **Judge:** `{e.judge_model}` · fabricated facts flagged: {e.fabricated_facts} "
        f"· lowest overall: {e.min_overall}/5",
        "",
        "## Judge means (1–5)",
        "",
        "| " + " | ".join(e.means) + " |",
        "|" + "---|" * len(e.means),
        "| " + " | ".join(f"{v:.2f}" for v in e.means.values()) + " |",
        "",
    ]
    lines += _BRIEF_TABLE + _brief_rows(e.briefs)
    return lines + (_portfolio(e.portfolio) if e.portfolio is not None else [])


def render_evaluation(evaluation: RunEvaluation) -> str:
    lines = _overview(evaluation)
    if evaluation.judge_model:
        lines += _judge(evaluation)
    findings = [(lint.brief, f) for lint in evaluation.lint for f in lint.findings]
    if findings:
        lines += ["", "## Lint findings", ""]
        lines += [f"- `{brief}` {f.severity} `{f.code}`: {f.excerpt}" for brief, f in findings]
    return "\n".join(lines) + "\n"
