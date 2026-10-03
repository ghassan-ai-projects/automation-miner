"""Derived figures are checked in code, and the critic is told what code verified."""

from __future__ import annotations

import pytest
from test_loop import FakeModel, _draft

from automation_miner.derivations import (
    arithmetic_issues,
    check_derivations,
    evaluate,
    figure_value,
    verified_notes,
)
from automation_miner.graph.loop import run_critique_loop
from automation_miner.schemas import Derivation, OpportunityDraft


def _with(*pairs: tuple[str, str]) -> OpportunityDraft:
    derivations = [Derivation(figure=f, formula=x, evidence_refs=["S7"]) for f, x in pairs]
    return _draft().model_copy(update={"derivations": derivations})


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ("640 / 0.62 * 0.38", 392.26),
        ("1,850 × 31% × 9 / 60", 86.03),
        ("(148 + 111) * 9 / 60", 38.85),
        ("-5 + 2", -3.0),
    ],
)
def test_evaluate_plain_arithmetic(formula: str, value: float) -> None:
    assert evaluate(formula) == pytest.approx(value, abs=0.01)


@pytest.mark.parametrize("formula", ["2 ** 64", "__import__('os')", "a * 3", "1 / 0", ""])
def test_evaluate_rejects_anything_but_arithmetic(formula: str) -> None:
    assert evaluate(formula) is None


def test_figure_value_reads_the_first_number() -> None:
    assert figure_value("~1,392.5 claims/week") == 1392.5
    assert figure_value("several") is None


def test_correct_derivation_is_verified_and_a_wrong_one_is_reported() -> None:
    checks = check_derivations(_with(("~392/week", "640 / 0.62 * 0.38"), ("~243/week", "640 / 0.62 * 0.38")))
    assert [c.ok for c in checks] == [True, False]
    assert "~392/week = 640 / 0.62 * 0.38" in verified_notes(checks) and "[S7]" in verified_notes(checks)
    assert "243" not in verified_notes(checks)
    issues = arithmetic_issues(checks)
    assert len(issues) == 1 and "computes to 392.3" in issues[0]


def test_critic_sees_verified_arithmetic_and_wrong_sums_block_the_round() -> None:
    model = FakeModel([9.0, 9.0])
    draft = _with(("~392/week", "640 / 0.62 * 0.38"), ("~5,000 hours", "2 + 2"))
    _, history = run_critique_loop(model, draft, [], max_iterations=1)
    critic_prompt = model.prompts[0][1]
    assert "Arithmetic checked by code" in critic_prompt and "~392/week" in critic_prompt
    assert not history[0]["passed"]
    assert any("arithmetic check failed" in i for i in history[0]["critique"]["writing_issues"])
    assert [d["ok"] for d in history[0]["derivations"]] == [True, False]
