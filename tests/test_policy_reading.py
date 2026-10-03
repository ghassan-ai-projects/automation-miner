"""Typed, quote-verified reading of free-text constraints."""

from __future__ import annotations

from pathlib import Path

import pytest

from automation_miner.graph.runner import run_mine
from automation_miner.schemas import ContextPacket, PolicyClause, PolicyReading
from automation_miner.scoring import parse_constraint_policy, read_policy, verify_reading


def _reading(*clauses: tuple[str, str]) -> PolicyReading:
    return PolicyReading(clauses=[PolicyClause(flag=f, quote=q) for f, q in clauses])  # type: ignore[arg-type]


def test_verification_drops_clauses_whose_quote_is_not_in_the_text() -> None:
    text = "Regulated motor claims; budget is tight."
    reading, warnings = verify_reading(
        _reading(("compliance", "Regulated  motor"), ("low_budget", "no money at all"),
                 ("compliance", "claims")),
        text,
    )
    assert [(c.flag, c.quote) for c in reading.clauses] == [("compliance", "Regulated  motor")]
    assert len(warnings) == 1 and "low_budget" in warnings[0]


def test_reading_decides_prose_and_keyword_disagreement_is_reported() -> None:
    text = "We are a regulated insurer but compliance is handled elsewhere; budget: low"
    policy = parse_constraint_policy(text, reading=_reading(("low_budget", "budget: low")))
    assert policy.low_budget and not policy.compliance
    assert policy.source("low_budget") == "from “budget: low”"
    assert any("regulated" in w and "--constraint compliance=true" in w for w in policy.warnings)


def test_parameters_override_the_reading() -> None:
    policy = parse_constraint_policy(
        "budget: low", {"budget": "high", "compliance": "true"},
        reading=_reading(("low_budget", "budget: low")),
    )
    assert not policy.low_budget and policy.compliance
    assert policy.source("compliance") == "parameter compliance=true"
    assert "(parameter compliance=true)" in policy.describe()[0]


def test_agent_limit_comes_from_the_reading() -> None:
    reading = PolicyReading(clauses=[PolicyClause(flag="agent_limit", quote="small team", limit=2)])
    assert parse_constraint_policy("a small team", reading=reading).agent_limit == 2


def test_without_a_reading_keywords_still_apply_and_name_their_phrase() -> None:
    policy = parse_constraint_policy("Regulated industry")
    assert policy.compliance and policy.source("compliance") == "keyword “regulated”"


class _Failing:
    def call_json(self, *args: object, **kwargs: object) -> object:
        raise RuntimeError("provider down")


def test_reader_failure_falls_back_to_keywords_with_a_warning() -> None:
    reading, warnings = read_policy(_Failing(), "budget: low")  # type: ignore[arg-type]
    assert reading is None and "keyword fallback" in warnings[0]
    assert read_policy(_Failing(), "  ") == (None, [])  # type: ignore[arg-type]


def test_run_records_the_reading_and_reports_its_source(tmp_path: Path) -> None:
    result = run_mine(
        workspace_path=tmp_path, idea="Claims intake at a regional insurer",
        constraints="Regulated industry. No budget concerns.", dry_run=True,
    )
    run_dir = Path(str(result["summary_path"])).parent
    context = ContextPacket.model_validate_json((run_dir / "trace" / "context.json").read_text())
    assert context.policy_reading is not None
    assert [c.flag for c in context.policy_reading.clauses] == ["compliance"]
    report = (run_dir / "report.md").read_text()
    assert "compliance: risk capped at Medium" in report and "“regulated”" in report
    assert "budget low/zero" not in report


@pytest.mark.parametrize("text", ["", "   "])
def test_empty_constraints_skip_the_reader(text: str) -> None:
    assert read_policy(_Failing(), text) == (None, [])  # type: ignore[arg-type]
