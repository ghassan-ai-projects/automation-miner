"""Streamed completions: progress is visible, stalls retry fast, errors retry."""

from __future__ import annotations

import json

import httpx
import pytest

from automation_miner.models.client import MinerModel
from automation_miner.models.config import RetryPolicy, load_config
from automation_miner.models.streaming import BadCompletion, StreamStalled, read_completion


def _sse(*events: str) -> httpx.Response:
    body = "".join(f"{event}\n\n" for event in events)
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)


def _data(payload: dict) -> str:
    return "data: " + json.dumps(payload)


CHUNKS = (
    ": OPENROUTER PROCESSING",
    _data({"choices": [{"delta": {"reasoning": "thinking"}}]}),
    _data({"choices": [{"delta": {"content": '{"ok": '}}]}),
    _data({"choices": [{"delta": {"content": "true}"}}], "usage": {"prompt_tokens": 11, "completion_tokens": 7}}),
    "data: [DONE]",
)


def test_stream_assembles_content_and_usage() -> None:
    content, usage = read_completion(_sse(*CHUNKS), "openrouter", 60, 300)
    assert content == '{"ok": true}'
    assert usage == {"prompt_tokens": 11, "completion_tokens": 7}


def test_keepalive_only_stream_counts_as_stalled() -> None:
    ticks = iter([0.0, 0.0, 100.0, 100.0])
    with pytest.raises(StreamStalled, match="no data"):
        read_completion(
            _sse(": ping", ": ping", ": ping"), "openrouter", 60, 300, clock=lambda: next(ticks)
        )


def test_mid_stream_error_and_empty_content_are_bad_completions() -> None:
    with pytest.raises(BadCompletion, match="mid-stream"):
        read_completion(_sse(_data({"error": {"message": "upstream"}})), "openrouter", 60, 300)
    with pytest.raises(BadCompletion, match="empty content"):
        read_completion(_sse(_data({"choices": [{"delta": {"reasoning": "x"}}]}), "data: [DONE]"),
                        "openrouter", 60, 300)


def test_client_streams_by_default_and_retries_a_stalled_attempt(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    config = load_config(None)
    config.retry = RetryPolicy(attempts=3, initial_seconds=0.0, jitter=0.0, stall_seconds=0.0)
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            return _sse(": ping", ": ping")  # stall: keep-alives, no data
        return _sse(*CHUNKS[1:])  # no keep-alive: data arrives at once

    model = MinerModel(config, http_client=httpx.Client(transport=httpx.MockTransport(handler)),
                       sleep=lambda _: None)
    assert model.chat("mapper", "sys", "prompt") == '{"ok": true}'
    assert len(bodies) == 2 and all(body["stream"] is True for body in bodies)
    usage = model.usage.snapshot().by_role["mapper"]
    assert usage.retries == 1 and usage.prompt_tokens == 11 and usage.exact


def test_workspace_provider_table_keeps_streaming_default(tmp_path) -> None:
    (tmp_path / "miner.toml").write_text(
        '[providers.openrouter]\nbase_url = "https://openrouter.ai/api/v1"\n'
        'api_key_env = "OPENROUTER_API_KEY"\n', encoding="utf-8"
    )
    assert load_config(tmp_path).resolve("critic").stream is True
