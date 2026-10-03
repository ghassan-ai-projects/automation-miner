"""Console rendering for CLI commands; library code never prints."""

from __future__ import annotations

import sys
from typing import Any, Callable, TextIO

from automation_miner.execution import StageProgress
from automation_miner.schemas import InputQuality


def stream_for(as_json: bool) -> TextIO:
    """Human chatter goes to stderr when stdout carries JSON."""
    return sys.stderr if as_json else sys.stdout


def preflight_printer(stream: TextIO) -> Callable[[InputQuality], None]:
    def show(profile: InputQuality) -> None:
        print(f"Preflight: {profile.level} evidence ({profile.score}/100)", file=stream)
        print(f"Preflight warning: {profile.warning}", file=stream)

    return show


def progress_printer(stream: TextIO) -> Callable[[StageProgress], None]:
    def show(progress: StageProgress) -> None:
        minutes, seconds = divmod(int(progress.elapsed_seconds), 60)
        spend = f" · ${progress.cost_usd:.4f}" if progress.cost_usd else ""
        print(
            f"[{minutes:02d}:{seconds:02d}] {progress.stage.replace('_', ' ')}"
            f" · {progress.calls} calls · {progress.tokens:,} tokens{spend}",
            file=stream,
            flush=True,
        )

    return show


def _context_line(context: dict[str, Any]) -> str:
    line = (
        f"Context: {context.get('included_files', 0)} file(s), "
        f"{context.get('chunks', 0)} chunks, {context.get('evidence_tokens', 0):,} tokens "
        f"({context.get('budget_used_pct', 0)}% of budget)"
    )
    if context.get("skipped_files"):
        line += f", {context['skipped_files']} skipped"
    return line + (", digested" if context.get("digested") else "")


def _opportunity_lines(entries: list[dict[str, Any]]) -> list[str]:
    published = [e for e in entries if e.get("eligibility") == "published"]
    filtered = [e for e in entries if e.get("eligibility") != "published"]
    lines = [f"Opportunities: {len(published)} published" + (
        f", {len(filtered)} filtered" if filtered else ""
    )]
    lines += [
        f"  {e['am_id']}  ICE {e['ice']:>3}  {e['tier']:<6} [{e['layer']}] {e['title']}"
        for e in published
    ]
    lines += [
        f"  {e['am_id']}  ICE {e['ice']:>3}  filtered — {(e.get('exclusion_reasons') or ['policy'])[0]}"
        for e in filtered
    ]
    return lines


def _cost_lines(usage: dict[str, Any], budget: dict[str, Any]) -> list[str]:
    if not usage.get("calls"):
        return []
    kind = "reported" if usage.get("exact") else "estimated"
    spend = f", ${usage['cost_usd']:.4f}" if usage.get("cost_usd") else ""
    retried = f", {usage['retries']} retried" if usage.get("retries") else ""
    lines = [
        f"Cost: {usage['calls']} model calls, {usage.get('total_tokens', 0):,} tokens "
        f"({kind}){spend}{retried}"
    ]
    if budget:
        lines.append(
            f"Budget: {usage.get('attempts', 0)}/{budget.get('max_attempts', '?')} attempts, "
            f"{usage.get('total_tokens', 0):,}/{budget.get('max_tokens', '?')} tokens"
        )
    return lines


def run_lines(result: dict[str, Any], summary: dict[str, Any]) -> list[str]:
    """The human summary printed after ``mine``."""
    lines = [f"Run: {result['run_id']}"]
    if summary.get("status"):
        lines.append(f"Status: {summary['status']}")
    if summary.get("context"):
        lines.append(_context_line(summary["context"]))
    lines += _opportunity_lines(summary.get("opportunities", []))
    stats = summary.get("stats", {})
    if stats:
        lines.append(
            f"Portfolio: avg ICE {stats.get('avg_ice', 0)}, "
            f"median {stats.get('median_ice', 0)}, top {stats.get('top_ice', 0)}"
        )
    lines += _cost_lines(summary.get("usage", {}), summary.get("budget", {}))
    lines += [f"Note: {note}" for note in summary.get("notes", [])[:5]]
    return lines + [f"Report: {result.get('report_path', '')}"]


def reader_lines(rows: list[Any], errors: list[str], suffix_count: int) -> list[str]:
    lines = [f"{'READER':<10} {'STATUS':<10} {'SOURCE':<12} FORMATS"]
    for row in rows:
        status = "ready" if row.available else "unavailable"
        lines.append(f"{row.name:<10} {status:<10} {row.source:<12} {' '.join(row.suffixes)}")
        if not row.available:
            lines.append(f"{'':<10} → {row.reason}")
    return lines + [f"\n{len(rows)} readers, {suffix_count} formats registered."]
