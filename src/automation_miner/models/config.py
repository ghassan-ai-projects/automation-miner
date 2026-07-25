"""Model routing configuration: miner.toml loading and role resolution.

Config is read from ``miner.toml`` in the workspace, falling back to
``~/.config/automation-miner/miner.toml``. Missing config falls back to the
built-in defaults from DESIGN.md. Env vars override everything:
``MINER_PROVIDER`` (all roles), ``MINER_MODEL`` (all roles),
``MINER_MODEL_<ROLE>`` (one role).

Beyond routing, this owns the tunables that used to be hardcoded in the HTTP
client: sampling temperature and ``max_tokens`` per role, retry policy, stage
concurrency, and the reader/context tables. ``max_tokens`` mattered most — one
value of 8192 was applied to every role, and the drafter emits a full
``OpportunityDraft`` with two tables, so a truncated completion became
unparseable JSON, burned three retries, and failed the run.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROLES = ("mapper", "layer_analyst", "drafter", "critic", "refiner", "scorer")

# Per-role sampling and output limits. Drafting and refining need room for a
# complete draft; scoring returns a handful of fields and should be near-greedy.
ROLE_DEFAULTS: dict[str, dict[str, Any]] = {
    "mapper": {"temperature": 0.2, "max_tokens": 6_000},
    "layer_analyst": {"temperature": 0.3, "max_tokens": 8_000},
    "drafter": {"temperature": 0.4, "max_tokens": 16_000},
    "critic": {"temperature": 0.2, "max_tokens": 4_000},
    "refiner": {"temperature": 0.3, "max_tokens": 16_000},
    "scorer": {"temperature": 0.1, "max_tokens": 2_000},
}

DEFAULT_RETRY: dict[str, Any] = {
    "attempts": 4,
    "initial_seconds": 1.0,
    "backoff": 2.0,
    "max_seconds": 30.0,
    "jitter": 0.25,
}

DEFAULT_CONCURRENCY: dict[str, Any] = {
    "critique": 4,
    "score": 4,
}

DEFAULT_CONFIG: dict[str, Any] = {
    "providers": {
        "openrouter": {
            "base_url": "https://openrouter.ai/api/v1",
            "api_key_env": "OPENROUTER_API_KEY",
            "supports_json_mode": True,
        },
        "gemini": {
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "api_key_env": "GOOGLE_API_KEY",
            "supports_json_mode": True,
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
class RetryPolicy:
    """Exponential backoff for transient provider failures."""

    attempts: int = 4
    initial_seconds: float = 1.0
    backoff: float = 2.0
    max_seconds: float = 30.0
    jitter: float = 0.25

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> RetryPolicy:
        merged = {**DEFAULT_RETRY, **(data or {})}
        return cls(
            attempts=max(1, int(merged["attempts"])),
            initial_seconds=max(0.0, float(merged["initial_seconds"])),
            backoff=max(1.0, float(merged["backoff"])),
            max_seconds=max(0.0, float(merged["max_seconds"])),
            jitter=min(1.0, max(0.0, float(merged["jitter"]))),
        )

    def delay_for(self, attempt: int) -> float:
        """Delay before retry number ``attempt`` (1-based)."""
        raw = self.initial_seconds * (self.backoff ** max(0, attempt - 1))
        return min(self.max_seconds, raw)


@dataclass(frozen=True)
class RoleRoute:
    """Resolved provider + model + sampling settings for one pipeline role."""

    provider: str
    model: str
    base_url: str = ""
    api_key_env: str = ""
    temperature: float = 0.3
    max_tokens: int = 8_000
    json_mode: bool = False


@dataclass
class MinerConfig:
    """Effective configuration: routing plus pipeline tunables."""

    providers: dict[str, dict[str, Any]] = field(default_factory=dict)
    roles: dict[str, dict[str, Any]] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    readers: dict[str, Any] = field(default_factory=dict)
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    concurrency: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_CONCURRENCY))
    source: str = "defaults"

    def workers_for(self, stage: str) -> int:
        """Thread count for a parallelizable stage (minimum 1)."""
        try:
            return max(1, int(self.concurrency.get(stage, DEFAULT_CONCURRENCY.get(stage, 1))))
        except (TypeError, ValueError):
            return 1

    def resolve(self, role: str, dry_run: bool = False) -> RoleRoute:
        """Resolve a role to a concrete provider/model, applying env overrides."""
        if role not in ROLES:
            raise ValueError(f"Unknown role: {role!r}. Known roles: {', '.join(ROLES)}")
        defaults = ROLE_DEFAULTS[role]
        if dry_run:
            return RoleRoute(
                provider="mock",
                model="mock",
                temperature=float(defaults["temperature"]),
                max_tokens=int(defaults["max_tokens"]),
            )
        entry = dict(self.roles.get(role) or DEFAULT_CONFIG["roles"][role])
        if os.getenv("MINER_PROVIDER"):
            entry["provider"] = os.environ["MINER_PROVIDER"]
        if os.getenv("MINER_MODEL"):
            entry["model"] = os.environ["MINER_MODEL"]
        role_env = os.getenv(f"MINER_MODEL_{role.upper()}")
        if role_env:
            entry["model"] = role_env

        temperature = _as_float(entry.get("temperature"), float(defaults["temperature"]))
        max_tokens = _as_int(entry.get("max_tokens"), int(defaults["max_tokens"]))

        provider = entry["provider"]
        if provider == "mock":
            return RoleRoute(
                provider="mock",
                model=str(entry.get("model", "mock")),
                temperature=temperature,
                max_tokens=max_tokens,
            )
        model = str(entry.get("model", "")).strip()
        if not model:
            raise ValueError(f"Role {role!r} does not define a model.")
        pconf = self.providers.get(provider)
        if pconf is None:
            raise ValueError(
                f"Provider {provider!r} (role {role!r}) is not defined in [providers]."
            )
        base_url = str(pconf.get("base_url", "")).strip()
        api_key_env = str(pconf.get("api_key_env", "")).strip()
        if not base_url:
            raise ValueError(f"Provider {provider!r} does not define base_url.")
        if not api_key_env:
            raise ValueError(f"Provider {provider!r} does not define api_key_env.")
        json_mode = bool(entry.get("json_mode", pconf.get("supports_json_mode", False)))
        return RoleRoute(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key_env=api_key_env,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
        )

    def routing_table(self, dry_run: bool = False) -> dict[str, str]:
        """Human-readable role → provider/model map (for manifests/server_info)."""
        table: dict[str, str] = {}
        for role in ROLES:
            route = self.resolve(role, dry_run)
            table[role] = f"{route.provider}/{route.model}"
        return table


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def load_config(workspace: Path | None = None, profile: str = "default") -> MinerConfig:
    """Load miner.toml (workspace first, then user config dir) plus a profile.

    A ``[profiles.<name>]`` table may override ``roles``, ``context``,
    ``readers``, ``retry``, and ``concurrency``.
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
    profiles = data.get("profiles", {})
    if profile != "default" and profile not in profiles:
        raise ValueError(f"Profile {profile!r} is not defined in {path}.")
    overrides = profiles.get(profile, {}) if profile != "default" else {}

    providers = {**DEFAULT_CONFIG["providers"], **data.get("providers", {})}
    roles = {**DEFAULT_CONFIG["roles"], **data.get("roles", {})}
    roles.update(overrides.get("roles", {}))

    context = {**data.get("context", {}), **overrides.get("context", {})}
    readers = {**data.get("readers", {}), **overrides.get("readers", {})}
    retry = {**data.get("retry", {}), **overrides.get("retry", {})}
    concurrency = {
        **DEFAULT_CONCURRENCY,
        **data.get("concurrency", {}),
        **overrides.get("concurrency", {}),
    }
    return MinerConfig(
        providers=providers,
        roles=roles,
        context=context,
        readers=readers,
        retry=RetryPolicy.from_dict(retry),
        concurrency=concurrency,
        source=str(path),
    )
