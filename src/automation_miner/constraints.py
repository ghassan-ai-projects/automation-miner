"""Dynamic run constraints shared by CLI, Python, MCP, and prompts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
MAX_PARAMS = 32
MAX_VALUE_CHARS = 500
RECOGNIZED_POLICY_PARAMS = frozenset(
    {
        "budget",
        "no_coding",
        "compliance",
        "urgent",
        "no_infrastructure",
        "mature_stack",
        "eu_data_residency",
        "human_payment_approval",
        "timeline",
        "agent_limit",
        "max_agents",
    }
)


def _checked(raw_key: object, raw_value: object) -> tuple[str, str]:
    key = str(raw_key).strip()
    if not _KEY.fullmatch(key):
        raise ValueError(
            f"invalid constraint parameter {key!r}; use letters, numbers, '.', '_', or '-'"
        )
    value = str(raw_value).strip()
    if not value:
        raise ValueError(f"constraint parameter {key!r} must not be empty")
    if len(value) > MAX_VALUE_CHARS:
        raise ValueError(f"constraint parameter {key!r} exceeds {MAX_VALUE_CHARS} characters")
    return key, value


def normalize_constraint_params(params: Mapping[str, Any] | None) -> dict[str, str]:
    """Validate free-form constraint parameters without hardcoding their meaning."""
    if not params:
        return {}
    if len(params) > MAX_PARAMS:
        raise ValueError(f"at most {MAX_PARAMS} constraint parameters are allowed")
    normalized: dict[str, str] = {}
    spellings: dict[str, str] = {}
    for raw_key, raw_value in params.items():
        key, value = _checked(raw_key, raw_value)
        if key.casefold() in spellings:
            raise ValueError(
                f"constraint parameter {key!r} duplicates "
                f"{spellings[key.casefold()]!r} case-insensitively"
            )
        spellings[key.casefold()] = key
        normalized[key] = value
    return normalized


def parse_constraint_args(values: list[str] | None) -> dict[str, str]:
    """Parse repeatable CLI ``--constraint key=value`` arguments."""
    parsed: dict[str, str] = {}
    for value in values or []:
        if "=" not in value:
            raise ValueError(f"constraint parameter {value!r} must use key=value")
        key, item = value.split("=", 1)
        key = key.strip()
        if key in parsed:
            raise ValueError(f"constraint parameter {key!r} was provided more than once")
        parsed[key] = item
    return normalize_constraint_params(parsed)


def render_constraints(text: str, params: Mapping[str, str] | None = None) -> str:
    """Render constraints as an open-ended prompt contract."""
    parts: list[str] = []
    if text.strip():
        parts.append(text.strip())
    normalized = normalize_constraint_params(params)
    if normalized:
        binding = [(key, value) for key, value in normalized.items() if key.casefold() in RECOGNIZED_POLICY_PARAMS]
        advisory = [(key, value) for key, value in normalized.items() if key.casefold() not in RECOGNIZED_POLICY_PARAMS]
        if binding:
            lines = ["Recognized constraint parameters (binding policy):"]
            lines += [f"- {key} = {value}" for key, value in binding]
            parts.append("\n".join(lines))
        if advisory:
            lines = ["Unknown constraint parameters (advisory context only):"]
            lines += [f"- {key} = {value}" for key, value in advisory]
            parts.append("\n".join(lines))
    return "\n\n".join(parts)
