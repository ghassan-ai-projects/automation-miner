"""Model routing configuration: miner.toml loading and role resolution.

Config is read from ``miner.toml`` in the workspace, falling back to
``~/.config/automation-miner/miner.toml``. Missing config falls back to the
built-in defaults. Env vars override everything:
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

from automation_miner.models.defaults import (
    PIPELINE_ROLES,
    EVALUATION_ROLES,
    ROLES,
    ROLE_DEFAULTS,
    REASONING_EFFORTS,
    DEFAULT_RETRY,
    DEFAULT_CONCURRENCY,
    DEFAULT_BUDGET,
    DEFAULT_CONFIG,
)

__all__ = [
    "PIPELINE_ROLES",
    "EVALUATION_ROLES",
    "ROLES",
    "ROLE_DEFAULTS",
    "REASONING_EFFORTS",
    "DEFAULT_RETRY",
    "DEFAULT_CONCURRENCY",
    "DEFAULT_BUDGET",
    "DEFAULT_CONFIG",
    "MinerConfig",
    "RetryPolicy",
    "RoleRoute",
    "load_config",
]


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff for transient provider failures."""

    attempts: int = 4
    initial_seconds: float = 1.0
    backoff: float = 2.0
    max_seconds: float = 30.0
    jitter: float = 0.25
    request_seconds: float = 300.0
    stall_seconds: float = 60.0

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> RetryPolicy:
        merged = {**DEFAULT_RETRY, **(data or {})}
        return cls(
            attempts=max(1, int(merged["attempts"])),
            initial_seconds=max(0.0, float(merged["initial_seconds"])),
            backoff=max(1.0, float(merged["backoff"])),
            max_seconds=max(0.0, float(merged["max_seconds"])),
            jitter=min(1.0, max(0.0, float(merged["jitter"]))),
            request_seconds=max(1.0, float(merged["request_seconds"])),
            stall_seconds=max(0.0, float(merged["stall_seconds"])),
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
    # OpenRouter's unified reasoning control: "off", "minimal", "low",
    # "medium", or "high". Empty leaves the provider default untouched.
    reasoning_effort: str = ""
    stream: bool = False
    # Cap on reasoning tokens (OpenRouter ``reasoning.max_tokens``); 0 = no cap.
    reasoning_max_tokens: int = 0
    # Provider routing preferences passed through as OpenRouter's ``provider``.
    routing: tuple[tuple[str, Any], ...] = ()
    # Most requests in flight at once to this provider across the process; 0 = no cap.
    max_concurrent: int = 0


@dataclass
class MinerConfig:
    """Effective configuration: routing plus pipeline tunables."""

    providers: dict[str, dict[str, Any]] = field(default_factory=dict)
    roles: dict[str, dict[str, Any]] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    readers: dict[str, Any] = field(default_factory=dict)
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    concurrency: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_CONCURRENCY))
    budget: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_BUDGET))
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
                provider="mock", model="mock", temperature=float(defaults["temperature"]),
                max_tokens=int(defaults["max_tokens"]),
            )
        entry = _with_env_overrides(role, dict(self.roles.get(role) or DEFAULT_CONFIG["roles"][role]))
        temperature = _as_float(entry.get("temperature"), float(defaults["temperature"]))
        max_tokens = _as_int(entry.get("max_tokens"), int(defaults["max_tokens"]))
        if entry["provider"] == "mock":
            return RoleRoute(
                provider="mock", model=str(entry.get("model", "mock")),
                temperature=temperature, max_tokens=max_tokens,
            )
        return self._provider_route(role, entry, temperature, max_tokens)

    def _provider(self, role: str, provider: str) -> tuple[dict[str, Any], str, str]:
        """The provider table plus its validated base_url and api_key_env."""
        pconf = self.providers.get(provider)
        if pconf is None:
            raise ValueError(f"Provider {provider!r} (role {role!r}) is not defined in [providers].")
        base_url = str(pconf.get("base_url", "")).strip()
        api_key_env = str(pconf.get("api_key_env", "")).strip()
        for value, name in ((base_url, "base_url"), (api_key_env, "api_key_env")):
            if not value:
                raise ValueError(f"Provider {provider!r} does not define {name}.")
        return pconf, base_url, api_key_env

    def _provider_route(
        self, role: str, entry: dict[str, Any], temperature: float, max_tokens: int
    ) -> RoleRoute:
        model = str(entry.get("model", "")).strip()
        if not model:
            raise ValueError(f"Role {role!r} does not define a model.")
        pconf, base_url, api_key_env = self._provider(role, entry["provider"])
        default_cap = int(ROLE_DEFAULTS[role].get("reasoning_max_tokens", 0))
        return RoleRoute(
            provider=entry["provider"], model=model, base_url=base_url, api_key_env=api_key_env,
            temperature=temperature, max_tokens=max_tokens,
            json_mode=bool(entry.get("json_mode", pconf.get("supports_json_mode", False))),
            reasoning_effort=_reasoning_effort(role, entry),
            stream=bool(entry.get("stream", pconf.get("stream", False))),
            reasoning_max_tokens=max(0, _as_int(entry.get("reasoning_max_tokens"), default_cap)),
            routing=tuple(sorted(dict(pconf.get("routing", {})).items())),
            max_concurrent=max(0, _as_int(pconf.get("max_concurrent"), 0)),
        )

    def routing_table(self, dry_run: bool = False) -> dict[str, str]:
        """Human-readable role → provider/model map (for manifests/server_info)."""
        table: dict[str, str] = {}
        for role in PIPELINE_ROLES:
            route = self.resolve(role, dry_run)
            table[role] = f"{route.provider}/{route.model}"
        return table


def _with_env_overrides(role: str, entry: dict[str, Any]) -> dict[str, Any]:
    """MINER_PROVIDER / MINER_MODEL apply to every role; MINER_MODEL_<ROLE> to one."""
    if os.getenv("MINER_PROVIDER"):
        entry["provider"] = os.environ["MINER_PROVIDER"]
    if os.getenv("MINER_MODEL"):
        entry["model"] = os.environ["MINER_MODEL"]
    role_env = os.getenv(f"MINER_MODEL_{role.upper()}")
    if role_env:
        entry["model"] = role_env
    return entry


def _reasoning_effort(role: str, entry: dict[str, Any]) -> str:
    effort = str(entry.get("reasoning_effort", "")).strip().lower()
    if effort not in REASONING_EFFORTS:
        raise ValueError(
            f"Role {role!r} has reasoning_effort {effort!r}; "
            f"expected one of {', '.join(sorted(e for e in REASONING_EFFORTS if e))}."
        )
    return effort


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _config_path(workspace: Path | None) -> Path | None:
    candidates = [workspace / "miner.toml"] if workspace is not None else []
    candidates.append(Path.home() / ".config" / "automation-miner" / "miner.toml")
    return next((p for p in candidates if p.is_file()), None)


def _merged(data: dict[str, Any], overrides: dict[str, Any], table: str) -> dict[str, Any]:
    return {**data.get(table, {}), **overrides.get(table, {})}


def _providers(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Per-provider merge: a workspace that redefines [providers.openrouter]
    keeps the defaults it does not mention (such as streaming)."""
    defaults = DEFAULT_CONFIG["providers"]
    return {
        name: {**defaults.get(name, {}), **settings}
        for name, settings in {**defaults, **data.get("providers", {})}.items()
    }


def load_config(workspace: Path | None = None, profile: str = "default") -> MinerConfig:
    """Load miner.toml (workspace first, then user config dir) plus a profile.

    A ``[profiles.<name>]`` table may override ``roles``, ``context``,
    ``readers``, ``retry``, ``concurrency``, and ``budget``.
    """
    path = _config_path(workspace)
    if path is None:
        return MinerConfig(
            providers=dict(DEFAULT_CONFIG["providers"]), roles=dict(DEFAULT_CONFIG["roles"])
        )
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    profiles = data.get("profiles", {})
    if profile != "default" and profile not in profiles:
        raise ValueError(f"Profile {profile!r} is not defined in {path}.")
    overrides = profiles.get(profile, {}) if profile != "default" else {}
    return MinerConfig(
        providers=_providers(data),
        roles={**DEFAULT_CONFIG["roles"], **_merged(data, overrides, "roles")},
        context=_merged(data, overrides, "context"),
        readers=_merged(data, overrides, "readers"),
        retry=RetryPolicy.from_dict(_merged(data, overrides, "retry")),
        concurrency={**DEFAULT_CONCURRENCY, **_merged(data, overrides, "concurrency")},
        budget={**DEFAULT_BUDGET, **_merged(data, overrides, "budget")},
        source=str(path),
    )
