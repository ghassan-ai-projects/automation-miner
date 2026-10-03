"""Stakeholder one-pager: a run's published opportunities as one HTML page.

The report and briefs are written for the person running the engine. A
process owner or sponsor needs one page they can open, print, or forward:
what was found, how big it is, what the first step is, and how success will
be measured. The page is a single self-contained file (inline CSS, no
scripts, no external requests) and every value is HTML-escaped, because
brief text derives from untrusted source documents.
"""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from automation_miner.artifacts.export_style import ONE_PAGER_CSS
from automation_miner.artifacts.layout import RunLayout
from automation_miner.artifacts.workspace import read_json, write_text
from automation_miner.schemas import Opportunity

DEFAULT_TOP = 5
_MAX_RISKS = 3


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def _list(items: list[str], limit: int | None = None) -> str:
    shown = items[:limit] if limit else items
    return "<ul>" + "".join(f"<li>{_e(item)}</li>" for item in shown) + "</ul>" if shown else ""


def _section(title: str, body: str) -> str:
    return f"<h4>{_e(title)}</h4>{body}" if body else ""


def _badges(opp: Opportunity, status: str) -> str:
    tags = [
        (f"ICE {opp.ice}", f"tier-{opp.tier.value}"), (opp.tier.value, f"tier-{opp.tier.value}"),
        (opp.draft.layer.value, ""), (f"effort {opp.draft.effort.value}", ""),
        (f"risk {opp.draft.risk_level.value}", ""), (status, ""),
    ]
    if opp.artifact_type == "discovery_hypothesis":
        tags.append(("discovery hypothesis — validate first", "hypothesis"))
    spans = "".join(f'<span class="badge {cls}">{_e(text)}</span>' for text, cls in tags)
    return f'<div class="badges">{spans}</div>'


def _impact(opp: Opportunity) -> str:
    rows = "".join(
        f"<tr><td>{_e(r.dimension)}</td><td>{_e(r.current)}</td><td>{_e(r.automated)}</td>"
        f"<td>{_e(r.improvement)}"
        + ('<div class="assumed">assumption</div>' if r.assumption else "")
        + "</td></tr>"
        for r in opp.draft.impact_analysis
    )
    if not rows:
        return ""
    head = "<tr><th>Dimension</th><th>Today</th><th>Automated</th><th>Change</th></tr>"
    return f'<div class="table-wrap"><table>{head}{rows}</table></div>'


def _risks(opp: Opportunity) -> list[str]:
    return [f"{r.risk} — {r.mitigation}" for r in opp.draft.risks[:_MAX_RISKS]]


def _card(rank: int, opp: Opportunity, status: str) -> str:
    d = opp.draft
    first_steps = d.validation_questions if opp.artifact_type == "discovery_hypothesis" else (
        d.implementation.mvp
    )
    left = _section("Problem", f"<p>{_e(d.problem)}</p>") + _section(
        "Proposed automation", f"<p>{_e(d.proposed_automation)}</p>"
    )
    right = _section(
        "Validate first" if opp.artifact_type == "discovery_hypothesis" else "First step (MVP)",
        _list(first_steps, 4),
    ) + _section("Human checkpoints", _list(d.hitl_points, 3))
    bottom = _section("Expected impact", _impact(opp)) + _section(
        "How success is measured", _list(d.success_metrics)
    ) + _section("Main risks", _list(_risks(opp)))
    return (
        f'<article class="card" id="{_e(opp.am_id)}"><h3>{rank}. {_e(d.title)} '
        f'<span class="badge">{_e(opp.am_id)}</span></h3>{_badges(opp, status)}'
        f'<div class="cols"><div>{left}</div><div>{right}</div></div>{bottom}</article>'
    )


def _glance(published: list[Opportunity], statuses: dict[str, str]) -> str:
    rows = "".join(
        f'<tr><td>{rank}</td><td><a href="#{_e(o.am_id)}">{_e(o.draft.title)}</a></td>'
        f'<td>{o.ice}</td><td class="wide">{_e(o.tier.value)}</td>'
        f'<td class="wide">{_e(o.draft.effort.value)}</td>'
        f"<td>{_e(statuses.get(o.am_id, o.status.value))}</td></tr>"
        for rank, o in enumerate(published, 1)
    )
    head = (
        '<tr><th>#</th><th>Opportunity</th><th>ICE</th><th class="wide">Tier</th>'
        '<th class="wide">Effort</th>'
        "<th>Status</th></tr>"
    )
    return f'<div class="table-wrap"><table>{head}{rows}</table></div>'


def _not_published(filtered: list[Opportunity]) -> str:
    items = [f"{o.draft.title} — {'; '.join(o.exclusion_reasons)}" for o in filtered]
    return f"<h2>Considered, not recommended</h2>{_list(items)}" if items else ""


def _facts(summary: dict[str, Any], published: int, total: int) -> str:
    quality = summary.get("input_quality", {}) or {}
    facts = [
        (f"{published} of {total}", "opportunities recommended"),
        (str(quality.get("level", "unknown")), "evidence quality"),
        (str(summary.get("created", ""))[:10], "analysed"),
    ]
    cells = "".join(f"<div><b>{_e(value)}</b>{_e(label)}</div>" for value, label in facts)
    return f'<div class="facts">{cells}</div>'


def _statuses(workspace: Path | None) -> dict[str, str]:
    """Current lifecycle status per AM-id, from the registry when there is one."""
    path = workspace / "registry.json" if workspace else None
    if path is None or not path.is_file():
        return {}
    return {str(e.get("i")): str(e.get("s", "")) for e in read_json(path).get("entries", [])}


def _load(run_dir: Path) -> tuple[dict[str, Any], list[Opportunity]]:
    layout = RunLayout(run_dir)
    if not layout.summary.is_file() or not layout.opportunities.is_file():
        raise ValueError(f"completed run not found at {run_dir}")
    raw = read_json(layout.opportunities).get("opportunities", [])
    return read_json(layout.summary), [Opportunity.model_validate(item) for item in raw]


def render_one_pager(run_dir: Path, workspace: Path | None = None, top: int = DEFAULT_TOP) -> str:
    """The run as one self-contained HTML page for stakeholders."""
    summary, opportunities = _load(run_dir)
    published = [o for o in opportunities if o.published]
    statuses = _statuses(workspace)
    cards = "".join(
        _card(rank, o, statuses.get(o.am_id, o.status.value))
        for rank, o in enumerate(published[: max(1, top)], 1)
    )
    title = f"Automation opportunities: {summary.get('domain', run_dir.name)}"
    body = (
        f"<h1>{_e(title)}</h1><p class=\"meta\">Run {_e(run_dir.name)}</p>"
        f"{_facts(summary, len(published), len(opportunities))}"
        f"<h2>At a glance</h2>{_glance(published, statuses)}<h2>Recommended</h2>{cards}"
        f"{_not_published([o for o in opportunities if not o.published])}"
        "<footer>Generated by automation-miner. Figures marked as assumptions are estimates "
        "to validate; every other figure traces to the source material.</footer>"
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_e(title)}</title><style>{ONE_PAGER_CSS}</style></head>"
        f"<body><main>{body}</main></body></html>\n"
    )


def export_one_pager(
    run_dir: Path, workspace: Path | None = None, out: Path | None = None, top: int = DEFAULT_TOP
) -> Path:
    """Write the one-pager (default ``<run>/one-pager.html``) and return its path."""
    target = out or RunLayout(run_dir).one_pager
    write_text(target, render_one_pager(run_dir, workspace, top))
    return target


__all__ = ["DEFAULT_TOP", "export_one_pager", "render_one_pager"]
