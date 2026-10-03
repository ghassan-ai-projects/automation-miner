"""Deterministic ICE math, coherence validation, constraint policy, ranking.

Everything here is pure code. The LLM proposes ICE factors with rationale; these
functions decide what the portfolio actually looks like.

Three defects this module replaces:

* **The validation layer did nothing.** ``calibrate()`` clamped factors to 1-5,
  but ``ICEScore`` already declares ``Field(ge=1, le=5)``, so pydantic rejected
  out-of-range values first and the clamp was unreachable. "LLM proposes, code
  validates" validated nothing. Real validation now cross-checks the factors
  against the draft's own effort/impact/risk estimates.
* **Two divergent constraint parsers.** ``rank()`` used regex policy parsing
  while ``apply_constraint_overrides()`` used its own substring checks, so
  ``budget: zero``, ``no budget``, ``agent_limit: 3``, ``team:3`` and
  ``timeline: tight`` all silently reshaped the portfolio while recording no
  override at all. There is now one parser.
* **Ranking destroyed paid-for work.** Hard filters dropped opportunities that
  had been drafted, critiqued, refined and scored — ``urgent`` cut a
  six-opportunity pool to three with no record of the rest. Filtered
  opportunities are now retained and carry their exclusion reason.

Adjustment policy: incoherence is resolved *downward only*. A score is capped
when the model was more optimistic than the draft supports, and merely flagged
when it was more pessimistic. Nothing here can inflate an ICE score.
"""

from __future__ import annotations

from automation_miner.scoring.ice import (
    SCORE_MAX,
    SCORE_MIN,
    apply_constraint_overrides,
    compute_ice,
    apply_confidence_cap,
    artifact_type_for,
    evidence_confidence_cap,
    validate_coherence,
    validate_score,
)
from automation_miner.scoring.policy import (
    URGENT_PORTFOLIO_SIZE,
    ConstraintPolicy,
    context_policy,
    parse_constraint_policy,
)
from automation_miner.scoring.reading import read_policy, verify_reading
from automation_miner.scoring.portfolio import (
    FILTER_KEYS,
    active_filters,
    apply_portfolio_policy,
    ease_first,
    filtered,
    portfolio_stats,
    published,
    sort_key,
    strategic_filters,
    tier_for,
)

__all__ = [
    "FILTER_KEYS",
    "SCORE_MAX",
    "SCORE_MIN",
    "URGENT_PORTFOLIO_SIZE",
    "ConstraintPolicy",
    "context_policy",
    "active_filters",
    "apply_constraint_overrides",
    "apply_portfolio_policy",
    "compute_ice",
    "ease_first",
    "apply_confidence_cap",
    "artifact_type_for",
    "evidence_confidence_cap",
    "filtered",
    "parse_constraint_policy",
    "read_policy",
    "verify_reading",
    "portfolio_stats",
    "published",
    "sort_key",
    "strategic_filters",
    "tier_for",
    "validate_coherence",
    "validate_score",
]
