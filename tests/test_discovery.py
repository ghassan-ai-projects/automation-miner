"""Pain ledger: sized pains are ranked in code and the plan must cover them."""

from __future__ import annotations

from automation_miner.discovery import (
    build_pain_ledger,
    coverage_report,
    render_ledger,
    uncovered_pains,
)
from automation_miner.schemas import (
    CandidatePortfolio,
    Layer,
    LayerAnalysis,
    Level,
    OpportunityCandidate,
    PainPoint,
)


def _pain(text: str, volume: float | None = None, minutes: float | None = None,
          other: str = "", observed: bool = True) -> PainPoint:
    return PainPoint(pain=text, volume_per_week=volume, minutes_per_item=minutes,
                     other_cost=other, observed=observed, evidence_refs=["S1"])


def _analysis(layer: Layer, *pains: PainPoint) -> LayerAnalysis:
    return LayerAnalysis(layer=layer, findings=[], pain_points=list(pains), pain_level=Level.HIGH)


def _candidate(title: str, *pains: str) -> OpportunityCandidate:
    return OpportunityCandidate(layer=Layer.DOCUMENT, title=title, value_thesis="v",
                                why_now="w", differentiation="d", addresses_pains=list(pains))


ANALYSES = [
    _analysis(Layer.KNOWLEDGE, _pain("Onboarding takes two weeks", other="temps slow")),
    _analysis(
        Layer.DOCUMENT,
        _pain("Re-keying email and paper FNOLs", 723, 9),
        _pain("Vague complaint"),
        _pain("Policy lookup without a number", 126, 6),
    ),
    _analysis(Layer.COMMUNICATION, _pain("Re-keying email and paper FNOLs!", 723, 9),
              _pain("Estimated follow-up sorting", 300, 4, observed=False)),
]


def test_ledger_ranks_observed_hours_first_then_costs_then_vague() -> None:
    ledger = build_pain_ledger(ANALYSES)
    assert [p.pain for p in ledger] == [
        "Re-keying email and paper FNOLs",
        "Policy lookup without a number",
        "Estimated follow-up sorting",
        "Onboarding takes two weeks",
        "Vague complaint",
    ]
    assert [p.id for p in ledger] == ["P1", "P2", "P3", "P4", "P5"]
    assert ledger[0].weekly_hours == 108.5


def test_ledger_rendering_shows_size_basis_and_refs() -> None:
    line = render_ledger(build_pain_ledger(ANALYSES))[: 200]
    assert line.startswith("P1 (document, observed): Re-keying email and paper FNOLs — ~108.5 h/week")


def test_coverage_requires_material_top_pains_within_portfolio_size() -> None:
    ledger = build_pain_ledger(ANALYSES)
    plan = CandidatePortfolio(candidates=[_candidate("A", "P1"), _candidate("B", "P3")])
    # Two candidates: only the top two material pains are owed; P2 is missing.
    assert [p.id for p in uncovered_pains(ledger, plan)] == ["P2"]
    report = coverage_report(ledger, plan)
    assert report["uncovered"] == ["P2"] and report["addressed_by"]["P1"] == ["A"]


def test_vague_pains_are_never_owed() -> None:
    ledger = build_pain_ledger([_analysis(Layer.DOCUMENT, _pain("Vague complaint"))])
    plan = CandidatePortfolio(candidates=[_candidate("A")])
    assert uncovered_pains(ledger, plan) == []


def test_near_duplicate_pains_merge_keeping_the_better_sized_one() -> None:
    ledger = build_pain_ledger(
        [
            _analysis(Layer.DOCUMENT, _pain("Policy lookup without policy number takes 6 minutes",
                                            126, 6)),
            _analysis(Layer.COMMUNICATION, _pain("Policy lookup without a policy number",
                                                 other="customer calls")),
            _analysis(Layer.DECISION, _pain("Complexity misclassification of injury claims",
                                            other="2.5 days rework")),
        ]
    )
    assert [p.pain for p in ledger] == [
        "Policy lookup without policy number takes 6 minutes",
        "Complexity misclassification of injury claims",
    ]


def test_same_domain_matches_differently_named_runs_only() -> None:
    from automation_miner.discovery import same_domain

    assert same_domain("claims-intake", "motor-claims-intake-sop")
    assert same_domain("hospital-strategy-memo", "hospital-strategy")
    assert not same_domain("claims-intake", "independent-veterinary-clinics")
    assert not same_domain("claims-intake", "logistics")
