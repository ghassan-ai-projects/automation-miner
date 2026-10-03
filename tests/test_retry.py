"""HTTP retry, backoff, and usage telemetry.

A single 429 previously aborted a run outright, discarding every already-paid
call before it. These tests drive the real client through a mock transport.
"""

from __future__ import annotations

import httpx
import pytest

from automation_miner.models.client import RETRYABLE_STATUS, MinerModel, UsageTracker
from automation_miner.models.config import MinerConfig, RetryPolicy, load_config
from automation_miner.schemas import DomainMap

COMPLETION = {
    "choices": [{"message": {"content": '{"ok": true}'}}],
    "usage": {"prompt_tokens": 120, "completion_tokens": 30},
}


@pytest.fixture
def config(monkeypatch: pytest.MonkeyPatch) -> MinerConfig:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    cfg = load_config(None)
    cfg.retry = RetryPolicy(attempts=4, initial_seconds=0.01, backoff=2.0, jitter=0.0)
    return cfg


def _model(config: MinerConfig, handler, sleeps: list[float] | None = None) -> MinerModel:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return MinerModel(
        config,
        http_client=client,
        sleep=(sleeps.append if sleeps is not None else lambda _: None),
    )


class _Schema(DomainMap):
    pass


def test_retries_then_succeeds_on_rate_limit(config: MinerConfig) -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(429, json={"error": {"message": "slow down"}})
        return httpx.Response(200, json=COMPLETION)

    sleeps: list[float] = []
    model = _model(config, handler, sleeps)
    assert model.chat("mapper", "sys", "prompt") == '{"ok": true}'
    assert attempts["n"] == 3
    assert len(sleeps) == 2
    # Exponential: the second wait is longer than the first.
    assert sleeps[1] > sleeps[0]

    usage = model.usage.snapshot()
    assert usage.calls == 1
    assert usage.retries == 2
    assert usage.prompt_tokens == 120
    assert usage.exact is True


def test_gives_up_after_the_configured_attempts(config: MinerConfig) -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(503, json={"error": {"message": "upstream down"}})

    model = _model(config, handler)
    with pytest.raises(RuntimeError, match="upstream down"):
        model.chat("mapper", "sys", "prompt")
    assert attempts["n"] == config.retry.attempts
    assert model.usage.snapshot().failures == 1


def test_non_retryable_status_fails_immediately(config: MinerConfig) -> None:
    """A 401 will not fix itself; burning the retry budget on it wastes time."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(401, json={"error": {"message": "invalid api key"}})

    model = _model(config, handler)
    with pytest.raises(RuntimeError, match="invalid api key"):
        model.chat("mapper", "sys", "prompt")
    assert attempts["n"] == 1
    assert 401 not in RETRYABLE_STATUS


def test_retry_after_header_is_honoured(config: MinerConfig) -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "7"}, json={})
        return httpx.Response(200, json=COMPLETION)

    sleeps: list[float] = []
    _model(config, handler, sleeps).chat("mapper", "sys", "prompt")
    assert sleeps == [7.0]


def test_retry_after_is_capped_by_policy(config: MinerConfig) -> None:
    config.retry = RetryPolicy(attempts=2, initial_seconds=0.01, max_seconds=5.0, jitter=0.0)

    def handler(request: httpx.Request) -> httpx.Response:
        if not getattr(handler, "seen", False):
            handler.seen = True  # type: ignore[attr-defined]
            return httpx.Response(429, headers={"retry-after": "3600"}, json={})
        return httpx.Response(200, json=COMPLETION)

    sleeps: list[float] = []
    _model(config, handler, sleeps).chat("mapper", "sys", "prompt")
    assert sleeps == [5.0]


def test_network_errors_retry(config: MinerConfig) -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise httpx.ConnectTimeout("timed out")
        return httpx.Response(200, json=COMPLETION)

    model = _model(config, handler)
    model.chat("mapper", "sys", "prompt")
    assert attempts["n"] == 2


def test_missing_api_key_is_reported_before_any_request(
    config: MinerConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request should be made")

    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY is not set"):
        _model(config, handler).chat("mapper", "sys", "prompt")


def test_per_role_sampling_settings_reach_the_request(config: MinerConfig) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(200, json=COMPLETION)

    model = _model(config, handler)
    model.chat("drafter", "sys", "prompt")
    # The drafter emits a full draft with two tables after reasoning; one
    # global 8192 cap truncated it into unparseable JSON.
    assert captured["max_tokens"] == 24_000
    assert captured["temperature"] == 0.4
    assert captured["response_format"] == {"type": "json_object"}

    captured.clear()
    model.chat("scorer", "sys", "prompt")
    assert captured["max_tokens"] == 16_000
    assert captured["temperature"] == 0.1


def test_json_mode_can_be_disabled_per_provider(config: MinerConfig) -> None:
    config.providers["openrouter"]["supports_json_mode"] = False
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(200, json=COMPLETION)

    _model(config, handler).chat("mapper", "sys", "prompt")
    assert "response_format" not in captured


def test_usage_is_estimated_when_the_provider_omits_it(config: MinerConfig) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})

    model = _model(config, handler)
    model.chat("mapper", "sys", "a much longer prompt than the reply")
    usage = model.usage.snapshot()
    assert usage.prompt_tokens > 0
    assert usage.exact is False


def test_usage_tracker_aggregates_per_role() -> None:
    tracker = UsageTracker()
    tracker.record("drafter", prompt_tokens=100, completion_tokens=50, exact=True)
    tracker.record("drafter", prompt_tokens=10, completion_tokens=5, exact=True)
    tracker.record("critic", prompt_tokens=7, completion_tokens=1, exact=False)

    snapshot = tracker.snapshot()
    assert snapshot.calls == 3
    assert snapshot.by_role["drafter"].calls == 2
    assert snapshot.by_role["drafter"].total_tokens == 165
    assert snapshot.total_tokens == 173
    # One estimated call makes the whole run's total inexact.
    assert snapshot.exact is False


def test_usage_tracker_is_thread_safe() -> None:
    from concurrent.futures import ThreadPoolExecutor

    tracker = UsageTracker()
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: tracker.record("drafter", prompt_tokens=1), range(400)))
    assert tracker.snapshot().by_role["drafter"].calls == 400
    assert tracker.snapshot().prompt_tokens == 400


def test_retry_policy_delays_grow_and_cap() -> None:
    policy = RetryPolicy(attempts=6, initial_seconds=1.0, backoff=3.0, max_seconds=10.0)
    assert policy.delay_for(1) == 1.0
    assert policy.delay_for(2) == 3.0
    assert policy.delay_for(3) == 9.0
    assert policy.delay_for(4) == 10.0


def test_reasoning_effort_is_forwarded_and_validated(config: MinerConfig) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(200, json=COMPLETION)

    config.roles["critic"] = {**config.roles["critic"], "reasoning_effort": "low"}
    config.roles["scorer"] = {**config.roles["scorer"], "reasoning_effort": "off"}
    model = _model(config, handler)
    model.chat("critic", "sys", "prompt")
    assert captured["reasoning"] == {"effort": "low"}
    captured.clear()
    model.chat("scorer", "sys", "prompt")
    assert captured["reasoning"] == {"enabled": False}
    captured.clear()
    model.chat("mapper", "sys", "prompt")
    # No explicit effort: thinking is capped so it cannot starve the answer,
    # and the measured runaway upstream is excluded from routing.
    assert captured["reasoning"] == {"max_tokens": 3_000}
    assert captured["provider"] == {"ignore": ["Relace"]}

    config.roles["mapper"] = {**config.roles["mapper"], "reasoning_effort": "extreme"}
    with pytest.raises(ValueError, match="reasoning_effort"):
        config.resolve("mapper")


def test_request_timeout_is_capped_per_attempt_not_by_the_run(config: MinerConfig) -> None:
    """A stalled call must time out and retry, not hold the whole run budget."""
    from automation_miner.execution import RunExecutionContext
    from automation_miner.schemas import RunBudget

    timeouts: list[float] = []
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        timeouts.append(request.extensions["timeout"]["read"])
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("stalled", request=request)
        return httpx.Response(200, json=COMPLETION)

    config.retry = RetryPolicy(attempts=3, initial_seconds=0.0, jitter=0.0, request_seconds=42.0)
    execution = RunExecutionContext("run", RunBudget(max_seconds=2_400))
    result = _model(config, handler).chat("mapper", "sys", "prompt", execution=execution)
    assert result == '{"ok": true}'
    assert calls["n"] == 2
    assert all(timeout == 42.0 for timeout in timeouts)
