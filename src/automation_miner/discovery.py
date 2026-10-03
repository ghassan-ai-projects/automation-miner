"""Opportunity discovery support: the pain ledger and its coverage check.

The first real runs found plausible ideas but missed the obvious big wins: the
judge listed policy lookup, API claim creation, and duplicate detection as
missing while the portfolio spent slots on photo compression. A consultant
avoids that by sizing the waste first. Layer analysts now report each pain with
volume and minutes; this module ranks them in code (largest observed weekly
hours first), gives each a citable id, and checks which top pains the planned
portfolio actually addresses. Ranking is deterministic, so two runs over the
same analyses produce the same ledger.
"""

from __future__ import annotations

import re

from automation_miner.schemas import (
    LAYER_ORDER,
    Layer,
    CandidatePortfolio,
    LayerAnalysis,
    PainPoint,
    RankedPain,
)

LEDGER_SIZE = 20
COVERAGE_TOP = 5
_WORDS = re.compile(r"[a-z0-9]+")


def _key(pain: PainPoint) -> str:
    return " ".join(_WORDS.findall(pain.pain.casefold()))


def _rank_key(item: tuple[int, PainPoint]) -> tuple[int, float, int, str]:
    """Measured hours, then estimated hours, then other costs, then vague pains.

    An estimate never displaces a measured pain: the model can inflate an
    estimate, but it cannot inflate what the evidence states.
    """
    layer_index, pain = item
    hours = pain.weekly_hours
    if hours is not None:
        tier = 0 if pain.observed else 1
    elif pain.other_cost.strip():
        tier = 2 if pain.observed else 3
    else:
        tier = 4
    return (tier, -(hours or 0.0), layer_index, _key(pain))


_STOPWORDS = frozenset(
    "a an and are as at be by for from in into is it its of on or per that the this to "
    "with without when which while who will was were has have had takes requires".split()
)
# Two pains are the same pain when most of the shorter one's content words
# appear in the longer one ("policy lookup without a number ... 6 minutes" vs
# "policy identification without a policy number ... searching").
NEAR_DUPLICATE_OVERLAP = 0.6


def _content_words(pain: PainPoint) -> frozenset[str]:
    return frozenset(w for w in _WORDS.findall(pain.pain.casefold()) if w not in _STOPWORDS)


def _near_duplicate(words: frozenset[str], kept: list[frozenset[str]]) -> bool:
    return any(
        len(words & other) / max(1, min(len(words), len(other))) >= NEAR_DUPLICATE_OVERLAP
        for other in kept
    )


def build_pain_ledger(
    analyses: list[LayerAnalysis], limit: int = LEDGER_SIZE
) -> list[RankedPain]:
    """Merge, de-duplicate, and rank every layer's pains; P1 is the largest.

    Ranking happens before de-duplication, so of two descriptions of one pain
    the better-sized one survives.
    """
    pool = [
        (LAYER_ORDER.index(analysis.layer), pain, analysis.layer)
        for analysis in analyses
        for pain in analysis.pain_points
        if _key(pain)
    ]
    kept: list[tuple[PainPoint, Layer]] = []
    seen: list[frozenset[str]] = []
    for _, pain, layer in sorted(pool, key=lambda item: _rank_key((item[0], item[1]))):
        words = _content_words(pain)
        if not _near_duplicate(words, seen):
            seen.append(words)
            kept.append((pain, layer))
    return [
        RankedPain(id=f"P{index}", layer=layer, **pain.model_dump())
        for index, (pain, layer) in enumerate(kept[:limit], 1)
    ]


def same_domain(slug: str, other: str) -> bool:
    """Whether two domain slugs name the same domain.

    The same domain mined from ``claims-intake/`` and from
    ``motor-claims-intake-sop.md`` gets different slugs; most of the shorter
    slug's words appearing in the longer one means they are the same domain.
    """
    words = frozenset(w for w in slug.split("-") if w and w not in _STOPWORDS)
    others = frozenset(w for w in other.split("-") if w and w not in _STOPWORDS)
    if not words or not others:
        return slug == other
    return len(words & others) / min(len(words), len(others)) >= NEAR_DUPLICATE_OVERLAP


def render_ledger(ledger: list[RankedPain]) -> str:
    """Compact one-line-per-pain view for the planner prompt and reports."""
    lines = []
    for pain in ledger:
        size = []
        if pain.weekly_hours is not None:
            size.append(f"~{pain.weekly_hours:g} h/week")
        if pain.volume_per_week is not None:
            size.append(f"{pain.volume_per_week:g}/week")
        if pain.minutes_per_item is not None:
            size.append(f"{pain.minutes_per_item:g} min each")
        if pain.other_cost:
            size.append(pain.other_cost)
        basis = "observed" if pain.observed else "estimated"
        refs = f" [{', '.join(pain.evidence_refs)}]" if pain.evidence_refs else ""
        lines.append(
            f"{pain.id} ({pain.layer.value}, {basis}): {pain.pain}"
            + (f" — {'; '.join(size)}" if size else "")
            + refs
        )
    return "\n".join(lines)


def material_pains(ledger: list[RankedPain], top: int = COVERAGE_TOP) -> list[RankedPain]:
    """The top pains a portfolio must address: sized ones among the first ``top``."""
    return [
        pain
        for pain in ledger[:top]
        if pain.weekly_hours is not None or pain.other_cost.strip()
    ]


def uncovered_pains(
    ledger: list[RankedPain], portfolio: CandidatePortfolio, top: int = COVERAGE_TOP
) -> list[RankedPain]:
    """Material top pains no candidate addresses.

    A portfolio cannot cover more top pains than it has candidates, so a
    requested size such as ``ideas=3`` shrinks the obligation to the top 3.
    """
    addressed = {pid for candidate in portfolio.candidates for pid in candidate.addresses_pains}
    window = min(top, len(portfolio.candidates))
    return [pain for pain in material_pains(ledger, window) if pain.id not in addressed]


def coverage_report(
    ledger: list[RankedPain], portfolio: CandidatePortfolio, top: int = COVERAGE_TOP
) -> dict[str, object]:
    """Which ranked pains each candidate removes, persisted with the plan."""
    by_pain: dict[str, list[str]] = {pain.id: [] for pain in ledger}
    for candidate in portfolio.candidates:
        for pid in candidate.addresses_pains:
            by_pain.setdefault(pid, []).append(candidate.title)
    return {
        "top": top,
        "material": [pain.id for pain in material_pains(ledger, top)],
        "uncovered": [pain.id for pain in uncovered_pains(ledger, portfolio, top)],
        "addressed_by": by_pain,
    }


def ledger_records(ledger: list[RankedPain]) -> list[dict[str, object]]:
    """Persistable ledger rows, including the computed weekly hours."""
    return [pain.model_dump(mode="json") | {"weekly_hours": pain.weekly_hours} for pain in ledger]
