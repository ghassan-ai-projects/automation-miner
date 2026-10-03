"""Lifecycle of a published brief: status changes and measured outcomes.

A brief predicts value ("handling time: baseline 9 min, target -50%"), and
until now nothing recorded what happened next: status was a frontmatter field
to edit by hand, and a measured result had nowhere to go. Without outcomes the
engine cannot learn whether its ICE scores mean anything.

Every change is an append-only event in ``lifecycle.json`` at the workspace
root. The brief stays the readable view: its frontmatter carries the current
status and latest verdict (so the registry sees them), and a Lifecycle
section renders the history.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from automation_miner.artifacts.registry import STATUS_ALIASES, parse_frontmatter, reindex_locked
from automation_miner.artifacts.workspace import (
    Workspace,
    read_json,
    workspace_transaction_lock,
    write_json,
    write_text,
)
from automation_miner.schemas import LifecycleEvent, LifecycleLedger, OppStatus, Verdict

LEDGER = "lifecycle.json"
_SECTION = "## Lifecycle"
_NEXT_SECTION = re.compile(r"^## ", re.MULTILINE)
_CRITERIA = re.compile(r"^Success measures:\n((?:- .*\n?)+)", re.MULTILINE)


def load_ledger(base: Path) -> LifecycleLedger:
    path = base / LEDGER
    return LifecycleLedger.model_validate(read_json(path)) if path.is_file() else LifecycleLedger()


def parse_status(value: str) -> OppStatus:
    """A lifecycle status from user input, accepting the documented aliases."""
    key = STATUS_ALIASES.get(value.strip().casefold(), value.strip().casefold())
    try:
        return OppStatus(key)
    except ValueError:
        names = ", ".join(status.value for status in OppStatus)
        raise ValueError(f"unknown status {value!r}; use one of: {names}") from None


def success_measures(brief: str) -> list[str]:
    """The brief's own success measures, in the order it lists them."""
    match = _CRITERIA.search(brief)
    lines = match.group(1).splitlines() if match else []
    return [line[2:].strip() for line in lines if line.startswith("- ")]


def resolve_metric(brief: str, metric: str) -> str:
    """``2`` names the brief's second success measure; any other text is kept."""
    if not metric.strip().isdigit():
        return metric.strip()
    measures = success_measures(brief)
    index = int(metric) - 1
    if not 0 <= index < len(measures):
        raise ValueError(f"the brief lists {len(measures)} success measures; got {metric}")
    return measures[index]


def _brief(base: Path, am_id: str) -> tuple[str, Path]:
    found = Workspace(base).find_opportunity(am_id)
    if found is None:
        raise ValueError(f"published opportunity {am_id.upper()} not found")
    return found


def _frontmatter_set(text: str, key: str, value: str) -> str:
    """Set one top-level frontmatter key, adding it before the closing fence if absent."""
    end = text.find("\n---", 3)
    head, rest = text[:end], text[end:]
    line = f'{key}: "{value}"'
    pattern = re.compile(rf"^{re.escape(key)}:.*$", re.MULTILINE)
    head = pattern.sub(line, head, count=1) if pattern.search(head) else f"{head}\n{line}"
    return head + rest


def _event_row(event: LifecycleEvent) -> str:
    if event.kind == "status" and event.status is not None:
        previous = f" (from {event.previous.value})" if event.previous else ""
        what, detail = f"status → {event.status.value}{previous}", event.note
    else:
        change = " → ".join(part for part in (event.baseline, event.measured) if part)
        what = f"outcome: {event.verdict or 'measured'}"
        detail = "; ".join(part for part in (f"{event.metric}: {change}", event.note) if part)
    return f"| {event.at[:10]} | {what} | {detail.replace('|', '/')} |"


def render_section(events: list[LifecycleEvent]) -> str:
    rows = [_event_row(event) for event in events]
    return "\n".join([_SECTION, "", "| Date | Event | Detail |", "|---|---|---|", *rows]) + "\n"


def _with_section(text: str, events: list[LifecycleEvent]) -> str:
    """Replace (or append) the brief's Lifecycle section."""
    start = text.find(f"\n{_SECTION}\n")
    if start != -1:
        following = _NEXT_SECTION.search(text, start + len(_SECTION) + 2)
        text = text[:start] + (("\n" + text[following.start():]) if following else "\n")
    return text.rstrip("\n") + "\n\n" + render_section(events)


def _record(base: Path, event: LifecycleEvent, path: Path, fields: dict[str, str]) -> None:
    """Append the event, refresh the brief, and rebuild the registry (caller holds the lock)."""
    ledger = load_ledger(base)
    ledger.events.append(event)
    write_json(base / LEDGER, ledger)
    text = path.read_text(encoding="utf-8")
    for key, value in {**fields, "updated": event.at[:10]}.items():
        text = _frontmatter_set(text, key, value)
    write_text(path, _with_section(text, ledger.for_id(event.am_id)))
    reindex_locked(base)


def _now() -> str:
    return f"{datetime.now():%Y-%m-%dT%H:%M:%S}"


def set_status(base: Path, am_id: str, status: str, note: str = "") -> LifecycleEvent:
    """Move a published brief to a new lifecycle status."""
    target = parse_status(status)
    with workspace_transaction_lock(base):
        am_id, path = _brief(base, am_id)
        meta = parse_frontmatter(path.read_text(encoding="utf-8"))
        current = parse_status(str(meta.get("status") or OppStatus.IDENTIFIED.value))
        if current is target:
            raise ValueError(f"{am_id} is already {target.value}")
        event = LifecycleEvent(
            am_id=am_id, at=_now(), kind="status", status=target, previous=current, note=note
        )
        _record(base, event, path, {"status": target.value})
    return event


def record_outcome(
    base: Path, am_id: str, metric: str, measured: str, *, baseline: str = "",
    verdict: Verdict | None = None, note: str = "",
) -> LifecycleEvent:
    """Record one measured result against a brief's success measure."""
    if not measured.strip():
        raise ValueError("a measured value is required")
    with workspace_transaction_lock(base):
        am_id, path = _brief(base, am_id)
        event = LifecycleEvent(
            am_id=am_id, at=_now(), kind="outcome",
            metric=resolve_metric(path.read_text("utf-8"), metric) or "unspecified",
            baseline=baseline.strip(), measured=measured.strip(), verdict=verdict, note=note,
        )
        fields: dict[str, str] = {"outcome": verdict} if verdict else {}
        _record(base, event, path, fields)
    return event


def outcome_rows(root: Path) -> list[dict[str, Any]]:
    """Every measured outcome joined with the score the brief was published at."""
    registry_path = root / "registry.json"
    registry = read_json(registry_path) if registry_path.is_file() else {}
    entries = {entry["i"]: entry for entry in registry.get("entries", [])}
    rows = []
    for event in load_ledger(root).events:
        if event.kind != "outcome":
            continue
        entry = entries.get(event.am_id, {})
        rows.append({
            "am_id": event.am_id, "title": entry.get("t", ""), "ice": entry.get("ice"),
            "tier": entry.get("tr", ""), "metric": event.metric, "baseline": event.baseline,
            "measured": event.measured, "verdict": event.verdict, "at": event.at,
        })
    return rows


__all__ = [
    "LEDGER", "load_ledger", "outcome_rows", "parse_status", "record_outcome", "render_section",
    "resolve_metric", "set_status", "success_measures",
]
