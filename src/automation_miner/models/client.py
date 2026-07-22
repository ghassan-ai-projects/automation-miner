"""Multi-provider chat client with validated JSON output and self-healing retries.

Providers: openrouter, gemini (OpenAI-compatible endpoint), openai_compatible
(custom base_url), and mock. The httpx client is constructor-injected so tests
can swap transports without touching the network (film-pipeline pattern).

Model selection is always explicit: roles resolve through ``MinerConfig``.
"""

from __future__ import annotations

import json
import os
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from automation_miner.models import mock
from automation_miner.models.config import MinerConfig

T = TypeVar("T", bound=BaseModel)

MAX_RETRIES = 3

_JSON_INSTRUCTION = (
    "\n\nRespond with a single JSON object matching the requested schema. "
    "No markdown fences, no prose."
)


class MinerModel:
    """Role-routed chat client.

    Testable: pass ``http_client`` (e.g. ``httpx.Client(transport=MockTransport(...))``)
    to intercept HTTP. ``dry_run=True`` forces the mock provider for every role.
    """

    def __init__(
        self,
        config: MinerConfig,
        http_client: httpx.Client | None = None,
        dry_run: bool = False,
    ) -> None:
        self.config = config
        self.dry_run = dry_run
        self._http = http_client or httpx.Client(timeout=120.0)

    def routing_table(self) -> dict[str, str]:
        return self.config.routing_table(dry_run=self.dry_run)

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._http.close()

    def chat(self, role: str, system: str, prompt: str) -> str:
        """Plain-text completion for one role (used for KB digests)."""
        route = self.config.resolve(role, dry_run=self.dry_run)
        if route.provider == "mock":
            first_line = prompt.splitlines()[0] if prompt else ""
            return mock.digest(first_line[:80], prompt)
        return self._chat_http(route, system, prompt)

    def call_json(self, role: str, system: str, prompt: str, schema: type[T]) -> T:
        """Request JSON, validate with pydantic, retry with the error fed back.

        Up to ``MAX_RETRIES`` attempts; each failure appends the validation or
        parse error to the prompt so the model can self-correct.
        """
        route = self.config.resolve(role, dry_run=self.dry_run)
        full_prompt = prompt + _JSON_INSTRUCTION
        last_error = ""
        for attempt in range(1, MAX_RETRIES + 1):
            if route.provider == "mock":
                raw = mock.call_json(role, schema.__name__, prompt)
            else:
                text = self._chat_http(route, system, full_prompt + last_error)
                try:
                    raw = _extract_json(text)
                except ValueError as exc:
                    if attempt == MAX_RETRIES:
                        raise RuntimeError(
                            f"Role {role!r} returned unparseable JSON "
                            f"after {MAX_RETRIES} attempts: {exc}"
                        ) from exc
                    last_error = (
                        f"\n\nYour previous response was not valid JSON:\n{exc}\n"
                        "Respond with a single JSON object only."
                    )
                    continue
            try:
                return schema.model_validate(raw)
            except ValidationError as exc:
                if attempt == MAX_RETRIES:
                    raise RuntimeError(
                        f"Role {role!r} failed to produce valid {schema.__name__} "
                        f"after {MAX_RETRIES} attempts: {exc}"
                    ) from exc
                last_error = (
                    f"\n\nYour previous response failed validation:\n{exc}\n"
                    "Fix it and respond with corrected JSON only."
                )
        raise AssertionError("unreachable")

    def _chat_http(self, route: Any, system: str, prompt: str) -> str:
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
        body = {
            "model": route.model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 8192,
        }
        try:
            resp = self._http.post(
                f"{route.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Chat completion failed for provider {route.provider!r}: {exc}"
            ) from exc
        try:
            data = resp.json()
        except ValueError as exc:
            raise RuntimeError(
                f"Provider {route.provider!r} returned an invalid JSON response."
            ) from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"Provider {route.provider!r} returned a non-object response.")
        choices = data.get("choices", [])
        if not isinstance(choices, list) or not choices:
            raise RuntimeError(f"Provider {route.provider!r} returned no choices.")
        first = choices[0]
        if not isinstance(first, dict) or not isinstance(first.get("message"), dict):
            raise RuntimeError(f"Provider {route.provider!r} returned a malformed choice.")
        content = first["message"].get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(f"Provider {route.provider!r} returned empty content.")
        return content


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
