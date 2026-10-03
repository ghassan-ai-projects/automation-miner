"""Read an OpenAI-compatible completion, streamed (SSE) or as one JSON body.

Non-streaming calls cannot tell a slow-but-working generation from a stalled
upstream: a real run waited 7.3 minutes on one layer-analysis call until the
request timeout fired. Streamed, every reasoning or content delta is proof of
progress, so an attempt is abandoned only after ``stall_seconds`` without a
data chunk (keep-alive comments do not count) and retried immediately.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

import httpx

from automation_miner.models.parsing import parse_completion


class StreamStalled(httpx.ReadTimeout):
    """No data chunk arrived within the stall window; retry like a timeout."""


class BadCompletion(RuntimeError):
    """HTTP 200 without a usable completion: empty, malformed, or a mid-stream error."""


class _Stream:
    """Accumulates one SSE stream and enforces the stall and deadline limits."""

    def __init__(self, provider: str, stall: float, deadline: float, clock: Callable[[], float]):
        self.provider, self.stall, self.deadline, self.clock = provider, stall, deadline, clock
        self.started = self.last_data = clock()
        self.parts: list[str] = []
        self.usage: dict[str, Any] = {}

    def feed(self, line: str) -> bool:
        """Consume one line; False once the stream is done."""
        now = self.clock()
        if now - self.started > self.deadline:
            raise StreamStalled(f"Provider {self.provider!r} exceeded the request deadline")
        if line.startswith(":"):  # keep-alive comment: not progress
            if now - self.last_data > self.stall:
                raise StreamStalled(f"Provider {self.provider!r} sent no data for {self.stall:g}s")
            return True
        if not line.startswith("data:"):
            return True  # event separator or a field we do not use
        payload = line[5:].strip()
        if payload == "[DONE]":
            return False
        self.last_data = now
        self._chunk(payload)
        return True

    def _chunk(self, payload: str) -> None:
        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError:
            return
        if not isinstance(chunk, dict):
            return
        if chunk.get("error"):
            raise BadCompletion(f"Provider {self.provider!r} failed mid-stream: {chunk['error']}")
        if isinstance(chunk.get("usage"), dict):
            self.usage = chunk["usage"]
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") if isinstance(choice, dict) else None
            if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                self.parts.append(delta["content"])


def read_completion(
    response: httpx.Response,
    provider: str,
    stall_seconds: float,
    deadline_seconds: float,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[str, dict[str, Any]]:
    """Return (content, usage) from a streaming or plain response."""
    if "text/event-stream" not in response.headers.get("content-type", ""):
        response.read()
        try:
            return parse_completion(response, provider)
        except RuntimeError as exc:
            raise BadCompletion(str(exc)) from exc
    stream = _Stream(provider, stall_seconds, deadline_seconds, clock)
    for line in response.iter_lines():
        if not stream.feed(line):
            break
    content = "".join(stream.parts)
    if not content.strip():
        raise BadCompletion(f"Provider {provider!r} returned empty content.")
    return content, stream.usage
