"""Model routing configuration: miner.toml loading and role resolution.

Config is read from ``miner.toml`` in the workspace, falling back to
``~/.config/automation-miner/miner.toml``. Missing config falls back to the
built-in defaults from DESIGN.md. Env vars override everything:
``MINER_PROVIDER`` (all roles), ``MINER_MODEL`` (all roles),
``MINER_MODEL_<ROLE>`` (one role).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROLES = ("mapper", "layer_analyst", "drafter", "critic", "refiner", "scorer")

DEFAULT_CONFIG: dict[str, Any] = {
    "providers": {
        "openrouter": {
            "base_url": "https://openrouter.ai/api/v1",
            "api_key_env": "OPENROUTER_API_KEY",
        },
        "gemini": {
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "api_key_env": "GOOGLE_API_KEY",
        },
    },
    "roles": {
        "mapper": {"provider": "openrouter", "model": "anthropic/claude-sonnet-4"},
        "layer_analyst": {"provider": "openrouter", "model": "anthropic/claude-sonnet-4"},
        "drafter": {"provider": "openrouter", "model": "anthropic/claude-sonnet-4"},
        "critic": {"provider": "openrouter", "model": "openai/gpt-4.1"},
        "refiner": {"provider": "openrouter", "model": "anthropic/claude-sonnet-4"},
        "scorer": {"provider": "openrouter", "model": "openai/gpt-4.1"},
    },
}


@dataclass(frozen=True)
class RoleRoute:
    """Resolved provider + model for one pipeline role."""

    provider: str
    model: str
    base_url: str = ""
    api_key_env: str = ""


@dataclass
class MinerConfig:
    """Effective model routing configuration."""

    providers: dict[str, dict[str, Any]] = field(default_factory=dict)
    roles: dict[str, dict[str, str]] = field(default_factory=dict)
    source: str = "defaults"

    def resolve(self, role: str, dry_run: bool = False) -> RoleRoute:
        """Resolve a role to a concrete provider/model, applying env overrides."""
        if role not in ROLES:
            raise ValueError(f"Unknown role: {role!r}. Known roles: {', '.join(ROLES)}")
        if dry_run:
            return RoleRoute(provider="mock", model="mock")
        entry = dict(self.roles.get(role) or DEFAULT_CONFIG["roles"][role])
        if os.getenv("MINER_PROVIDER"):
            entry["provider"] = os.environ["MINER_PROVIDER"]
        if os.getenv("MINER_MODEL"):
            entry["model"] = os.environ["MINER_MODEL"]
        role_env = os.getenv(f"MINER_MODEL_{role.upper()}")
        if role_env:
            entry["model"] = role_env
        provider = entry["provider"]
        if provider == "mock":
            return RoleRoute(provider="mock", model=entry.get("model", "mock"))
        pconf = self.providers.get(provider)
        if pconf is None:
            raise ValueError(
                f"Provider {provider!r} (role {role!r}) is not defined in [providers]."
            )
        return RoleRoute(
            provider=provider,
            model=entry["model"],
            base_url=str(pconf.get("base_url", "")),
            api_key_env=str(pconf.get("api_key_env", "")),
        )

    def routing_table(self, dry_run: bool = False) -> dict[str, str]:
        """Human-readable role → provider/model map (for manifests/server_info)."""
        return {
            role: f"{self.resolve(role, dry_run).provider}/{self.resolve(role, dry_run).model}"
            for role in ROLES
        }


def load_config(workspace: Path | None = None, profile: str = "default") -> MinerConfig:
    """Load miner.toml (workspace first, then user config dir) plus a profile.

    A ``[profiles.<name>.roles]`` table overrides ``[roles]`` per role.
    """
    candidates: list[Path] = []
    if workspace is not None:
        candidates.append(workspace / "miner.toml")
    candidates.append(Path.home() / ".config" / "automation-miner" / "miner.toml")

    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        return MinerConfig(
            providers=dict(DEFAULT_CONFIG["providers"]),
            roles=dict(DEFAULT_CONFIG["roles"]),
        )

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    providers = {**DEFAULT_CONFIG["providers"], **data.get("providers", {})}
    roles = {**DEFAULT_CONFIG["roles"], **data.get("roles", {})}
    profile_roles = data.get("profiles", {}).get(profile, {}).get("roles", {})
    roles.update(profile_roles)
    return MinerConfig(providers=providers, roles=roles, source=str(path))
