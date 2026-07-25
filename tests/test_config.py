"""Configuration validation and profile selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from automation_miner.models.config import MinerConfig, load_config


def test_provider_requires_endpoint_and_key_env() -> None:
    config = MinerConfig(
        providers={"custom": {"base_url": "", "api_key_env": ""}},
        roles={"mapper": {"provider": "custom", "model": "model"}},
    )
    with pytest.raises(ValueError, match="base_url"):
        config.resolve("mapper")


def test_unknown_named_profile_fails_fast(tmp_path: Path) -> None:
    (tmp_path / "miner.toml").write_text(
        "[profiles.cheap.roles]\nmapper = { provider = 'mock', model = 'mock' }\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not defined"):
        load_config(tmp_path, profile="typo")


# --- v4 tunables: per-role limits, retry, concurrency, context, readers -----


def test_role_defaults_differ_per_role() -> None:
    config = load_config(None)
    drafter = config.resolve("drafter")
    scorer = config.resolve("scorer")
    assert drafter.max_tokens > scorer.max_tokens
    assert drafter.temperature > scorer.temperature


def test_toml_overrides_role_sampling(tmp_path: Path) -> None:
    (tmp_path / "miner.toml").write_text(
        """
[roles]
drafter = { provider = "openrouter", model = "m", temperature = 0.9, max_tokens = 32000 }
""",
        encoding="utf-8",
    )
    route = load_config(tmp_path).resolve("drafter")
    assert route.temperature == 0.9
    assert route.max_tokens == 32_000


def test_context_readers_retry_and_concurrency_tables_load(tmp_path: Path) -> None:
    (tmp_path / "miner.toml").write_text(
        """
[context]
evidence_tokens = 90000
layer_tokens = 20000

[readers]
disabled = ["pptx"]
max_file_bytes = 5000000

[readers.csv]
sample_rows = 40

[retry]
attempts = 7
max_seconds = 12

[concurrency]
critique = 8
""",
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.context["evidence_tokens"] == 90_000
    assert config.readers["disabled"] == ["pptx"]
    assert config.readers["csv"]["sample_rows"] == 40
    assert config.retry.attempts == 7
    assert config.retry.max_seconds == 12.0
    assert config.workers_for("critique") == 8
    assert config.workers_for("score") == 4  # default retained


def test_workers_for_rejects_nonsense() -> None:
    config = load_config(None)
    config.concurrency = {"critique": "many"}
    assert config.workers_for("critique") == 1


def test_profile_can_override_context_and_concurrency(tmp_path: Path) -> None:
    (tmp_path / "miner.toml").write_text(
        """
[context]
evidence_tokens = 1000

[profiles.deep.context]
evidence_tokens = 200000

[profiles.deep.concurrency]
critique = 2
""",
        encoding="utf-8",
    )
    assert load_config(tmp_path).context["evidence_tokens"] == 1_000
    deep = load_config(tmp_path, "deep")
    assert deep.context["evidence_tokens"] == 200_000
    assert deep.workers_for("critique") == 2


def test_dry_run_still_carries_role_sampling_defaults() -> None:
    route = load_config(None).resolve("drafter", dry_run=True)
    assert route.provider == "mock"
    assert route.max_tokens == 16_000
