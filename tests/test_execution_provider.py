"""Provider-client integration with per-run token admission."""

from __future__ import annotations

import json
import time

import httpx
import pytest

from automation_miner.execution import BudgetExceeded, RunExecutionContext
from automation_miner.models.client import MinerModel
from automation_miner.models.config import MinerConfig
from automation_miner.schemas import RunBudget


def test_provider_usage_is_exact_and_token_budget_stops_next_request(monkeypatch) -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 900},
            },
        )

    config = MinerConfig(
        providers={"custom": {"base_url": "https://provider.test/v1", "api_key_env": "KEY"}},
        roles={"mapper": {"provider": "custom", "model": "model", "max_tokens": 1_000}},
        budget={"max_attempts": 5, "max_tokens": 1_100, "max_seconds": 30},
    )
    model = MinerModel(
        config,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        dry_run=False,
    )
    execution = RunExecutionContext("2026-08-28_provider", RunBudget(**config.budget))
    try:
        monkeypatch.setenv("KEY", "test-key")
        assert model.chat("mapper", "", "x", execution=execution) == "ok"
        assert execution.usage.snapshot().exact is True
        with pytest.raises(BudgetExceeded, match="max_tokens"):
            model.chat("mapper", "", "x", execution=execution)
    finally:
        model.close()

    assert len(requests) == 1


def test_terminal_provider_failure_persists_attempt_tokens_and_retry_count(monkeypatch) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"message": "down"}})

    config = MinerConfig(
        providers={"custom": {"base_url": "https://provider.test/v1", "api_key_env": "KEY"}},
        roles={"mapper": {"provider": "custom", "model": "model", "max_tokens": 1_000}},
        budget={"max_attempts": 5, "max_tokens": 10_000, "max_seconds": 30},
    )
    model = MinerModel(
        config,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        dry_run=False,
        sleep=lambda _: None,
    )
    execution = RunExecutionContext("2026-08-28_provider-failure", RunBudget(**config.budget))
    monkeypatch.setenv("KEY", "test-key")
    try:
        with pytest.raises(RuntimeError, match="down"):
            model.chat("mapper", "", "x", execution=execution)
    finally:
        model.close()

    usage = execution.usage.snapshot()
    assert usage.calls == 0
    assert usage.attempts == 4
    assert usage.retries == 3
    assert usage.attempted_tokens > 0
    assert execution.snapshot().tokens == usage.attempted_tokens


def test_unknown_failed_attempt_consumes_full_token_reservation(monkeypatch) -> None:
    requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(503, json={"error": {"message": "down"}})

    config = MinerConfig(
        providers={"custom": {"base_url": "https://provider.test/v1", "api_key_env": "KEY"}},
        roles={"mapper": {"provider": "custom", "model": "model", "max_tokens": 1_000}},
        budget={"max_attempts": 5, "max_tokens": 1_100, "max_seconds": 30},
    )
    model = MinerModel(
        config,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        dry_run=False,
        sleep=lambda _: None,
    )
    execution = RunExecutionContext("2026-08-28_full-reservation", RunBudget(**config.budget))
    monkeypatch.setenv("KEY", "test-key")
    try:
        with pytest.raises(BudgetExceeded, match="max_tokens"):
            model.chat("mapper", "", "x", execution=execution)
    finally:
        model.close()

    assert requests == 1
    assert execution.snapshot().attempts == 1
    assert execution.snapshot().tokens >= 1_000


def test_malformed_provider_usage_falls_back_to_estimates(monkeypatch) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": "unknown", "completion_tokens": -1},
            },
        )

    config = MinerConfig(
        providers={"custom": {"base_url": "https://provider.test/v1", "api_key_env": "KEY"}},
        roles={"mapper": {"provider": "custom", "model": "model"}},
    )
    model = MinerModel(
        config,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        dry_run=False,
    )
    execution = RunExecutionContext("2026-08-28_malformed-usage", RunBudget())
    monkeypatch.setenv("KEY", "test-key")
    try:
        assert model.chat("mapper", "system", "input", execution=execution) == "ok"
    finally:
        model.close()

    usage = execution.usage.snapshot()
    assert usage.exact is False
    assert usage.prompt_tokens > 0
    assert usage.completion_tokens > 0
    assert execution.snapshot().attempts == 1


@pytest.mark.parametrize("response_json", [{"choices": []}, {"choices": [{}]}])
def test_deadline_is_checked_after_terminal_provider_response(
    monkeypatch, response_json: dict
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        time.sleep(0.01)
        return httpx.Response(200, json=response_json)

    config = MinerConfig(
        providers={"custom": {"base_url": "https://provider.test/v1", "api_key_env": "KEY"}},
        roles={"mapper": {"provider": "custom", "model": "model"}},
        budget={"max_attempts": 5, "max_tokens": 120_000, "max_seconds": 0.001},
    )
    model = MinerModel(
        config,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        dry_run=False,
        sleep=lambda _: None,
    )
    execution = RunExecutionContext("2026-08-28_late-response", RunBudget(**config.budget))
    monkeypatch.setenv("KEY", "test-key")
    try:
        with pytest.raises(BudgetExceeded, match="max_seconds"):
            model.chat("mapper", "", "x", execution=execution)
    finally:
        model.close()


def test_provider_reported_zero_usage_is_not_replaced_by_estimates(monkeypatch) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            },
        )

    config = MinerConfig(
        providers={"custom": {"base_url": "https://provider.test/v1", "api_key_env": "KEY"}},
        roles={"mapper": {"provider": "custom", "model": "model"}},
    )
    model = MinerModel(
        config,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        dry_run=False,
    )
    monkeypatch.setenv("KEY", "test-key")
    try:
        assert model.chat("mapper", "", "x") == "ok"
    finally:
        model.close()

    usage = model.usage.snapshot()
    assert usage.prompt_tokens == 0
    assert usage.completion_tokens == 0
    assert usage.exact is True


def test_unexpected_provider_exception_is_in_failure_telemetry(monkeypatch) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise RuntimeError("transport adapter failed")

    config = MinerConfig(
        providers={"custom": {"base_url": "https://provider.test/v1", "api_key_env": "KEY"}},
        roles={"mapper": {"provider": "custom", "model": "model"}},
    )
    model = MinerModel(
        config,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    execution = RunExecutionContext("2026-08-28_unexpected-provider", RunBudget())
    monkeypatch.setenv("KEY", "test-key")
    try:
        with pytest.raises(RuntimeError, match="transport adapter failed"):
            model.chat("mapper", "", "x", execution=execution)
    finally:
        model.close()

    usage = execution.usage.snapshot()
    assert usage.calls == 0
    assert usage.failures == 1
    assert usage.attempts == 1
    assert usage.attempted_tokens > 0
