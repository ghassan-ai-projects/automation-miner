"""OpenAI-compatible chat transport: retries, budget admission, usage telemetry.

* **Transient failures retry with backoff.** A single 429 used to abort a run
  and discard every already-paid call. Retryable statuses, network errors, and
  HTTP-200 responses with no usable content back off exponentially and honour
  ``Retry-After``.
* **Every attempt is admitted and settled.** Each attempt reserves its worst
  case (prompt + ``max_tokens``) against the run budget before it is sent and
  settles at observed usage afterwards; a failed attempt is charged in full.
* **One stalled request cannot hold the run.** Each request times out after
  ``retry.request_seconds`` (bounded by the run's remaining wall clock) and is
  retried like any other transient failure.
"""

from __future__ import annotations

import os
import random
import time
from typing import TYPE_CHECKING, Any, Callable

import httpx

from automation_miner.context import estimate_tokens
from automation_miner.models.config import RetryPolicy, RoleRoute
from automation_miner.models.parsing import error_detail, reported_cost, reported_token_count
from automation_miner.models.streaming import BadCompletion, read_completion
from automation_miner.models.usage import UsageTracker

if TYPE_CHECKING:
    from automation_miner.execution import AttemptAdmission, RunExecutionContext

# Statuses worth retrying: rate limits, timeouts, and transient upstream faults.
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})


def retry_delay(policy: RetryPolicy, attempt: int, response: httpx.Response | None) -> float:
    """Backoff delay, preferring the provider's own ``Retry-After`` hint."""
    delay = policy.delay_for(attempt)
    if response is not None:
        header = response.headers.get("retry-after", "")
        if header:
            try:
                delay = max(delay, min(policy.max_seconds, float(header)))
            except ValueError:
                pass
    if policy.jitter:
        delay *= 1 + random.uniform(0, policy.jitter)
    return delay


def request_body(route: RoleRoute, system: str, prompt: str) -> dict[str, Any]:
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    body: dict[str, Any] = {
        "model": route.model,
        "messages": messages,
        "temperature": route.temperature,
        "max_tokens": route.max_tokens,
    }
    if route.json_mode:
        body["response_format"] = {"type": "json_object"}
    if route.reasoning_effort == "off":
        body["reasoning"] = {"enabled": False}
    elif route.reasoning_effort:
        body["reasoning"] = {"effort": route.reasoning_effort}
    elif route.reasoning_max_tokens:
        body["reasoning"] = {"max_tokens": route.reasoning_max_tokens}
    if route.routing:
        body["provider"] = dict(route.routing)
    return body


class ChatTransport:
    """Sends one role's chat completion with retries; one instance per call."""

    def __init__(
        self,
        http: httpx.Client,
        policy: RetryPolicy,
        sleep: Callable[[float], Any],
        role: str,
        route: RoleRoute,
        tracker: UsageTracker,
        execution: RunExecutionContext | None,
    ) -> None:
        self.http, self.policy, self.sleep = http, policy, sleep
        self.role, self.route, self.tracker, self.execution = role, route, tracker, execution
        self.started = time.monotonic()
        self.admission: AttemptAdmission | None = None

    def send(self, system: str, prompt: str) -> str:
        api_key = os.environ.get(self.route.api_key_env, "")
        if not api_key:
            raise RuntimeError(
                f"{self.route.api_key_env} is not set (required for provider "
                f"{self.route.provider!r}). Set it or use --dry-run."
            )
        body = request_body(self.route, system, prompt)
        estimate = estimate_tokens(system) + estimate_tokens(prompt)
        self.attempted = estimate + self.route.max_tokens
        self.last_error: Exception | None = None
        for attempt in range(1, self.policy.attempts + 1):
            content = self._attempt(body, api_key, estimate, attempt)
            if content is not None:
                return content
        raise RuntimeError(
            f"Chat completion failed for provider {self.route.provider!r}: {self.last_error}"
        )

    def _admit(self, estimate: int) -> float:
        """Reserve the attempt against the run budget; return its timeout."""
        if self.execution is None:
            return self.policy.request_seconds
        self.admission = self.execution.admit_attempt(estimate, self.route.max_tokens)
        return min(self.policy.request_seconds, self.execution.remaining_seconds())

    def _attempt(
        self, body: dict[str, Any], api_key: str, estimate: int, attempt: int
    ) -> str | None:
        """One admitted attempt: the content, or None after scheduling a retry."""
        final = attempt == self.policy.attempts
        self.admission = None
        try:
            content, usage = self._exchange(body, api_key, self._admit(estimate))
        except httpx.HTTPStatusError as exc:
            self._on_status_error(exc, self.admission, attempt, final)
            return None
        except httpx.HTTPError as exc:
            self._on_transient(exc, self.admission, attempt, final, charge_in_full=False)
            return None
        except BadCompletion as exc:
            # HTTP 200 without a usable completion (empty content from a
            # reasoning model that spent its budget thinking, a malformed
            # envelope, a mid-stream error): retry; the attempt is charged.
            self._on_transient(exc, self.admission, attempt, final, charge_in_full=True)
            return None
        except Exception:
            self._on_unexpected()
            raise
        return self._settle(content, usage, estimate, self.admission)

    def _on_unexpected(self) -> None:
        if self.admission is None:
            return
        self._abandon(self.admission)
        self.tracker.record(
            self.role, attempted_tokens=self.attempted, attempts=1, failures=1, calls=0
        )
        self._check_deadline()

    def _on_status_error(
        self, exc: httpx.HTTPStatusError, admission: AttemptAdmission | None, attempt: int,
        final: bool,
    ) -> None:
        self._abandon(admission)
        self.last_error = exc
        status = exc.response.status_code
        if status not in RETRYABLE_STATUS or final:
            self._fail()
            raise RuntimeError(
                f"Chat completion failed for provider {self.route.provider!r} "
                f"(HTTP {status}): {error_detail(exc.response)}"
            ) from exc
        self._retry(retry_delay(self.policy, attempt, exc.response))

    def _on_transient(
        self, exc: Exception, admission: AttemptAdmission | None, attempt: int, final: bool,
        charge_in_full: bool,
    ) -> None:
        self.last_error = exc
        if charge_in_full and self.execution is not None and admission is not None:
            self.execution.record_tokens(admission.prompt_tokens, self.route.max_tokens, admission)
        elif not charge_in_full:
            self._abandon(admission)
        if final:
            self._fail()
            raise RuntimeError(self._exhausted_message(exc, charge_in_full)) from exc
        self._retry(retry_delay(self.policy, attempt, None))

    def _exhausted_message(self, exc: Exception, completion_failure: bool) -> str:
        if completion_failure:
            return (
                f"Completion failed for role {self.role!r} using "
                f"{self.route.provider!r}/{self.route.model!r} after "
                f"{self.policy.attempts} attempts: {exc}"
            )
        return (
            f"Chat completion failed for provider {self.route.provider!r} "
            f"after {self.policy.attempts} attempts: {exc}"
        )

    def _exchange(
        self, body: dict[str, Any], api_key: str, timeout: float
    ) -> tuple[str, dict[str, Any]]:
        """One HTTP exchange: streamed when the provider supports it."""
        url = f"{self.route.base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        provider = self.route.provider
        if not self.route.stream:
            response = self.http.post(url, headers=headers, json=body, timeout=timeout)
            response.raise_for_status()
            return read_completion(response, provider, self.policy.stall_seconds, timeout)
        # The read timeout is a backstop for a connection that sends nothing at
        # all; keep-alive-only stalls are caught by read_completion itself.
        limits = httpx.Timeout(timeout, read=min(timeout, self.policy.stall_seconds + 30))
        with self.http.stream(
            "POST", url, headers=headers, json={**body, "stream": True}, timeout=limits
        ) as response:
            if response.is_error:
                response.read()
                response.raise_for_status()
            return read_completion(response, provider, self.policy.stall_seconds, timeout)

    def _settle(
        self, content: str, usage: dict[str, Any], estimate: int,
        admission: AttemptAdmission | None,
    ) -> str:
        prompt_tokens = reported_token_count(usage.get("prompt_tokens"))
        completion_tokens = reported_token_count(usage.get("completion_tokens"))
        observed_prompt = estimate if prompt_tokens is None else prompt_tokens
        observed_completion = (
            estimate_tokens(content) if completion_tokens is None else completion_tokens
        )
        cost = reported_cost(usage)
        self.tracker.record(
            self.role, prompt_tokens=observed_prompt, completion_tokens=observed_completion,
            seconds=time.monotonic() - self.started, attempts=1, cost_usd=cost,
            exact=prompt_tokens is not None and completion_tokens is not None,
        )
        if self.execution is not None:
            self.execution.record_tokens(observed_prompt, observed_completion, admission)
            self.execution.record_cost(cost)
            self.execution.remaining_seconds()
        return content

    def _abandon(self, admission: AttemptAdmission | None) -> None:
        if self.execution is not None and admission is not None:
            self.execution.abandon_attempt(admission)

    def _check_deadline(self) -> None:
        if self.execution is not None:
            self.execution.remaining_seconds()

    def _fail(self) -> None:
        self.tracker.record(
            self.role,
            attempted_tokens=self.attempted,
            seconds=time.monotonic() - self.started,
            retries=0,
            failures=1,
            attempts=1,
            calls=0,
        )
        self._check_deadline()

    def _retry(self, delay: float) -> None:
        self.tracker.record(
            self.role, attempted_tokens=self.attempted, retries=1, attempts=1, calls=0
        )
        if self.execution is not None:
            delay = min(delay, self.execution.remaining_seconds())
        self.sleep(delay)
