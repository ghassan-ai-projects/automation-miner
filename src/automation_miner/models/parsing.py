"""Response parsing: structured-output instructions and tolerant JSON extraction."""

from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import BaseModel


def schema_instruction(schema: type[BaseModel]) -> str:
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


def error_detail(response: httpx.Response) -> str:
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


def parse_completion(
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


def reported_token_count(value: object) -> int | None:
    """Accept only non-negative integer provider usage values."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def reported_cost(usage: dict[str, Any]) -> float:
    """Provider-reported spend in USD; 0 when absent or malformed."""
    cost = usage.get("cost")
    if isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost < 0:
        return 0.0
    return float(cost)


def _parse_object(candidate: str) -> dict[str, Any]:
    value = json.loads(candidate)
    if not isinstance(value, dict):
        raise ValueError("Model response JSON must be an object.")
    return value


def _json_candidates(text: str) -> list[str]:
    """The whole text, the last fenced block, then the outermost braces."""
    candidates = [text]
    for fence in ("```json", "```"):
        if fence in text:
            block = text[text.rfind(fence) + len(fence) :]
            close = block.find("```")
            candidates.append((block[:close] if close != -1 else block).strip())
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    return candidates


def extract_json(text: str) -> dict[str, Any]:
    """Parse a model response into a JSON object, tolerating fences/prose."""
    text = text.strip()
    for candidate in _json_candidates(text):
        try:
            return _parse_object(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
    raise ValueError(f"Model response is not valid JSON. Preview: {text[:200]}")
