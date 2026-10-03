"""Run evaluation: the lint must catch every defect the first real brief had."""

from __future__ import annotations

from pathlib import Path

from factories import make_opportunity

from automation_miner.artifacts.briefs import render_brief
from automation_miner.evaluation.lint import lint_brief

FIXTURE_DEFECTS = """---
am-id: "AM-005"
domain: "DHL in Germany — operational domain description:"
---

# AM-005: ComplianceGuard Agent

## Problem Statement

The current compliance monitoring process is unknown.

### Inputs
- GPS data – inferred from S2: 'GPS tracking on delivery vehicles'; API not explicitly stated

### Steps
1. 1. Ingest real-time telematics data.
2. 2. Apply rule engine.

### Outputs
- (none identified)

## Evidence

- `S2`

Validation criteria:
- Actual time saved vs. the Assumed reduction in ArbZG violations projected above
"""


def test_lint_catches_every_defect_of_the_first_real_brief() -> None:
    lint = lint_brief(FIXTURE_DEFECTS, "AM-005.md")
    codes = {finding.code for finding in lint.findings}
    assert {
        "hedge:inferred-from-source",
        "hedge:not-explicitly-stated",
        "double-numbering",
        "empty-section",
        "missing-section",
        "domain-trailing-punctuation",
        "garbled-validation-criterion",
    } <= codes
    assert lint.hedge_count == 2
    assert lint.errors >= 7


def test_rendered_clean_brief_passes_lint() -> None:
    opportunity = make_opportunity("AM-001", evidence_refs=["S1", "S2"])
    text = render_brief(opportunity, "run", evidence_labels={"S1": "sop.md # Intake"})
    lint = lint_brief(text, "AM-001.md")
    assert lint.errors == 0, lint.findings


def test_evidence_section_ids_are_not_counted_as_inline_citations(tmp_path: Path) -> None:
    text = render_brief(make_opportunity("AM-002", evidence_refs=["S1"]), "run")
    assert "`S1`" in text
    assert lint_brief(text).hedge_count == 0
