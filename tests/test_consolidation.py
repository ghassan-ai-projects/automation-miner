"""Pain consolidation: merge paraphrases, size cross-cutting costs, never lose a pain."""

from __future__ import annotations

from typing import Any

from automation_miner.consolidation import consolidate, consolidated_pool, pains_listing
from automation_miner.discovery import rank_pains
from automation_miner.execution import BudgetExceeded
from automation_miner.schemas import ConsolidatedPain, Layer, PainConsolidation, PainPoint

POOL = [
    (Layer.DOCUMENT, PainPoint(pain="Re-typing paper forms", volume_per_week=148,
                               minutes_per_item=9, observed=True, evidence_refs=["S4"])),
    (Layer.DOCUMENT, PainPoint(pain="Policy lookup without policy number", volume_per_week=141,
                               minutes_per_item=6, observed=True)),
    (Layer.COMMUNICATION, PainPoint(pain="Policy identification needs a call to the customer",
                                    volume_per_week=126, observed=True)),
    (Layer.MONITORING, PainPoint(pain="Duplicate claims merged downstream", volume_per_week=121,
                                 other_cost="rework", observed=True)),
]


def _pain(**fields: Any) -> ConsolidatedPain:
    return ConsolidatedPain(observed=True, layer=Layer.DOCUMENT, **fields)


def test_listing_numbers_every_pain_with_its_size() -> None:
    listing = pains_listing(POOL)
    assert listing.splitlines()[0].startswith("1. [document] Re-typing paper forms")
    assert "148 per week | 9 min each" in listing and "? min each" in listing


def test_merges_add_missing_costs_fix_volumes_and_keep_the_rest() -> None:
    consolidation = PainConsolidation(pains=[
        _pain(pain="Re-keying email FNOLs into ClaimsDesk", volume_per_week=None,
              volume_formula="1850 * 0.31", minutes_per_item=9, sources=[]),
        _pain(pain="Policy lookup without number, incl. customer calls", volume_per_week=141,
              volume_formula="640 * 0.22", minutes_per_item=6, sources=[2, 3, 99]),
    ])
    pool, notes = consolidated_pool(consolidation, POOL)
    names = [pain.pain for _, pain in pool]
    assert names[0].startswith("Re-keying email") and pool[0][1].volume_per_week == 573.5
    assert "Re-typing paper forms" in names and "Duplicate claims merged downstream" in names
    assert not any(name.startswith("Policy identification") for name in names)
    assert any("kept as listed" in note for note in notes)
    ledger = rank_pains(pool)
    assert ledger[0].pain.startswith("Re-keying email") and ledger[0].weekly_hours == 86.0


def test_uncomputable_formula_keeps_the_stated_volume() -> None:
    pool, notes = consolidated_pool(
        PainConsolidation(pains=[_pain(pain="x", volume_per_week=10, volume_formula="a lot")]), []
    )
    assert pool[0][1].volume_per_week == 10 and "not computable" in notes[0]


class _Model:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def call_json(self, *args: object, **kwargs: object) -> object:
        raise self.error


def test_failed_call_falls_back_and_budget_exhaustion_propagates() -> None:
    result, notes = consolidate(_Model(RuntimeError("down")), POOL, "evidence")  # type: ignore[arg-type]
    assert result is None and "ranked pains as listed" in notes[0]
    try:
        consolidate(_Model(BudgetExceeded("tokens", 2, 1)), POOL, "evidence")  # type: ignore[arg-type]
    except BudgetExceeded:
        pass
    else:
        raise AssertionError("budget exhaustion must stop the run")
    assert consolidated_pool(PainConsolidation(), POOL) == (POOL, [])
