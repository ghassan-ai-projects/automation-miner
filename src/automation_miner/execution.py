"""Per-invocation budget admission, deadline, and ownership state."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from automation_miner.models.client import UsageTracker
from automation_miner.schemas import RunBudget


class BudgetExceeded(RuntimeError):
    """A run could not admit another attempt within its configured budget."""

    def __init__(self, limit: str, observed: int | float, maximum: int | float) -> None:
        self.limit = limit
        self.observed = observed
        self.maximum = maximum
        super().__init__(f"run budget exhausted: {limit} {observed} exceeds maximum {maximum}")


@dataclass(frozen=True)
class BudgetSnapshot:
    """Observable admission state persisted with a failed or completed run."""

    attempts: int
    logical_calls: int
    tokens: int
    elapsed_seconds: float
    stage: str
    stage_seconds: dict[str, float]


@dataclass(frozen=True)
class AttemptAdmission:
    """Reservation returned when one provider attempt is admitted."""

    prompt_tokens: int
    reserved_tokens: int


class RunExecutionContext:
    """Thread-safe limits and usage ownership for exactly one pipeline run."""

    def __init__(self, run_id: str, budget: RunBudget) -> None:
        self.run_id = run_id
        self.budget = budget
        self.usage = UsageTracker()
        self._lock = threading.Lock()
        self._started = time.monotonic()
        self._attempts = 0
        self._logical_calls = 0
        self._tokens = 0
        self._reserved_tokens = 0
        self._stage = "setup"
        self._stage_seconds: dict[str, float] = {}

    @property
    def stage(self) -> str:
        with self._lock:
            return self._stage

    def set_stage(self, stage: str) -> None:
        with self._lock:
            self._stage = stage

    def record_stage(self, stage: str, seconds: float) -> None:
        """Record the slowest worker duration for a stage."""
        with self._lock:
            self._stage_seconds[stage] = max(
                self._stage_seconds.get(stage, 0.0), round(seconds, 2)
            )

    def begin_logical_call(self) -> None:
        with self._lock:
            self._check_deadline_locked()
            self._logical_calls += 1

    def admit_attempt(
        self, prompt_tokens: int = 0, completion_tokens: int = 0
    ) -> AttemptAdmission:
        """Atomically reserve one provider/mock attempt before execution."""
        with self._lock:
            self._check_deadline_locked()
            if self._attempts >= self.budget.max_attempts:
                raise BudgetExceeded("max_attempts", self._attempts + 1, self.budget.max_attempts)
            prompt_tokens = max(0, prompt_tokens)
            completion_tokens = max(0, completion_tokens)
            reservation = prompt_tokens + completion_tokens
            projected = self._tokens + self._reserved_tokens + reservation
            if projected > self.budget.max_tokens:
                raise BudgetExceeded(
                    "max_tokens", projected, self.budget.max_tokens
                )
            self._attempts += 1
            self._reserved_tokens += reservation
            return AttemptAdmission(prompt_tokens, reservation)

    def record_tokens(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        admission: AttemptAdmission | None = None,
    ) -> None:
        """Settle an admitted attempt with observed or estimated usage."""
        with self._lock:
            if admission is not None:
                self._reserved_tokens -= admission.reserved_tokens
            self._tokens += max(0, prompt_tokens) + max(0, completion_tokens)
            if self._tokens > self.budget.max_tokens:
                raise BudgetExceeded("max_tokens", self._tokens, self.budget.max_tokens)

    def abandon_attempt(self, admission: AttemptAdmission) -> None:
        """Settle an unknown failed attempt at its full reserved cost."""
        self.record_tokens(0, admission.reserved_tokens, admission)

    def remaining_seconds(self) -> float:
        with self._lock:
            remaining = self.budget.max_seconds - (time.monotonic() - self._started)
            if remaining <= 0:
                raise BudgetExceeded("max_seconds", self.budget.max_seconds, self.budget.max_seconds)
            return remaining

    def snapshot(self) -> BudgetSnapshot:
        with self._lock:
            return BudgetSnapshot(
                attempts=self._attempts,
                logical_calls=self._logical_calls,
                tokens=self._tokens,
                elapsed_seconds=round(time.monotonic() - self._started, 3),
                stage=self._stage,
                stage_seconds=dict(self._stage_seconds),
            )

    def _check_deadline_locked(self) -> None:
        elapsed = time.monotonic() - self._started
        if elapsed >= self.budget.max_seconds:
            raise BudgetExceeded("max_seconds", round(elapsed, 3), self.budget.max_seconds)
