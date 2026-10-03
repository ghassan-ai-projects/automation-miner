"""Constraint policy: one deterministic parser for prose and typed parameters.

The single source of truth for both score overrides and portfolio filtering.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

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

# Legacy free-form syntax. Structured parameters (--constraint key=value)
# override every one of these.
PROSE_PATTERNS: dict[str, str] = {
    "low_budget": r"(?:\bbudget\s*[:=]?\s*(?:low|zero|none)\b|\bno\s+budget\b)",
    "no_coding": r"\bno[- ]?(?:custom\s+dev|coding)\b",
    "compliance": r"\b(?:compliance|regulated)\b",
    "urgent": r"\b(?:urgent|1\s+week|one\s+week|tight\s+timeline)\b|\btimeline\s*[:=]?\s*tight\b",
    "no_infrastructure": r"\bno\s+(?:existing\s+)?infrastructure\b",
    "mature_stack": r"\b(?:existing\s+)?mature\s+stack\b",
    "eu_data_residency": (
        r"\beu[- ](?:hosted|only)\b|\beu\s+data\s+residen|"
        r"\bdata.{0,30}(?:remain|stay).{0,15}\beu\b"
    ),
    "human_payment_approval": (
        r"\bpayment(?:s)?\b.{0,30}\b(?:human\s+approval|must|require).{0,20}\bapprov"
    ),
}

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

_BOUNDARIES = re.compile(r"[.;,\n]|\b(?:but|however|except|although|unless)\b")
_NEGATED_BEFORE = re.compile(r"(?:not|no|without|never|isn't|aren't)\s+(?:\w+\s+){0,2}$")
_NEGATED_INSIDE = re.compile(
    r"\b(?:do|does|did|is|are|was|were|will|can)\s+not\b|"
    r"\b(?:don't|doesn't|didn't|isn't|aren't|wasn't|weren't|won't|can't)\b"
)
_NEGATED_AFTER = re.compile(
    r"\s+(?:(?:is|are|was|were|do|does|did|will|can)\s+)?(?:not|isn't|aren't|never)\b"
)
_DISMISSED_AFTER = re.compile(
    r"\s+(?:concern|concerns|issue|issues|problem|problems|restriction|"
    r"restrictions|limitation|limitations)\b"
)
_TRUE = {"1", "true", "yes", "on", "required", "heavy", "strict", "tight"}
_FALSE = {"0", "false", "no", "off", "none", "unset", "disabled"}
RECOGNIZED = set(FLAGS) - {"low_budget"} | {"budget", "timeline", "agent_limit", "max_agents"}


@dataclass(frozen=True)
class ConstraintPolicy:
    """Deterministic policy flags parsed from the documented free-form syntax.

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

    @property
    def active(self) -> bool:
        return any(getattr(self, flag) for flag in FLAGS) or self.agent_limit is not None

    def describe(self) -> list[str]:
        """Human-readable list of every policy in force, for run notes."""
        notes = [note for flag, note in FLAG_NOTES.items() if getattr(self, flag)]
        if self.agent_limit is not None:
            notes.append(f"agent limit {self.agent_limit}: larger topologies excluded")
        notes.extend(self.warnings)
        if self.advisory_params:
            names = ", ".join(self.advisory_params)
            notes.append(f"advisory constraint parameters (not hard policy): {names}")
        return notes


def _negated(text: str, match: re.Match[str]) -> bool:
    """Whether a matched phrase is negated or dismissed within its own clause."""
    prior = list(_BOUNDARIES.finditer(text, 0, match.start()))
    clause_start = prior[-1].end() if prior else 0
    following = _BOUNDARIES.search(text, match.end())
    clause_end = following.start() if following else len(text)
    after = text[match.end() : clause_end]
    return bool(
        _NEGATED_BEFORE.search(text[clause_start : match.start()])
        or _NEGATED_INSIDE.search(match.group(0))
        or _NEGATED_AFTER.match(after)
        or _DISMISSED_AFTER.match(after)
    )


def _active_phrase(text: str, pattern: str) -> bool:
    """Match a policy phrase while respecting clause-bounded negation."""
    return any(not _negated(text, match) for match in re.finditer(pattern, text))


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


def _agent_limit(text: str, structured: dict[str, str], warnings: list[str]) -> int | None:
    match = re.search(r"agent[\s_-]*limit\s*[:=]?\s*(\d+)", text)
    limit = int(match.group(1)) if match else None
    if limit is None and re.search(r"agent[\s_-]*limit", text):
        limit = 1
    if limit is None and (
        "small team" in text or re.search(r"team\s*[:=]?\s*([1-3])(?:\D|$)", text)
    ):
        limit = 2
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
    return limit


def parse_constraint_policy(
    constraints: str, params: Mapping[str, str] | None = None
) -> ConstraintPolicy:
    """Build one deterministic policy from prose plus typed parameters.

    Recognized structured parameters override legacy prose. Unknown parameters
    remain prompt context and are explicitly reported as advisory; they never
    become execution filters by accident.
    """
    text = constraints.casefold()
    warnings: list[str] = []
    structured = _structured(params, warnings)
    values = {flag: _active_phrase(text, PROSE_PATTERNS[flag]) for flag in FLAGS}
    _apply_structured(values, structured, warnings)
    agent_limit = _agent_limit(text, structured, warnings)
    advisory = tuple(sorted(key for key in structured if key not in RECOGNIZED))
    return ConstraintPolicy(
        **values,
        agent_limit=agent_limit,
        raw=constraints,
        warnings=tuple(warnings),
        advisory_params=advisory,
    )
