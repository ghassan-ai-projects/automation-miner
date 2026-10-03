"""Thread-safe per-role call and token accounting."""

from __future__ import annotations

import threading

from automation_miner.schemas import RoleUsage, RunUsage


_COUNTED = frozenset(
    {
        "logical_calls", "attempts", "retries", "failures",
        "prompt_tokens", "completion_tokens", "attempted_tokens",
    }
)


class UsageTracker:
    """Thread-safe per-role call and token accounting."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._roles: dict[str, RoleUsage] = {}

    def record(
        self, role: str, *, exact: bool | None = None, calls: int = 1, seconds: float = 0.0,
        cost_usd: float = 0.0, **counts: int,
    ) -> None:
        """Add one event's counts to ``role``.

        ``counts`` are the integer fields of :class:`RoleUsage` (prompt_tokens,
        completion_tokens, attempted_tokens, retries, failures, logical_calls,
        attempts). Tokens are exact only if every provider call was exact;
        logical-call records (``calls=0``) do not change exactness.
        """
        unknown = set(counts) - _COUNTED
        if unknown:
            raise TypeError(f"unknown usage fields: {sorted(unknown)}")
        with self._lock:
            current = self._roles.get(role, RoleUsage())
            merged = {name: getattr(current, name) + counts.get(name, 0) for name in _COUNTED}
            recorded_exact = current.exact
            if calls:
                recorded_exact = (current.exact or current.calls == 0) and bool(exact)
            self._roles[role] = RoleUsage(
                **merged, calls=current.calls + calls, exact=recorded_exact,
                seconds=round(current.seconds + seconds, 3),
                cost_usd=round(current.cost_usd + cost_usd, 6),
            )

    def snapshot(self) -> RunUsage:
        with self._lock:
            roles = dict(self._roles)
        total = RunUsage(by_role=roles)
        for usage in roles.values():
            total.calls += usage.calls
            total.logical_calls += usage.logical_calls
            total.attempts += usage.attempts
            total.retries += usage.retries
            total.cost_usd = round(total.cost_usd + usage.cost_usd, 6)
            total.failures += usage.failures
            total.prompt_tokens += usage.prompt_tokens
            total.completion_tokens += usage.completion_tokens
            total.attempted_tokens += usage.attempted_tokens
            total.seconds = round(total.seconds + usage.seconds, 3)
        total.total_tokens = total.prompt_tokens + total.completion_tokens
        total.exact = bool(roles) and all(usage.exact for usage in roles.values())
        return total
