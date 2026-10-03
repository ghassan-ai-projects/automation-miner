"""Built-in routing, sampling, retry, concurrency, and budget defaults."""

from __future__ import annotations

from typing import Any

PIPELINE_ROLES = ("mapper", "layer_analyst", "drafter", "critic", "refiner", "scorer")
# The judge never runs inside a mining run. It powers ``automation-miner
# evaluate`` and should be a stronger model from a different family than the
# generator, so a run is not graded by the model that wrote it.
EVALUATION_ROLES = ("judge",)
ROLES = PIPELINE_ROLES + EVALUATION_ROLES

# Per-role sampling and output limits. Reasoning models spend completion
# tokens on thinking before any JSON appears: a 4k critic limit returned empty
# content four times in a row and failed a real run. The defaults leave room
# for reasoning; flash-class output costs cents per million tokens.
ROLE_DEFAULTS: dict[str, dict[str, Any]] = {
    "mapper": {"temperature": 0.2, "max_tokens": 16_000, "reasoning_max_tokens": 3_000},
    "layer_analyst": {"temperature": 0.3, "max_tokens": 16_000, "reasoning_max_tokens": 3_000},
    "drafter": {"temperature": 0.4, "max_tokens": 24_000, "reasoning_max_tokens": 4_000},
    "critic": {"temperature": 0.2, "max_tokens": 16_000, "reasoning_max_tokens": 4_000},
    "refiner": {"temperature": 0.3, "max_tokens": 24_000, "reasoning_max_tokens": 3_000},
    "scorer": {"temperature": 0.1, "max_tokens": 16_000, "reasoning_max_tokens": 3_000},
    "judge": {"temperature": 0.0, "max_tokens": 16_000, "reasoning_max_tokens": 4_000},
}

REASONING_EFFORTS = frozenset({"", "off", "minimal", "low", "medium", "high"})

DEFAULT_RETRY: dict[str, Any] = {
    "attempts": 4,
    "initial_seconds": 1.0,
    "backoff": 2.0,
    "max_seconds": 30.0,
    "jitter": 0.25,
    # Per-request ceiling. Without it a single stalled provider call could hold
    # a run for its entire remaining wall-clock budget instead of retrying.
    "request_seconds": 300.0,
    # Streaming only: give up on an attempt after this long without a data
    # chunk. Keep-alive comments do not count as progress.
    "stall_seconds": 60.0,
}

DEFAULT_CONCURRENCY: dict[str, Any] = {
    "critique": 8,
    "score": 4,
}

# A runaway ceiling, not a cost target. Measured real runs (Oct 2026): a
# one-liner uses ~65k tokens before drafting and a three-file KB ~100k before
# portfolio planning; a full run is 300k-700k tokens across ~50 calls. The old
# 120k default failed every real run with budget_exhausted. Admission also
# reserves each call's max_tokens up front, so parallel drafting needs headroom.
DEFAULT_BUDGET: dict[str, Any] = {
    "max_attempts": 200,
    "max_tokens": 1_500_000,
    "max_seconds": 2_400.0,
}

DEFAULT_CONFIG: dict[str, Any] = {
    "providers": {
        "openrouter": {
            "base_url": "https://openrouter.ai/api/v1",
            "api_key_env": "OPENROUTER_API_KEY",
            "supports_json_mode": True,
            "stream": True,
            # Measured 2026-10-03 for deepseek-v4-flash: this upstream ignores
            # the reasoning cap and spends the whole completion budget
            # thinking (7.6k-15.5k reasoning tokens, no answer). Override with
            # routing = {} in miner.toml to re-enable it.
            "routing": {"ignore": ["Relace"]},
        },
        "gemini": {
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "api_key_env": "GOOGLE_API_KEY",
            "supports_json_mode": True,
        },
    },
    "roles": {
        role: {"provider": "openrouter", "model": "deepseek/deepseek-v4-flash"}
        for role in ROLES
    },
}
