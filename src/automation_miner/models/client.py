"""Role-routed model client with validated JSON output.

Providers: openrouter, gemini (OpenAI-compatible endpoint), openai_compatible
(custom base_url), and mock. The httpx client is constructor-injected so tests
can swap transports without touching the network. Retries, budget admission,
and per-attempt telemetry live in ``transport``; response parsing in
``parsing``; usage accounting in ``usage``.

The client is thread-safe: stages that fan out over opportunities share one
instance, and usage accumulation is mutex-guarded.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Callable, Iterator, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from automation_miner.context import estimate_tokens
from automation_miner.models import mock
from automation_miner.models.config import MinerConfig, RoleRoute
from automation_miner.models.parsing import extract_json, schema_instruction
from automation_miner.models.transport import RETRYABLE_STATUS, ChatTransport
from automation_miner.models.usage import UsageTracker

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")

if TYPE_CHECKING:
    from automation_miner.execution import RunExecutionContext

__all__ = ["RETRYABLE_STATUS", "MinerModel", "RunScopedModel", "UsageTracker"]

MAX_JSON_ATTEMPTS = 3

_ACTIVE_EXECUTION: ContextVar["RunExecutionContext | None"] = ContextVar(
    "automation_miner_execution", default=None
)
_ACTIVE_USAGE: ContextVar["UsageTracker | None"] = ContextVar(
    "automation_miner_usage", default=None
)


@contextmanager
def _run_scope(execution: RunExecutionContext) -> Iterator[None]:
    execution_token = _ACTIVE_EXECUTION.set(execution)
    usage_token = _ACTIVE_USAGE.set(execution.usage)
    try:
        yield
    finally:
        _ACTIVE_USAGE.reset(usage_token)
        _ACTIVE_EXECUTION.reset(execution_token)


class MinerModel:
    """Role-routed chat client.

    Testable: pass ``http_client`` (e.g. ``httpx.Client(transport=MockTransport(...))``)
    to intercept HTTP. ``dry_run=True`` forces the mock provider for every role.
    ``sleep`` is injectable so retry tests do not wait in real time.
    """

    def __init__(
        self,
        config: MinerConfig,
        http_client: httpx.Client | None = None,
        dry_run: bool = False,
        sleep: Any = time.sleep,
    ) -> None:
        self.config = config
        self.dry_run = dry_run
        self.usage = UsageTracker()
        self._http = http_client or httpx.Client(timeout=180.0)
        self._sleep = sleep

    def routing_table(self) -> dict[str, str]:
        return self.config.routing_table(dry_run=self.dry_run)

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._http.close()

    def _begin(
        self, role: str, usage: UsageTracker | None, execution: RunExecutionContext | None
    ) -> tuple[RoleRoute, UsageTracker, RunExecutionContext | None]:
        """Resolve the route and the run-scoped tracker; count one logical call."""
        execution = execution or _ACTIVE_EXECUTION.get()
        route = self.config.resolve(role, dry_run=self.dry_run)
        scoped = execution.usage if execution is not None else _ACTIVE_USAGE.get()
        tracker = usage or scoped or self.usage
        if execution is not None:
            execution.begin_logical_call()
        tracker.record(role, logical_calls=1, calls=0)
        return route, tracker, execution

    def _mock(
        self, role: str, route: RoleRoute, prompt_tokens: int, produce: Callable[[], R],
        measure: Callable[[R], str], tracker: UsageTracker, execution: RunExecutionContext | None,
    ) -> R:
        """One mock attempt with the same admission and accounting as a real one."""
        admission = execution.admit_attempt(prompt_tokens, route.max_tokens) if execution else None
        started = time.monotonic()
        try:
            result = produce()
        except Exception:
            if execution is not None and admission is not None:
                execution.abandon_attempt(admission)
            tracker.record(role, attempted_tokens=prompt_tokens, attempts=1, failures=1, calls=0)
            raise
        completion = estimate_tokens(measure(result))
        tracker.record(
            role, prompt_tokens=prompt_tokens, completion_tokens=completion,
            seconds=time.monotonic() - started, attempts=1,
        )
        if execution is not None:
            execution.record_tokens(prompt_tokens, completion, admission)
            execution.remaining_seconds()
        return result

    def chat(
        self, role: str, system: str, prompt: str, *, usage: UsageTracker | None = None,
        execution: RunExecutionContext | None = None,
    ) -> str:
        """Plain-text completion for one role (used for KB digests)."""
        route, tracker, execution = self._begin(role, usage, execution)
        if route.provider != "mock":
            return self._chat_http(role, route, system, prompt, usage=tracker, execution=execution)
        tokens = estimate_tokens(system) + estimate_tokens(prompt)
        return self._mock(
            role, route, tokens, lambda: mock.digest(prompt), lambda text: text, tracker, execution
        )

    def _json_attempt(
        self, role: str, route: RoleRoute, system: str, prompt: str, full_prompt: str,
        schema_name: str, tracker: UsageTracker, execution: RunExecutionContext | None,
    ) -> dict[str, Any]:
        """One raw JSON object from the provider; ValueError when unparseable."""
        if route.provider == "mock":
            tokens = estimate_tokens(system) + estimate_tokens(full_prompt)
            return self._mock(
                role, route, tokens, lambda: mock.call_json(role, schema_name, prompt),
                lambda raw: json.dumps(raw, ensure_ascii=False), tracker, execution,
            )
        text = self._chat_http(role, route, system, full_prompt, usage=tracker, execution=execution)
        return extract_json(text)

    def call_json(
        self, role: str, system: str, prompt: str, schema: type[T], *,
        usage: UsageTracker | None = None, execution: RunExecutionContext | None = None,
    ) -> T:
        """Request JSON, validate with pydantic, retry with the error fed back.

        Up to ``MAX_JSON_ATTEMPTS`` attempts; each failure appends the validation
        or parse error to the prompt so the model can self-correct.
        """
        route, tracker, execution = self._begin(role, usage, execution)
        full_prompt = prompt + schema_instruction(schema)
        feedback = ""
        for attempt in range(1, MAX_JSON_ATTEMPTS + 1):
            try:
                raw = self._json_attempt(
                    role, route, system, prompt, full_prompt + feedback, schema.__name__,
                    tracker, execution,
                )
                return schema.model_validate(raw)
            except (ValueError, ValidationError) as exc:
                if attempt == MAX_JSON_ATTEMPTS:
                    raise RuntimeError(_json_failure(role, schema.__name__, exc)) from exc
                feedback = _json_feedback(exc)
        raise AssertionError("unreachable")

    # -- HTTP ---------------------------------------------------------------

    def _chat_http(
        self,
        role: str,
        route: Any,
        system: str,
        prompt: str,
        *,
        usage: UsageTracker | None = None,
        execution: RunExecutionContext | None = None,
    ) -> str:
        tracker = usage or (execution.usage if execution is not None else self.usage)
        transport = ChatTransport(
            self._http, self.config.retry, self._sleep, role, route, tracker, execution
        )
        return transport.send(system, prompt)


def _json_failure(role: str, schema_name: str, exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return (
            f"Role {role!r} failed to produce valid {schema_name} "
            f"after {MAX_JSON_ATTEMPTS} attempts: {exc}"
        )
    return f"Role {role!r} returned unparseable JSON after {MAX_JSON_ATTEMPTS} attempts: {exc}"


def _json_feedback(exc: Exception) -> str:
    """The error fed back to the model so its next attempt can self-correct."""
    if isinstance(exc, ValidationError):
        return (
            f"\n\nYour previous response failed validation:\n{exc}\n"
            "Fix it and respond with corrected JSON only."
        )
    return (
        f"\n\nYour previous response was not valid JSON:\n{exc}\n"
        "Respond with a single JSON object only."
    )


class RunScopedModel:
    """A model facade whose usage and admission state belong to one run."""

    def __init__(self, base: MinerModel, execution: RunExecutionContext) -> None:
        self._base = base
        self.execution = execution
        self.config = base.config
        self.dry_run = base.dry_run
        self.usage = execution.usage

    def routing_table(self) -> dict[str, str]:
        return self._base.routing_table()

    def chat(self, role: str, system: str, prompt: str) -> str:
        with _run_scope(self.execution):
            return self._base.chat(role, system, prompt)

    def call_json(self, role: str, system: str, prompt: str, schema: type[T]) -> T:
        with _run_scope(self.execution):
            return self._base.call_json(role, system, prompt, schema)

    def close(self) -> None:
        """The base model is owned by the outer run and closes it."""
