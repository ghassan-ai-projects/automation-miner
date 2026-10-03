"""Consolidate and size the run's pains before code ranks them.

Five layer analysts each list pains from the same evidence, so a real run's
ledger carried "policy lookup without a number" three times while its largest
waste was missing: the SOP states 9 minutes of keying "for email and paper",
and the analysts sized only paper (148 x 9 min = 22 h/week), never email
(640 x 9 min = 96 h/week). Word-overlap merging cannot see paraphrases, and
per-layer analysts cannot see costs that cut across layers.

One consolidation call sees every listed pain together with the evidence. It
merges duplicates, applies each stated per-item time to every volume it
covers, and gives each volume as a formula. Code keeps it honest: formulas are
evaluated (a stated volume that disagrees is replaced by the computed one),
merge references are validated, and any listed pain the call did not account
for is kept as it was, so consolidation can sharpen the ledger but never lose
a pain. If the call fails, the run ranks the analysts' pains as before.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from automation_miner.derivations import TOLERANCE, evaluate
from automation_miner.execution import BudgetExceeded
from automation_miner.prompts import PAIN_CONSOLIDATION_SYSTEM, pain_consolidation_prompt
from automation_miner.schemas import (
    LAYER_ORDER,
    ConsolidatedPain,
    Layer,
    LayerAnalysis,
    PainConsolidation,
    PainPoint,
)

if TYPE_CHECKING:
    from automation_miner.models.client import MinerModel, RunScopedModel

Pool = list[tuple[Layer, PainPoint]]


def raw_pool(analyses: list[LayerAnalysis]) -> Pool:
    ordered = sorted(analyses, key=lambda a: LAYER_ORDER.index(a.layer))
    return [(a.layer, pain) for a in ordered for pain in a.pain_points if pain.pain.strip()]


def _size(value: float | None, unit: str) -> str:
    return f"{value:g} {unit}" if value is not None else f"? {unit}"


def pains_listing(pool: Pool) -> str:
    """The analysts' pains, numbered, in the form the consolidation call reads."""
    return "\n".join(
        f"{i}. [{layer.value}] {p.pain} | who: {p.who or '?'} | "
        f"{_size(p.volume_per_week, 'per week')} | {_size(p.minutes_per_item, 'min each')} | "
        f"{p.other_cost or 'no other cost'} | {'observed' if p.observed else 'estimate'} | "
        f"refs: {', '.join(p.evidence_refs) or 'none'}"
        for i, (layer, p) in enumerate(pool, 1)
    )


def _checked_volume(pain: ConsolidatedPain, notes: list[str]) -> float | None:
    """The volume its formula computes, when the formula and the stated value disagree."""
    if not pain.volume_formula.strip():
        return pain.volume_per_week
    computed = evaluate(pain.volume_formula)
    if computed is None:
        notes.append(f"volume formula not computable for “{pain.pain[:60]}”; kept stated value")
        return pain.volume_per_week
    stated = pain.volume_per_week
    if stated is None or abs(computed - stated) > max(0.5, TOLERANCE * abs(computed)):
        notes.append(f"volume of “{pain.pain[:60]}” set to {computed:,.0f} from its formula")
        return round(computed, 1)
    return stated


def consolidated_pool(consolidation: PainConsolidation, pool: Pool) -> tuple[Pool, list[str]]:
    """Consolidated pains with verified volumes, plus every listed pain left unmerged."""
    notes: list[str] = []
    used: set[int] = set()
    result: Pool = []
    for pain in consolidation.pains:
        used.update(i for i in pain.sources if 1 <= i <= len(pool))
        volume = _checked_volume(pain, notes)
        fields = pain.model_dump(include=set(PainPoint.model_fields))
        result.append((pain.layer, PainPoint.model_validate({**fields, "volume_per_week": volume})))
    kept = [item for i, item in enumerate(pool, 1) if i not in used]
    if kept and consolidation.pains:
        notes.append(f"{len(kept)} listed pain(s) not merged by consolidation were kept as listed")
    return result + kept, notes


def consolidate(
    model: MinerModel | RunScopedModel, pool: Pool, evidence: str
) -> tuple[PainConsolidation | None, list[str]]:
    """One consolidation call; None (rank the analysts' pains as listed) on failure."""
    if not pool:
        return None, []
    prompt = pain_consolidation_prompt(pains_listing(pool), evidence)
    try:
        result = model.call_json(
            "layer_analyst", PAIN_CONSOLIDATION_SYSTEM, prompt, PainConsolidation
        )
    except BudgetExceeded:
        raise
    except Exception as exc:
        return None, [f"pain consolidation failed ({type(exc).__name__}); ranked pains as listed"]
    return result, []


__all__ = ["Pool", "consolidate", "consolidated_pool", "pains_listing", "raw_pool"]
