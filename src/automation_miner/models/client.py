"""Multi-provider chat client with validated JSON output, retries, and telemetry.

Providers: openrouter, gemini (OpenAI-compatible endpoint), openai_compatible
(custom base_url), and mock. The httpx client is constructor-injected so tests
can swap transports without touching the network (film-pipeline pattern).

Three behaviours beyond routing, each replacing a measured failure mode:

* **Transient failures retry with backoff.** Any ``httpx.HTTPError`` used to
  abort the run immediately, so a single 429 discarded up to 25 already-paid
  calls. Retryable statuses now back off exponentially and honour ``Retry-After``.
* **Usage is tracked.** A run makes 30-60 calls and previously reported only
  wall-clock duration — no calls, tokens, or cost signal. Provider ``usage``
  blocks are recorded when present, estimated otherwise.
* **JSON mode is requested** where the provider supports it, which is the
  cheapest available reduction in parse-failure retries.

The client is thread-safe: stages that fan out over opportunities share one
instance, and usage accumulation is mutex-guarded.
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from automation_miner.context import estimate_tokens
from automation_miner.models import mock
from automation_miner.models.config import MinerConfig, RoleRoute
from automation_miner.schemas import RoleUsage, RunUsage

T = TypeVar("T", bound=BaseModel)

MAX_JSON_ATTEMPTS = 3

# Statuses worth retrying: rate limits, timeouts, and transient upstream faults.
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})

def _schema_instruction(schema: type[BaseModel]) -> str:
    """Render the authoritative structured-output contract for a model call.

    Role prompts explain the task, but they are not a reliable substitute for
    the Pydantic contract enforced after the response. Supplying that contract
    here keeps every role aligned with the validator, including future schemas.
    """
    json_schema = json.dumps(schema.model_json_schema(), indent=2, ensure_ascii=False)
    return (
        "\n\nReturn one JSON object that validates against this exact JSON Schema:\n"
        f"{json_schema}\n\n"
        "Obey every required field, type, enum, array bound, and nested object "
        "shape. Do not add fields that the schema does not define. "
        "Return JSON only: no markdown fences or prose."
    )


class UsageTracker:
    """Thread-safe per-role call and token accounting."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._roles: dict[str, RoleUsage] = {}

    def record(
        self,
        role: str,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        seconds: float = 0.0,
        exact: bool = False,
        retries: int = 0,
        failures: int = 0,
        calls: int = 1,
    ) -> None:
        with self._lock:
            current = self._roles.get(role, RoleUsage())
            self._roles[role] = RoleUsage(
                calls=current.calls + calls,
                retries=current.retries + retries,
                failures=current.failures + failures,
                prompt_tokens=current.prompt_tokens + prompt_tokens,
                completion_tokens=current.completion_tokens + completion_tokens,
                seconds=round(current.seconds + seconds, 3),
                # Exact only if every recorded call was exact.
                exact=(current.exact or current.calls == 0) and exact,
            )

    def snapshot(self) -> RunUsage:
        with self._lock:
            roles = dict(self._roles)
        total = RunUsage(by_role=roles)
        for usage in roles.values():
            total.calls += usage.calls
            total.retries += usage.retries
            total.failures += usage.failures
            total.prompt_tokens += usage.prompt_tokens
            total.completion_tokens += usage.completion_tokens
            total.seconds = round(total.seconds + usage.seconds, 3)
        total.total_tokens = total.prompt_tokens + total.completion_tokens
        total.exact = bool(roles) and all(usage.exact for usage in roles.values())
        return total


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

    def chat(self, role: str, system: str, prompt: str) -> str:
        """Plain-text completion for one role (used for KB digests)."""
        route = self.config.resolve(role, dry_run=self.dry_run)
        if route.provider == "mock":
            result = mock.digest(prompt)
            self.usage.record(
                role,
                prompt_tokens=estimate_tokens(prompt),
                completion_tokens=estimate_tokens(result),
            )
            return result
        return self._chat_http(role, route, system, prompt)

    def call_json(self, role: str, system: str, prompt: str, schema: type[T]) -> T:
        """Request JSON, validate with pydantic, retry with the error fed back.

        Up to ``MAX_JSON_ATTEMPTS`` attempts; each failure appends the validation
        or parse error to the prompt so the model can self-correct.
        """
        route = self.config.resolve(role, dry_run=self.dry_run)
        full_prompt = prompt + _schema_instruction(schema)
        last_error = ""
        for attempt in range(1, MAX_JSON_ATTEMPTS + 1):
            if route.provider == "mock":
                raw: dict[str, Any] = mock.call_json(role, schema.__name__, prompt)
                self.usage.record(role, prompt_tokens=estimate_tokens(prompt))
            else:
                text = self._chat_http(role, route, system, full_prompt + last_error)
                try:
                    raw = _extract_json(text)
                except ValueError as exc:
                    if attempt == MAX_JSON_ATTEMPTS:
                        raise RuntimeError(
                            f"Role {role!r} returned unparseable JSON "
                            f"after {MAX_JSON_ATTEMPTS} attempts: {exc}"
                        ) from exc
                    last_error = (
                        f"\n\nYour previous response was not valid JSON:\n{exc}\n"
                        "Respond with a single JSON object only."
                    )
                    continue
            try:
                return schema.model_validate(raw)
            except ValidationError as exc:
                if attempt == MAX_JSON_ATTEMPTS:
                    raise RuntimeError(
                        f"Role {role!r} failed to produce valid {schema.__name__} "
                        f"after {MAX_JSON_ATTEMPTS} attempts: {exc}"
                    ) from exc
                last_error = (
                    f"\n\nYour previous response failed validation:\n{exc}\n"
                    "Fix it and respond with corrected JSON only."
                )
        raise AssertionError("unreachable")

    # -- HTTP ---------------------------------------------------------------

    def _chat_http(self, role: str, route: RoleRoute, system: str, prompt: str) -> str:
        api_key = os.environ.get(route.api_key_env, "")
        if not api_key:
            raise RuntimeError(
                f"{route.api_key_env} is not set (required for provider "
                f"{route.provider!r}). Set it or use --dry-run."
            )
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

        policy = self.config.retry
        started = time.monotonic()
        retries = 0
        last_error: Exception | None = None

        for attempt in range(1, policy.attempts + 1):
            try:
                response = self._http.post(
                    f"{route.base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status = exc.response.status_code
                if status not in RETRYABLE_STATUS or attempt == policy.attempts:
                    self.usage.record(
                        role, seconds=time.monotonic() - started, retries=retries, failures=1
                    )
                    raise RuntimeError(
                        f"Chat completion failed for provider {route.provider!r} "
                        f"(HTTP {status}): {_error_detail(exc.response)}"
                    ) from exc
                self._sleep(_retry_delay(policy, attempt, exc.response))
                retries += 1
                continue
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt == policy.attempts:
                    self.usage.record(
                        role, seconds=time.monotonic() - started, retries=retries, failures=1
                    )
                    raise RuntimeError(
                        f"Chat completion failed for provider {route.provider!r} "
                        f"after {policy.attempts} attempts: {exc}"
                    ) from exc
                self._sleep(_retry_delay(policy, attempt, None))
                retries += 1
                continue

            try:
                content, usage = _parse_completion(response, route.provider)
            except RuntimeError as exc:
                # A provider can return HTTP 200 before an upstream generation
                # fails, yielding no choices, empty content, or a malformed
                # envelope. These failures are transient in the same way as a
                # 5xx and are safe to retry because model calls have no side
                # effects.
                last_error = exc
                if attempt == policy.attempts:
                    self.usage.record(
                        role,
                        seconds=time.monotonic() - started,
                        retries=retries,
                        failures=1,
                    )
                    raise RuntimeError(
                        f"Completion failed for role {role!r} using "
                        f"{route.provider!r}/{route.model!r} after "
                        f"{policy.attempts} attempts: {exc}"
                    ) from exc
                self._sleep(_retry_delay(policy, attempt, None))
                retries += 1
                continue
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            exact = prompt_tokens is not None and completion_tokens is not None
            self.usage.record(
                role,
                prompt_tokens=int(prompt_tokens or estimate_tokens(system) + estimate_tokens(prompt)),
                completion_tokens=int(completion_tokens or estimate_tokens(content)),
                seconds=time.monotonic() - started,
                exact=exact,
                retries=retries,
            )
            return content

        raise RuntimeError(
            f"Chat completion failed for provider {route.provider!r}: {last_error}"
        )


def _retry_delay(policy: Any, attempt: int, response: httpx.Response | None) -> float:
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


def _error_detail(response: httpx.Response) -> str:
    """Best-effort provider error message, truncated for logs."""
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:200]
        if isinstance(error, str):
            return error[:200]
    return str(payload)[:200]


def _parse_completion(
    response: httpx.Response, provider: str
) -> tuple[str, dict[str, Any]]:
    """Extract message content and usage from an OpenAI-shaped response."""
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"Provider {provider!r} returned an invalid JSON response."
        ) from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Provider {provider!r} returned a non-object response.")
    choices = data.get("choices", [])
    if not isinstance(choices, list) or not choices:
        raise RuntimeError(f"Provider {provider!r} returned no choices.")
    first = choices[0]
    if not isinstance(first, dict) or not isinstance(first.get("message"), dict):
        raise RuntimeError(f"Provider {provider!r} returned a malformed choice.")
    content = first["message"].get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError(f"Provider {provider!r} returned empty content.")
    usage = data.get("usage")
    return content, usage if isinstance(usage, dict) else {}


def _extract_json(text: str) -> dict[str, Any]:
    """Parse a model response into a JSON object, tolerating fences/prose."""
    text = text.strip()

    def parse_object(candidate: str) -> dict[str, Any]:
        value = json.loads(candidate)
        if not isinstance(value, dict):
            raise ValueError("Model response JSON must be an object.")
        return value

    try:
        return parse_object(text)
    except (json.JSONDecodeError, ValueError):
        pass
    for fence in ("```json", "```"):
        if fence in text:
            block = text[text.rfind(fence) + len(fence) :]
            close = block.find("```")
            if close != -1:
                block = block[:close]
            try:
                return parse_object(block.strip())
            except (json.JSONDecodeError, ValueError):
                pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return parse_object(text[start : end + 1])
        except (json.JSONDecodeError, ValueError):
            pass
    raise ValueError(f"Model response is not valid JSON. Preview: {text[:200]}")
