"""Provider-specific request bodies and the per-provider concurrency cap."""

from __future__ import annotations


def test_openrouter_extensions_are_not_sent_to_other_providers() -> None:
    from automation_miner.models.config import load_config
    from automation_miner.models.transport import request_body

    config = load_config(None)
    config.roles["judge"] = {"provider": "zai", "model": "glm-5.3-flash"}
    route = config.resolve("judge")
    assert route.base_url == "https://api.z.ai/api/coding/paas/v4"
    assert route.api_key_env == "ZAI_API_KEY" and route.stream and route.max_concurrent == 2
    body = request_body(route, "sys", "prompt")
    assert "reasoning" not in body and "provider" not in body
    assert body["response_format"] == {"type": "json_object"}


def test_provider_gate_caps_requests_in_flight_across_threads() -> None:
    import threading
    import time as _time

    from automation_miner.models.config import RoleRoute
    from automation_miner.models.transport import provider_gate

    route = RoleRoute(provider="capped", model="m", base_url="https://x", max_concurrent=2)
    active, peak, lock = [0], [0], threading.Lock()

    def work() -> None:
        with provider_gate(route):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            _time.sleep(0.02)
            with lock:
                active[0] -= 1

    threads = [threading.Thread(target=work) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert peak[0] == 2
    uncapped = RoleRoute(provider="free", model="m")
    with provider_gate(uncapped):
        pass
