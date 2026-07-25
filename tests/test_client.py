"""Tests for MinerModel: HTTP path, self-healing retries, key handling."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel

from automation_miner.models.client import MinerModel
from automation_miner.models.config import MinerConfig


class _Out(BaseModel):
    name: str
    value: int


def _config() -> MinerConfig:
    return MinerConfig(
        providers={
            "openrouter": {
                "base_url": "https://openrouter.ai/api/v1",
                "api_key_env": "OPENROUTER_API_KEY",
            }
        },
        roles={"mapper": {"provider": "openrouter", "model": "m"}},
    )


def _client(responses: list[str]) -> tuple[MinerModel, list[dict]]:
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        text = responses[min(len(sent) - 1, len(responses) - 1)]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": text}}]},
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    return MinerModel(_config(), http_client=http, sleep=lambda _: None), sent


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MINER_MODEL", raising=False)
    monkeypatch.delenv("MINER_PROVIDER", raising=False)


def test_valid_json_first_try() -> None:
    client, sent = _client(['{"name": "a", "value": 1}'])
    out = client.call_json("mapper", "sys", "prompt", _Out)
    assert out == _Out(name="a", value=1)
    assert len(sent) == 1
    structured_prompt = sent[0]["messages"][-1]["content"]
    assert "exact JSON Schema" in structured_prompt
    assert '"name"' in structured_prompt
    assert '"value"' in structured_prompt
    assert '"type": "integer"' in structured_prompt
    assert "Do not add fields that the schema does not define." in structured_prompt


def test_fenced_json_is_extracted() -> None:
    client, _ = _client(['Here you go:\n```json\n{"name": "b", "value": 2}\n```'])
    assert client.call_json("mapper", "sys", "prompt", _Out).value == 2


def test_parse_failure_retries_with_feedback() -> None:
    client, sent = _client(["not json at all", '{"name": "c", "value": 3}'])
    out = client.call_json("mapper", "sys", "prompt", _Out)
    assert out.value == 3
    assert len(sent) == 2
    retry_prompt = sent[1]["messages"][-1]["content"]
    assert "not valid JSON" in retry_prompt


def test_validation_failure_retries_with_errors() -> None:
    client, sent = _client(['{"name": "d"}', '{"name": "d", "value": 4}'])
    out = client.call_json("mapper", "sys", "prompt", _Out)
    assert out.value == 4
    assert len(sent) == 2
    retry_prompt = sent[1]["messages"][-1]["content"]
    assert "failed validation" in retry_prompt


def test_exhausted_retries_raise() -> None:
    client, sent = _client(["garbage"] * 5)
    with pytest.raises(RuntimeError, match="unparseable JSON"):
        client.call_json("mapper", "sys", "prompt", _Out)
    assert len(sent) == 3  # MAX_RETRIES


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY")
    client, _ = _client(['{"name": "a", "value": 1}'])
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY is not set"):
        client.call_json("mapper", "sys", "prompt", _Out)


def test_non_object_json_retries() -> None:
    client, sent = _client(["null", '{"name": "valid", "value": 5}'])
    assert client.call_json("mapper", "sys", "prompt", _Out).value == 5
    assert len(sent) == 2


def test_empty_provider_content_retries() -> None:
    client, sent = _client(["", '{"name": "valid", "value": 5}'])
    assert client.call_json("mapper", "sys", "prompt", _Out).value == 5
    assert len(sent) == 2
    assert client.usage.snapshot().retries == 1


def test_malformed_provider_envelope_raises_runtime_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"unexpected": True}]})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = MinerModel(_config(), http_client=http, sleep=lambda _: None)
    with pytest.raises(RuntimeError, match="malformed choice"):
        client.call_json("mapper", "sys", "prompt", _Out)


def test_close_releases_http_client() -> None:
    client, _ = _client(['{"name": "a", "value": 1}'])
    client.close()
    assert client._http.is_closed
