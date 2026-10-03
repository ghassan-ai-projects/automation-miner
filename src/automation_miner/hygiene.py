"""Deterministic prose hygiene for opportunity drafts.

Epistemic status belongs in structured fields (``evidence_refs``,
``assumptions``, ``validation_questions``, impact-row ``assumption`` flags).
When a model writes it into the prose instead — "inferred from S2: '...'; not
explicitly stated" — the brief becomes unreadable without becoming any more
honest. The first real run published a brief with 75 such hedges.

Code can detect this exactly, so it is checked in code: the critique loop
treats a hedged draft as not yet passing and feeds the excerpts back to the
refiner, and the evaluation lint counts any residue as an error.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from automation_miner.schemas import OpportunityDraft

HEDGE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("inferred-from-source", r"\binferred (?:from|via) \[?S\d+"),
    ("not-explicitly-stated", r"\bnot explicitly (?:stated|mentioned|described|confirmed)\b"),
    ("no-evidence-provided", r"\bno evidence (?:is )?(?:provided|describes|supports|given)\b"),
    (
        "not-in-evidence",
        r"\bnot (?:provided|sourced|confirmed|described|mentioned) (?:in|from|by) "
        r"(?:the )?(?:supplied |source )?(?:evidence|S\d+)",
    ),
    ("evidence-does-not", r"\b(?:the )?evidence does not\b"),
    ("inferred-label", r"\(inferred\b|\binferred:"),
    ("quoted-source", r"\bS\d+:\s*['\"‘“]"),
    ("inline-citation", r"\[S\d+(?:\s*,\s*S\d+)*\]"),
)
_COMPILED = [(code, re.compile(pattern, re.IGNORECASE)) for code, pattern in HEDGE_PATTERNS]


@dataclass(frozen=True)
class Hedge:
    code: str
    field: str
    excerpt: str


def find_hedges(text: str, field: str = "") -> list[Hedge]:
    """Every provenance hedge in ``text`` with a short excerpt around it."""
    spans = sorted(
        (match.start(), match.end(), code)
        for code, pattern in _COMPILED
        for match in pattern.finditer(text)
    )
    found: list[Hedge] = []
    last_end = -1
    for start, end, code in spans:
        if start < last_end:  # overlapping patterns describe one hedge
            continue
        last_end = end
        excerpt = text[max(0, start - 40) : end + 40].replace("\n", " ").strip()
        found.append(Hedge(code, field, excerpt))
    return found


_LIST_FIELDS = (
    "inputs", "steps", "outputs", "hitl_points", "technical_requirements", "dependencies",
    "constraints", "assumptions", "validation_questions", "success_metrics",
)


def _prose_fields(draft: OpportunityDraft) -> list[tuple[str, str]]:
    """Every reader-facing text field of a draft, labelled by field name."""
    fields = [
        ("problem", draft.problem),
        ("proposed_automation", draft.proposed_automation),
        ("agent_topology", draft.agent_topology),
    ]
    fields += [(name, item) for name in _LIST_FIELDS for item in getattr(draft, name)]
    fields += [
        ("impact_analysis", text)
        for row in draft.impact_analysis
        for text in (row.dimension, row.current, row.automated, row.improvement, row.basis)
    ]
    fields += [
        (f"implementation.{phase}", item)
        for phase in ("mvp", "expansion", "autonomy")
        for item in getattr(draft.implementation, phase)
    ]
    fields += [("risks", text) for risk in draft.risks for text in (risk.risk, risk.mitigation)]
    return fields


def draft_hedges(draft: OpportunityDraft) -> list[Hedge]:
    return [hedge for field, text in _prose_fields(draft) for hedge in find_hedges(text, field)]


def hygiene_feedback(hedges: list[Hedge], limit: int = 12) -> list[str]:
    """Writing issues the refiner can act on, one per offending excerpt."""
    issues = [
        f"{hedge.field}: remove evidence commentary from prose — \"{hedge.excerpt}\""
        for hedge in hedges[:limit]
    ]
    if len(hedges) > limit:
        issues.append(f"... and {len(hedges) - limit} more instances of evidence commentary")
    return issues
