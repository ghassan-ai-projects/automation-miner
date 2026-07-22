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
