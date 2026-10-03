"""Constraint policy: one deterministic resolver for every source of constraints.

The single source of truth for both score overrides and portfolio filtering.
Precedence, highest first:

1. structured parameters (``--constraint key=value``, MCP ``constraint_params``);
2. the run's verified policy reading of the constraint text (``policy_reading``);
3. the keyword patterns in :mod:`prose`, only when no reading exists.

Every active flag records where it came from, so a report can show *why* a
filter fired instead of leaving the operator to reverse-engineer a regex.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass

from automation_miner.schemas import ContextPacket, PolicyClause, PolicyReading
from automation_miner.scoring.prose import prose_agent_limit, prose_matches

URGENT_PORTFOLIO_SIZE = 3


FLAGS = (
    "low_budget",
    "no_coding",
    "compliance",
    "urgent",
    "no_infrastructure",
    "mature_stack",
    "eu_data_residency",
    "human_payment_approval",
)

FLAG_NOTES: dict[str, str] = {
    "low_budget": "budget low/zero: only Ease >= 4 opportunities are eligible",
    "no_coding": "no-coding: Ease capped at 4 (configuration-level only)",
    "compliance": "compliance: risk capped at Medium, high-risk items excluded",
    "urgent": f"urgent/tight timeline: top {URGENT_PORTFOLIO_SIZE} by Ease then ICE",
    "no_infrastructure": "no existing infrastructure: Document and Knowledge layers only",
    "mature_stack": "existing mature stack: Communication, Decision and Monitoring layers only",
    "eu_data_residency": "EU data residency: unverified external data channels are excluded",
    "human_payment_approval": "payments: explicit human approval is mandatory",
}

_TRUE = {"1", "true", "yes", "on", "required", "heavy", "strict", "tight"}
_FALSE = {"0", "false", "no", "off", "none", "unset", "disabled"}
RECOGNIZED = set(FLAGS) - {"low_budget"} | {"budget", "timeline", "agent_limit", "max_agents"}


# The structured parameter that sets a flag, when it is not the flag's own name.
_PARAM_FOR = {"low_budget": "budget", "urgent": "timeline"}
_ENFORCE_HINT = {"low_budget": "budget=low", "urgent": "timeline=tight"}


@dataclass(frozen=True)
class ConstraintPolicy:
    """Deterministic policy flags resolved from parameters and constraint text.

    The single source of truth for both score overrides and portfolio filtering.
    """

    low_budget: bool = False
    no_coding: bool = False
    compliance: bool = False
    urgent: bool = False
    no_infrastructure: bool = False
    mature_stack: bool = False
    eu_data_residency: bool = False
    human_payment_approval: bool = False
    agent_limit: int | None = None
    raw: str = ""
    warnings: tuple[str, ...] = ()
    advisory_params: tuple[str, ...] = ()
    sources: tuple[tuple[str, str], ...] = ()

    @property
    def active(self) -> bool:
        return any(getattr(self, flag) for flag in FLAGS) or self.agent_limit is not None

    def source(self, flag: str) -> str:
        return dict(self.sources).get(flag, "")

    def describe(self) -> list[str]:
        """Human-readable list of every policy in force and its origin, for run notes."""
        notes = [
            note + (f" ({self.source(flag)})" if self.source(flag) else "")
            for flag, note in FLAG_NOTES.items() if getattr(self, flag)
        ]
        if self.agent_limit is not None:
            origin = f" ({self.source('agent_limit')})" if self.source("agent_limit") else ""
            notes.append(f"agent limit {self.agent_limit}: larger topologies excluded{origin}")
        notes.extend(self.warnings)
        if self.advisory_params:
            names = ", ".join(self.advisory_params)
            notes.append(f"advisory constraint parameters (not hard policy): {names}")
        return notes


def _param_bool(params: Mapping[str, str], key: str) -> bool | None:
    value = params.get(key)
    normalized = value.casefold().strip() if value is not None else None
    if normalized in _TRUE:
        return True
    if normalized in _FALSE:
        return False
    return None


def _structured(params: Mapping[str, str] | None, warnings: list[str]) -> dict[str, str]:
    """Case-insensitive parameters; the first spelling of a duplicate wins."""
    structured: dict[str, str] = {}
    spellings: dict[str, str] = {}
    for raw_key, raw_value in (params or {}).items():
        spelling = str(raw_key).strip()
        key = spelling.casefold()
        if key in structured:
            warnings.append(
                f"duplicate structured parameter {spelling!r}; keeping {spellings[key]!r}"
            )
            continue
        spellings[key] = spelling
        structured[key] = str(raw_value).strip()
    return structured


def _apply_structured(
    values: dict[str, bool], structured: dict[str, str], warnings: list[str]
) -> None:
    """Structured budget, boolean flags, and timeline override the prose."""
    budget = structured.get("budget")
    if budget is not None:
        if budget.casefold() in {"low", "zero", "none"} | {"medium", "high"}:
            values["low_budget"] = budget.casefold() in {"low", "zero", "none"}
        else:
            warnings.append(f"unrecognized structured budget {budget!r}; ignored for hard policy")
    for flag in FLAGS[1:]:
        if flag in structured:
            value = _param_bool(structured, flag)
            if value is None:
                warnings.append(f"unrecognized structured {flag} value; ignored for hard policy")
            else:
                values[flag] = value
    timeline = structured.get("timeline")
    if timeline is not None:
        if timeline.casefold() in {"tight", "urgent", "asap", "normal", "loose", "flexible"}:
            values["urgent"] = timeline.casefold() in {"tight", "urgent", "asap"}
        else:
            warnings.append(f"unrecognized structured timeline {timeline!r}; ignored")


def _structured_limit(
    structured: dict[str, str], warnings: list[str], fallback: int | None
) -> int | None:
    for key in ("agent_limit", "max_agents"):
        if key not in structured:
            continue
        try:
            candidate = int(structured[key])
        except ValueError:
            warnings.append(f"unrecognized structured {key} value; ignored for hard policy")
            continue
        if candidate >= 1:
            return candidate
        warnings.append(f"structured {key} must be at least 1; ignored for hard policy")
    return fallback


def _keyword_values(text: str) -> tuple[dict[str, bool], int | None, dict[str, str]]:
    matches = prose_matches(text)
    sources = {flag: f"keyword “{phrase}”" for flag, phrase in matches.items()}
    limit = prose_agent_limit(text)
    if limit is not None:
        sources["agent_limit"] = "keyword"
    return {flag: flag in matches for flag in FLAGS}, limit, sources


def _read_values(
    text: str, reading: PolicyReading, warnings: list[str]
) -> tuple[dict[str, bool], int | None, dict[str, str]]:
    """Flags from the verified reading; a keyword it did not apply becomes a warning."""
    quotes: dict[str, PolicyClause] = {clause.flag: clause for clause in reading.clauses}
    sources: dict[str, str] = {flag: f"from “{clause.quote}”" for flag, clause in quotes.items()}
    limit_clause = quotes.get("agent_limit")
    limit = (limit_clause.limit or 1) if limit_clause else None
    for flag, phrase in prose_matches(text).items():
        if flag not in quotes:
            hint = _ENFORCE_HINT.get(flag, f"{flag}=true")
            warnings.append(
                f"constraints mention “{phrase}” but it was not read as binding {flag}; "
                f"pass --constraint {hint} to enforce it"
            )
    return {flag: flag in quotes for flag in FLAGS}, limit, sources


def _param_sources(structured: dict[str, str]) -> dict[str, str]:
    sources = {}
    for flag in (*FLAGS, "agent_limit", "max_agents"):
        key = _PARAM_FOR.get(flag, flag)
        if key in structured:
            sources["agent_limit" if flag == "max_agents" else flag] = (
                f"parameter {key}={structured[key]}"
            )
    return sources


def parse_constraint_policy(
    constraints: str, params: Mapping[str, str] | None = None,
    reading: PolicyReading | None = None,
) -> ConstraintPolicy:
    """Build one deterministic policy from typed parameters and the constraint text.

    Recognized structured parameters override the text. Unknown parameters
    remain prompt context and are explicitly reported as advisory; they never
    become execution filters by accident.
    """
    warnings: list[str] = []
    structured = _structured(params, warnings)
    if reading is None:
        values, limit, sources = _keyword_values(constraints)
    else:
        values, limit, sources = _read_values(constraints, reading, warnings)
    _apply_structured(values, structured, warnings)
    sources.update(_param_sources(structured))
    return ConstraintPolicy(
        **values,
        agent_limit=_structured_limit(structured, warnings, limit),
        raw=constraints,
        warnings=tuple(warnings),
        advisory_params=tuple(sorted(key for key in structured if key not in RECOGNIZED)),
        sources=tuple(sorted(sources.items())),
    )


def context_policy(context: ContextPacket) -> ConstraintPolicy:
    """The policy a run resolved, including warnings from reading its constraints."""
    policy = parse_constraint_policy(
        context.raw_constraints, context.constraint_params, context.policy_reading
    )
    warnings = (*context.policy_warnings, *policy.warnings)
    return dataclasses.replace(policy, warnings=warnings)
