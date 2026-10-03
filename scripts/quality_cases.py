"""Quality-suite cases and the bar they are graded against.

Keep ``BAR`` in sync with docs/quality/00-QUALITY-BAR.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Case:
    name: str
    kind: str
    value: str
    constraints: str = ""
    min_published: int = 3
    min_publication_rate: float = 0.0
    expected_mode: str = ""
    all_hypotheses: bool = False


CASES: dict[str, Case] = {
    "claims": Case(
        name="claims",
        kind="kb",
        value=str(ROOT / "examples" / "claims-intake"),
        constraints="compliance:heavy, team:5",
        min_published=4,
        min_publication_rate=0.6,
        expected_mode="operational",
    ),
    "strategy": Case(
        name="strategy",
        kind="file",
        value=str(ROOT / "examples" / "hospital-strategy-memo.md"),
        min_published=3,
        expected_mode="strategy",
    ),
    "oneliner": Case(
        name="oneliner",
        kind="idea",
        value="Independent veterinary clinics in the Netherlands",
        min_published=3,
        all_hypotheses=True,
    ),
    # The input of the first real run (DHL), kept as a regression case.
    "dhl": Case(
        name="dhl", kind="idea",
        value=(ROOT / "examples" / "dhl-germany-domain.md").read_text(encoding="utf-8"),
        min_published=4, min_publication_rate=0.6,
    ),
    # ~89k tokens of synthetic field-service records: exercises digestion and
    # per-stage evidence selection. Generated into the output directory.
    "large": Case(
        name="large", kind="kb", value="@large-kb", min_published=4,
        expected_mode="operational",
    ),
}

# The bar. Keep in sync with docs/quality/00-QUALITY-BAR.md.
BAR: dict[str, float] = {
    "max_minutes": 15.0,
    "max_lint_errors": 0,
    "min_judge_overall_mean": 4.0,
    "min_judge_dimension_mean": 3.5,
    "min_brief_overall": 3,
    "max_fabricated_facts_per_brief": 0.5,
    "min_portfolio_diversity": 4,
    "min_portfolio_coverage": 3,
}
