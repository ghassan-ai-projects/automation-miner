"""Building blocks for opportunity briefs: text helpers and computed sections.

The brief used to render only the draft. Everything the pipeline computed about
*quality* — the per-factor score rationale, the critic's score, how many refine
rounds it took, which constraint overrides fired, which code calibrations or
repairs were applied, and which evidence the draft rests on — was persisted to
JSON and then never shown. A published brief could not justify its own ICE
score. The Scoring & Confidence and Evidence sections close that gap.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

from automation_miner.schemas import InputQuality, Opportunity
from automation_miner.scoring import active_filters

FILTER_LABELS: dict[str, str] = {
    "low_hanging": "low-hanging fruit",
    "high_value": "high-value",
    "vision": "vision/moonshot",
}


def title_slug(title: str) -> str:
    """Short slug for the brief filename."""
    text = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return text[:60].strip("-") or "opportunity"


def yaml_scalar(text: str) -> str:
    """JSON strings are valid YAML scalars and preserve quotes, slashes, and newlines."""
    return json.dumps(text, ensure_ascii=False)


def cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>")


def bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- (none identified)"


def numbered(items: list[str]) -> str:
    cleaned = [re.sub(r"^\s*\d+[.)]\s*", "", item) for item in items]
    return "\n".join(f"{i}. {item}" for i, item in enumerate(cleaned, 1))


def is_discovery_hypothesis(
    opp: Opportunity, input_quality: InputQuality | None = None
) -> bool:
    """Frame uncertain output, including all thin-input output, as discovery work."""
    if opp.artifact_type == "discovery_hypothesis":
        return True
    return (
        input_quality is not None and input_quality.level == "thin"
    ) or opp.score.confidence <= 2 or not opp.draft.evidence_refs


_CALIBRATION_INTRO = (
    "Automated calibration (code cross-checked the proposed factors against "
    "this draft's own effort, impact and risk estimates):"
)
_UNVERIFIED = (
    " — these ids do not exist in the run's evidence index, so the claims "
    "attached to them are unsupported."
)


def _notes(title: str, notes: list[str]) -> list[str]:
    return ["", title, "", *[f"- {note}" for note in notes]] if notes else []


def scoring_section(opp: Opportunity) -> str:
    """Per-factor rationale plus every automated judgement applied to the score."""
    s = opp.score
    rounds = f"{opp.iterations} iteration{'s' if opp.iterations != 1 else ''}"
    lines = [
        f"**ICE {opp.ice}** — {opp.tier.label} · Impact {s.impact} × "
        f"Confidence {s.confidence} × Ease {s.ease}",
        "",
        f"- **Impact {s.impact}** — {s.impact_rationale}",
        f"- **Confidence {s.confidence}** — {s.confidence_rationale}",
        f"- **Ease {s.ease}** — {s.ease_rationale}",
        "",
        f"Critic score **{opp.critique_overall}/10** after {rounds}.",
    ]
    if flags := active_filters(opp):
        lines += ["", f"Strategic filters: {', '.join(FILTER_LABELS.get(k, k) for k in flags)}."]
    lines += _notes(_CALIBRATION_INTRO, opp.calibration)
    lines += _notes("Quality repairs:", opp.repair_notes)
    lines += _notes("Constraint overrides applied:", opp.overrides_applied)
    if not opp.published:
        lines += ["", "> **Excluded from the published portfolio for this run:**"]
        lines += [f"> - {reason}" for reason in opp.exclusion_reasons]
    return "\n".join(lines)


def evidence_section(
    opp: Opportunity, run_id: str, labels: Mapping[str, str] | None = None
) -> str:
    """Which evidence the draft cites — with source and location — and any that did not resolve."""
    if not opp.draft.evidence_refs:
        return (
            "No evidence ids were cited. Treat the claims above as inference rather "
            "than grounded findings."
        )
    labels = labels or {}
    lines = [
        "Observed facts in this brief come from these source passages "
        f"(ids refer to `trace/context.json` in run `{run_id}`):",
        "",
    ]
    lines += [
        f"- `{ref}`" + (f" — {labels[ref]}" if labels.get(ref) else "")
        for ref in opp.draft.evidence_refs
    ]
    if opp.unresolved_refs:
        refs = ", ".join(f"`{ref}`" for ref in opp.unresolved_refs)
        lines += ["", f"> **Unverified citations:** {refs}{_UNVERIFIED}"]
    return "\n".join(lines)


def validation_section(opp: Opportunity, heading: str) -> str:
    d = opp.draft
    return (
        f"## {heading}\n\n"
        f"### Questions to answer\n{bullets(d.validation_questions)}\n\n"
        f"### Working assumptions\n{bullets(d.assumptions)}\n"
    )


def validation_criteria(opp: Opportunity) -> str:
    """Measure the brief's own projections, so validation has concrete targets."""
    criteria = [f"- {metric}" for metric in opp.draft.success_metrics]
    if not criteria:
        criteria = [
            f"- {row.dimension.strip()}: measured result vs. projected {row.improvement.strip()}"
            for row in opp.draft.impact_analysis[:3]
            if row.dimension.strip() and row.improvement.strip()
        ]
    criteria += [
        "- Exception and override rate at each human-in-the-loop point",
        "- What did this analysis miss?",
    ]
    return "\n".join(criteria)
