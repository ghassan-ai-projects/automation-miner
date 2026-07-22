"""Critique-refine loop: terminates on pass, respects max_iterations."""

from __future__ import annotations

from typing import Any

from automation_miner.graph.loop import run_critique_loop
from automation_miner.models import mock
from automation_miner.schemas import CRITIQUE_THRESHOLD, OpportunityDraft


class FakeModel:
    """Scripted critic: returns the queued critique scores, then passes."""

    def __init__(self, critique_scores: list[float]) -> None:
        self.critique_scores = critique_scores
        self.critic_calls = 0
        self.refiner_calls = 0

    def call_json(self, role: str, system: str, prompt: str, schema: type) -> Any:
        if role == "critic":
            self.critic_calls += 1
            idx = min(self.critic_calls - 1, len(self.critique_scores) - 1)
            value = self.critique_scores[idx]
            return schema(
                groundedness=value,
                specificity=value,
                quantified_impact=value,
                feasibility=value,
                hitl_clarity=value,
                differentiation=value,
                feedback=f"round {self.critic_calls}",
            )
        if role == "refiner":
            self.refiner_calls += 1
            return schema.model_validate(mock.call_json(role, schema.__name__, prompt))
        raise AssertionError(f"unexpected role {role}")


def _draft() -> OpportunityDraft:
    return OpportunityDraft.model_validate(
        mock.call_json("drafter", "DraftBatch", "")["drafts"][0]
    )


def test_passes_first_try() -> None:
    model = FakeModel([8.0])
    final, history = run_critique_loop(model, _draft(), [], max_iterations=3)
    assert model.critic_calls == 1
    assert model.refiner_calls == 0
    assert len(history) == 1
    assert history[0]["passed"]
    assert history[0]["overall"] >= CRITIQUE_THRESHOLD
    assert final.title


def test_fail_then_pass() -> None:
    model = FakeModel([5.0, 8.0])
    final, history = run_critique_loop(model, _draft(), [], max_iterations=3)
    assert model.critic_calls == 2
    assert model.refiner_calls == 1
    assert [h["passed"] for h in history] == [False, True]
    assert final.layer == _draft().layer


def test_respects_max_iterations_when_never_passing() -> None:
    model = FakeModel([3.0])
    final, history = run_critique_loop(model, _draft(), [], max_iterations=3)
    assert model.critic_calls == 3  # exactly max_iterations critique rounds
    assert model.refiner_calls == 2
    assert len(history) == 3
    assert not any(h["passed"] for h in history)
    assert final is not None
