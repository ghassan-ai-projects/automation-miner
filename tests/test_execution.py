"""Per-run admission, deadline, and usage ownership tests."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from automation_miner.execution import BudgetExceeded, RunExecutionContext
from automation_miner.schemas import RunBudget


def test_attempt_admission_is_atomic_across_stage_workers() -> None:
    execution = RunExecutionContext(
        "2026-08-28_parallel",
        RunBudget(max_attempts=8, max_tokens=1_000, max_seconds=30),
    )

    def admit(_: int) -> bool:
        try:
            execution.admit_attempt(1)
        except BudgetExceeded:
            return False
        return True

    with ThreadPoolExecutor(max_workers=16) as pool:
        admitted = list(pool.map(admit, range(64)))

    assert sum(admitted) == 8
    assert execution.snapshot().attempts == 8


def test_token_admission_preserves_observed_overage() -> None:
    execution = RunExecutionContext(
        "2026-08-28_tokens",
        RunBudget(max_attempts=5, max_tokens=10, max_seconds=30),
    )
    admission = execution.admit_attempt(8)

    with pytest.raises(BudgetExceeded, match="max_tokens"):
        execution.record_tokens(8, 3, admission)

    assert execution.snapshot().tokens == 11
    with pytest.raises(BudgetExceeded, match="max_tokens"):
        execution.admit_attempt(1)


def test_token_reservation_is_atomic_across_parallel_attempts() -> None:
    execution = RunExecutionContext(
        "2026-08-28_token-reservation",
        RunBudget(max_attempts=5, max_tokens=10, max_seconds=30),
    )

    def admit(_: int) -> bool:
        try:
            execution.admit_attempt(2, 8)
        except BudgetExceeded:
            return False
        return True

    with ThreadPoolExecutor(max_workers=8) as pool:
        admitted = list(pool.map(admit, range(8)))

    assert sum(admitted) == 1


def test_deadline_is_enforced_before_new_work() -> None:
    execution = RunExecutionContext(
        "2026-08-28_deadline",
        RunBudget(max_attempts=5, max_tokens=100, max_seconds=0.001),
    )
    time.sleep(0.01)

    with pytest.raises(BudgetExceeded, match="max_seconds"):
        execution.begin_logical_call()


def test_deadline_is_checked_after_mock_work(monkeypatch: pytest.MonkeyPatch) -> None:
    from automation_miner.models import mock
    from automation_miner.models.client import MinerModel
    from automation_miner.models.config import load_config

    def slow_digest(_: str) -> str:
        time.sleep(0.01)
        return "digest"

    monkeypatch.setattr(mock, "digest", slow_digest)
    model = MinerModel(load_config(None), dry_run=True)
    execution = RunExecutionContext(
        "2026-08-28_slow-mock",
        RunBudget(max_attempts=2, max_tokens=10_000, max_seconds=0.001),
    )
    try:
        with pytest.raises(BudgetExceeded, match="max_seconds"):
            model.chat("mapper", "", "input", execution=execution)
    finally:
        model.close()
