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
        self.prompts: list[tuple[str, str]] = []

    def call_json(self, role: str, system: str, prompt: str, schema: type) -> Any:
        self.prompts.append((role, prompt))
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
                grounding_violations=[],
                constraint_violations=[],
                feedback=f"round {self.critic_calls}",
            )
        if role == "refiner":
            self.refiner_calls += 1
            return schema.model_validate(mock.call_json(role, schema.__name__, prompt))
        raise AssertionError(f"unexpected role {role}")


def _draft() -> OpportunityDraft:
    return OpportunityDraft.model_validate(
        mock.call_json("drafter", "OpportunityDraft", "")
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


def test_critic_and_refiner_receive_evidence_and_constraints() -> None:
    model = FakeModel([5.0, 8.0])
    run_critique_loop(
        model,
        _draft(),
        [],
        max_iterations=2,
        evidence="source fact: 100 cases/day",
        constraints="no custom dev",
    )
    critic_prompts = [prompt for role, prompt in model.prompts if role == "critic"]
    refiner_prompts = [prompt for role, prompt in model.prompts if role == "refiner"]
    assert all("100 cases/day" in prompt for prompt in critic_prompts)
    assert all("no custom dev" in prompt for prompt in critic_prompts)
    assert "100 cases/day" in refiner_prompts[0]
    assert "no custom dev" in refiner_prompts[0]


def test_refinement_regression_keeps_the_best_version() -> None:
    model = FakeModel([7.4, 5.0])
    original = _draft()
    final, history = run_critique_loop(model, original, [], max_iterations=2)

    assert final == original
    assert history[0]["selected"] is True
    assert history[1]["selected"] is False


def test_gate_clean_version_beats_higher_invalid_score() -> None:
    class GateModel(FakeModel):
        def call_json(self, role: str, system: str, prompt: str, schema: type) -> Any:
            if role != "critic":
                return super().call_json(role, system, prompt, schema)
            self.critic_calls += 1
            invalid = self.critic_calls == 1
            value = 8.0 if invalid else 7.4
            return schema(
                groundedness=value,
                specificity=value,
                quantified_impact=value,
                feasibility=value,
                hitl_clarity=value,
                differentiation=value,
                grounding_violations=["unsupported baseline"] if invalid else [],
                constraint_violations=[],
                feedback="remove unsupported baseline" if invalid else "clean",
            )

    _, history = run_critique_loop(GateModel([8.0, 7.4]), _draft(), [], max_iterations=2)
    assert history[0]["overall"] > history[1]["overall"]
    assert history[1]["selected"] is True
