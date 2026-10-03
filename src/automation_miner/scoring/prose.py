"""Keyword reading of free-text constraints: the fallback and the cross-check.

Run constraints are read by a model into typed, quote-verified policy flags
(``policy_reading``). These clause-aware patterns remain for two jobs: the
fallback when no reading exists (legacy runs, a failed reader call), and a
cross-check that warns when a keyword fires but the reading did not apply it,
so an ambiguous constraint is surfaced instead of silently decided.
"""

from __future__ import annotations

import re

# Structured parameters (--constraint key=value) override every one of these.
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


def _active_match(text: str, pattern: str) -> str:
    """The first policy phrase not negated within its clause, or an empty string."""
    for match in re.finditer(pattern, text):
        if not _negated(text, match):
            return match.group(0)
    return ""


def prose_matches(text: str) -> dict[str, str]:
    """Flag → matched phrase for every flag the keyword patterns activate."""
    folded = text.casefold()
    found = {flag: _active_match(folded, pattern) for flag, pattern in PROSE_PATTERNS.items()}
    return {flag: phrase for flag, phrase in found.items() if phrase}


def prose_agent_limit(text: str) -> int | None:
    """An agent cap stated in prose: an explicit number, else 1, else 2 for a small team."""
    folded = text.casefold()
    match = re.search(r"agent[\s_-]*limit\s*[:=]?\s*(\d+)", folded)
    if match:
        return int(match.group(1))
    if re.search(r"agent[\s_-]*limit", folded):
        return 1
    if "small team" in folded or re.search(r"team\s*[:=]?\s*([1-3])(?:\D|$)", folded):
        return 2
    return None
