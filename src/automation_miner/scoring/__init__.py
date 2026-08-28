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

import re
import statistics
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Iterable

from automation_miner.schemas import (
    PUBLICATION_QUALITY_FLOOR,
    Eligibility,
    ICEScore,
    Layer,
    Level,
    Opportunity,
    OpportunityDraft,
    PortfolioStats,
    Tier,
)

SCORE_MIN = 1
SCORE_MAX = 5
URGENT_PORTFOLIO_SIZE = 3
FILTER_KEYS = ("low_hanging", "high_value", "vision")


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
        return bool(
            self.low_budget
            or self.no_coding
            or self.compliance
            or self.urgent
            or self.no_infrastructure
            or self.mature_stack
            or self.eu_data_residency
            or self.human_payment_approval
            or self.agent_limit is not None
        )

    def describe(self) -> list[str]:
        """Human-readable list of every policy in force, for run notes."""
        notes: list[str] = []
        if self.low_budget:
            notes.append("budget low/zero: only Ease >= 4 opportunities are eligible")
        if self.no_coding:
            notes.append("no-coding: Ease capped at 4 (configuration-level only)")
        if self.compliance:
            notes.append("compliance: risk capped at Medium, high-risk items excluded")
        if self.urgent:
            notes.append(
                f"urgent/tight timeline: top {URGENT_PORTFOLIO_SIZE} by Ease then ICE"
            )
        if self.no_infrastructure:
            notes.append("no existing infrastructure: Document and Knowledge layers only")
        if self.mature_stack:
            notes.append(
                "existing mature stack: Communication, Decision and Monitoring layers only"
            )
        if self.eu_data_residency:
            notes.append(
                "EU data residency: unverified external data channels are excluded"
            )
        if self.human_payment_approval:
            notes.append("payments: explicit human approval is mandatory")
        if self.agent_limit is not None:
            notes.append(f"agent limit {self.agent_limit}: larger topologies excluded")
        notes.extend(self.warnings)
        if self.advisory_params:
            names = ", ".join(self.advisory_params)
            notes.append(f"advisory constraint parameters (not hard policy): {names}")
        return notes


def _active_phrase(text: str, pattern: str) -> bool:
    """Match a policy phrase while respecting clause-bounded negation."""
    boundaries = re.compile(r"[.;,\n]|\b(?:but|however|except|although|unless)\b")
    for match in re.finditer(pattern, text):
        prior = list(boundaries.finditer(text, 0, match.start()))
        clause_start = prior[-1].end() if prior else 0
        following = boundaries.search(text, match.end())
        clause_end = following.start() if following else len(text)
        before = text[clause_start : match.start()]
        after = text[match.end() : clause_end]
        if re.search(r"(?:not|no|without|never|isn't|aren't)\s+(?:\w+\s+){0,2}$", before):
            continue
        if re.search(
            r"\b(?:do|does|did|is|are|was|were|will|can)\s+not\b|"
            r"\b(?:don't|doesn't|didn't|isn't|aren't|wasn't|weren't|won't|can't)\b",
            match.group(0),
        ):
            continue
        if re.match(
            r"\s+(?:(?:is|are|was|were|do|does|did|will|can)\s+)?"
            r"(?:not|isn't|aren't|never)\b",
            after,
        ):
            continue
        if re.match(
            r"\s+(?:concern|concerns|issue|issues|problem|problems|restriction|"
            r"restrictions|limitation|limitations)\b",
            after,
        ):
            continue
        return True
    return False


def _param_bool(params: Mapping[str, str], key: str) -> bool | None:
    value = params.get(key)
    if value is None:
        return None
    normalized = value.casefold().strip()
    if normalized in {"1", "true", "yes", "on", "required", "heavy", "strict", "tight"}:
        return True
    if normalized in {"0", "false", "no", "off", "none", "unset", "disabled"}:
        return False
    return None


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
    structured: dict[str, str] = {}
    spellings: dict[str, str] = {}
    for raw_key, raw_value in (params or {}).items():
        spelling = str(raw_key).strip()
        key = spelling.casefold()
        if key in structured:
            warnings.append(
                f"duplicate structured parameter {spelling!r}; "
                f"keeping {spellings[key]!r}"
            )
            continue
        spellings[key] = spelling
        structured[key] = str(raw_value).strip()

    low_budget = _active_phrase(
        text,
        r"(?:\bbudget\s*[:=]?\s*(?:low|zero|none)\b|\bno\s+budget\b)",
    )
    no_coding = _active_phrase(text, r"\bno[- ]?(?:custom\s+dev|coding)\b")
    compliance = _active_phrase(text, r"\b(?:compliance|regulated)\b")
    urgent = _active_phrase(
        text,
        r"\b(?:urgent|1\s+week|one\s+week|tight\s+timeline)\b|"
        r"\btimeline\s*[:=]?\s*tight\b",
    )
    no_infrastructure = _active_phrase(text, r"\bno\s+(?:existing\s+)?infrastructure\b")
    mature_stack = _active_phrase(text, r"\b(?:existing\s+)?mature\s+stack\b")
    eu_data_residency = _active_phrase(
        text,
        r"\beu[- ](?:hosted|only)\b|\beu\s+data\s+residen|"
        r"\bdata.{0,30}(?:remain|stay).{0,15}\beu\b",
    )
    human_payment_approval = _active_phrase(
        text,
        r"\bpayment(?:s)?\b.{0,30}\b(?:human\s+approval|must|require).{0,20}\bapprov",
    )

    budget = structured.get("budget")
    if budget is not None:
        if budget.casefold() in {"low", "zero", "none"}:
            low_budget = True
        elif budget.casefold() in {"medium", "high"}:
            low_budget = False
        else:
            warnings.append(f"unrecognized structured budget {budget!r}; ignored for hard policy")

    bool_keys = {
        "no_coding": "no_coding",
        "compliance": "compliance",
        "urgent": "urgent",
        "no_infrastructure": "no_infrastructure",
        "mature_stack": "mature_stack",
        "eu_data_residency": "eu_data_residency",
        "human_payment_approval": "human_payment_approval",
    }
    values = {
        "low_budget": low_budget,
        "no_coding": no_coding,
        "compliance": compliance,
        "urgent": urgent,
        "no_infrastructure": no_infrastructure,
        "mature_stack": mature_stack,
        "eu_data_residency": eu_data_residency,
        "human_payment_approval": human_payment_approval,
    }
    for param_key, policy_key in bool_keys.items():
        if param_key in structured:
            value = _param_bool(structured, param_key)
            if value is None:
                warnings.append(f"unrecognized structured {param_key} value; ignored for hard policy")
            else:
                values[policy_key] = value
    if "timeline" in structured:
        value = structured["timeline"].casefold()
        if value in {"tight", "urgent", "asap"}:
            values["urgent"] = True
        elif value in {"normal", "loose", "flexible"}:
            values["urgent"] = False
        else:
            warnings.append(f"unrecognized structured timeline {structured['timeline']!r}; ignored")

    agent_match = re.search(r"agent[\s_-]*limit\s*[:=]?\s*(\d+)", text)
    team_match = re.search(r"team\s*[:=]?\s*([1-3])(?:\D|$)", text)
    agent_limit = int(agent_match.group(1)) if agent_match else None
    if agent_limit is None and re.search(r"agent[\s_-]*limit", text):
        agent_limit = 1
    if agent_limit is None and ("small team" in text or team_match):
        agent_limit = 2
    for key in ("agent_limit", "max_agents"):
        if key in structured:
            try:
                candidate = int(structured[key])
            except ValueError:
                warnings.append(f"unrecognized structured {key} value; ignored for hard policy")
            else:
                if candidate < 1:
                    warnings.append(f"structured {key} must be at least 1; ignored for hard policy")
                else:
                    agent_limit = candidate
                    break
    recognized = set(bool_keys) | {"budget", "timeline", "agent_limit", "max_agents"}
    advisory = tuple(sorted(key for key in structured if key not in recognized))
    return ConstraintPolicy(
        low_budget=values["low_budget"],
        no_coding=values["no_coding"],
        compliance=values["compliance"],
        urgent=values["urgent"],
        no_infrastructure=values["no_infrastructure"],
        mature_stack=values["mature_stack"],
        eu_data_residency=values["eu_data_residency"],
        human_payment_approval=values["human_payment_approval"],
        agent_limit=agent_limit,
        raw=constraints,
        warnings=tuple(warnings),
        advisory_params=advisory,
    )


def validate_score(value: int) -> int:
    """Clamp an ICE factor into the valid 1-5 range."""
    return max(SCORE_MIN, min(SCORE_MAX, int(value)))


def compute_ice(impact: int, confidence: int, ease: int) -> int:
    """ICE = Impact x Confidence x Ease, range 1-125."""
    return validate_score(impact) * validate_score(confidence) * validate_score(ease)


# Maximum Ease that each effort level can justify (spec Phase 3 ladder:
# High effort is a 1-4 week integration, which cannot also be "already have the
# tools"). ``None`` means no ceiling.
_EFFORT_EASE_CEILING: dict[Level, int] = {Level.HIGH: 2, Level.MEDIUM: 4}
# Maximum Impact each impact_estimate can justify.
_ESTIMATE_IMPACT_CEILING: dict[Level, int] = {Level.LOW: 2, Level.MEDIUM: 4}
# High risk contradicts maximum confidence.
_RISK_CONFIDENCE_CEILING: dict[Level, int] = {Level.HIGH: 4}
# A draft with no quantified impact rows cannot support high confidence.
_UNQUANTIFIED_CONFIDENCE_CEILING = 3
# A draft citing no evidence is an inference, not a validated pattern.
_UNGROUNDED_CONFIDENCE_CEILING = 3


def validate_coherence(
    score: ICEScore, draft: OpportunityDraft, unresolved_refs: Iterable[str] = ()
) -> tuple[ICEScore, list[str]]:
    """Cross-check LLM factors against the draft's own estimates.

    Returns the adjusted score and a note per adjustment or flagged
    inconsistency. Adjustments only ever lower a factor.
    """
    notes: list[str] = []
    impact, confidence, ease = score.impact, score.confidence, score.ease

    ceiling = _EFFORT_EASE_CEILING.get(draft.effort)
    if ceiling is not None and ease > ceiling:
        notes.append(
            f"ease {ease} -> {ceiling}: incompatible with {draft.effort.value} effort"
        )
        ease = ceiling
    elif draft.effort is Level.LOW and ease <= 2:
        notes.append(
            f"flagged: ease {ease} is pessimistic for low effort (left unchanged)"
        )

    ceiling = _ESTIMATE_IMPACT_CEILING.get(draft.impact_estimate)
    if ceiling is not None and impact > ceiling:
        notes.append(
            f"impact {impact} -> {ceiling}: exceeds the draft's "
            f"{draft.impact_estimate.value} impact estimate"
        )
        impact = ceiling
    elif draft.impact_estimate is Level.HIGH and impact <= 2:
        notes.append(
            f"flagged: impact {impact} contradicts a high impact estimate (left unchanged)"
        )

    ceiling = _RISK_CONFIDENCE_CEILING.get(draft.risk_level)
    if ceiling is not None and confidence > ceiling:
        notes.append(
            f"confidence {confidence} -> {ceiling}: high risk implies residual uncertainty"
        )
        confidence = ceiling

    if not draft.impact_analysis and confidence > _UNQUANTIFIED_CONFIDENCE_CEILING:
        notes.append(
            f"confidence {confidence} -> {_UNQUANTIFIED_CONFIDENCE_CEILING}: "
            "no quantified impact rows"
        )
        confidence = _UNQUANTIFIED_CONFIDENCE_CEILING

    if not draft.evidence_refs and confidence > _UNGROUNDED_CONFIDENCE_CEILING:
        notes.append(
            f"confidence {confidence} -> {_UNGROUNDED_CONFIDENCE_CEILING}: "
            "draft cites no evidence"
        )
        confidence = _UNGROUNDED_CONFIDENCE_CEILING

    unresolved = list(unresolved_refs)
    if unresolved:
        notes.append(
            f"flagged: cited evidence ids do not exist: {', '.join(sorted(unresolved))}"
        )

    if (impact, confidence, ease) == (score.impact, score.confidence, score.ease):
        return score, notes
    return (
        score.model_copy(update={"impact": impact, "confidence": confidence, "ease": ease}),
        notes,
    )


def apply_constraint_overrides(
    score: ICEScore, risk: Level, policy: ConstraintPolicy
) -> tuple[ICEScore, Level, list[str]]:
    """Apply the spec's Constraint Override Rules to a score/risk pair.

    Returns the (possibly adjusted) score, risk, and the list of applied rules.
    """
    applied: list[str] = []

    if policy.compliance:
        if risk is Level.HIGH:
            risk = Level.MEDIUM
            applied.append("compliance: risk hard-capped at Medium (flagged for review)")
        else:
            applied.append("compliance: risk cap active")

    if policy.no_coding and score.ease > 4:
        score = score.model_copy(update={"ease": 4})
        applied.append("no-coding: ease capped at 4 (configuration-level only)")
    elif policy.no_coding:
        applied.append("no-coding: configuration-level only")

    if policy.agent_limit is not None:
        applied.append(
            f"agent-limit {policy.agent_limit}: multi-agent spots rerouted to "
            "single-agent with queuing"
        )

    if policy.urgent:
        applied.append("urgent: ranking by Ease first (quick wins)")

    if policy.low_budget:
        applied.append("budget low/zero: only existing-tool, config-level work eligible")

    if policy.eu_data_residency:
        applied.append("EU data residency: external data channels require verified EU hosting")

    if policy.human_payment_approval:
        applied.append("payments: explicit human approval required")

    return score, risk, applied


def ease_first(
    constraints: str, constraint_params: Mapping[str, str] | None = None
) -> bool:
    """Whether constraints force Ease-first ranking (urgent / tight timeline)."""
    return parse_constraint_policy(constraints, constraint_params).urgent


def strategic_filters(opp: Opportunity) -> dict[str, bool]:
    """The three strategic filters from the spec, applied in order."""
    s = opp.score
    return {
        "low_hanging": s.ease >= 4 and s.impact >= 3,
        "high_value": opp.ice >= 40 and opp.draft.risk_level.rank <= Level.MEDIUM.rank,
        "vision": s.impact == 5 and s.ease <= 2,
    }


def active_filters(opp: Opportunity) -> list[str]:
    return [key for key, active in strategic_filters(opp).items() if active]


def _exclusions(opp: Opportunity, policy: ConstraintPolicy) -> list[str]:
    """Every reason this opportunity fails the hard portfolio constraints."""
    reasons: list[str] = []
    if opp.unresolved_refs:
        reasons.append(
            "grounding: cited evidence ids do not resolve: "
            + ", ".join(sorted(opp.unresolved_refs))
        )
    reasons.extend(f"quality gate: {reason}" for reason in opp.quality_gate_reasons)
    if opp.critique_overall < PUBLICATION_QUALITY_FLOOR:
        reasons.append(
            f"critic score {opp.critique_overall:g} is below the "
            f"{PUBLICATION_QUALITY_FLOOR:g} inspiration quality floor after "
            f"{opp.iterations} iteration{'s' if opp.iterations != 1 else ''}"
        )
    if policy.low_budget and opp.score.ease < 4:
        reasons.append(f"budget low/zero requires Ease >= 4 (has {opp.score.ease})")
    if policy.no_coding and opp.score.ease < 4:
        reasons.append(f"no-coding requires Ease >= 4 (has {opp.score.ease})")
    source_risk = opp.source_risk_level or opp.draft.risk_level
    if policy.compliance and source_risk is Level.HIGH:
        reasons.append("compliance excludes unresolved high-risk items")
    if policy.no_infrastructure and opp.draft.layer not in {Layer.DOCUMENT, Layer.KNOWLEDGE}:
        reasons.append(
            f"no existing infrastructure limits to Document/Knowledge "
            f"(is {opp.draft.layer.value})"
        )
    if policy.mature_stack and opp.draft.layer not in {
        Layer.COMMUNICATION,
        Layer.DECISION,
        Layer.MONITORING,
    }:
        reasons.append(
            f"existing mature stack limits to Communication/Decision/Monitoring "
            f"(is {opp.draft.layer.value})"
        )
    if policy.agent_limit is not None and opp.draft.agent_count > policy.agent_limit:
        reasons.append(
            f"agent limit {policy.agent_limit} exceeded (needs {opp.draft.agent_count})"
        )
    draft_text = " ".join(
        [
            opp.draft.proposed_automation,
            *opp.draft.steps,
            *opp.draft.outputs,
            *opp.draft.technical_requirements,
            *opp.draft.dependencies,
        ]
    ).casefold()
    if policy.eu_data_residency:
        external_channels = (
            "email-to-sms",
            "sms gateway",
            "carrier gateway",
            "twilio",
        )
        declared_channels = opp.draft.external_data_channels
        unverified_declared = [
            channel.name
            for channel in declared_channels
            if not channel.eu_hosting_verified
        ]
        if unverified_declared:
            reasons.append(
                "EU data residency excludes unverified external data channel(s): "
                + ", ".join(unverified_declared)
            )
        proposed = next(
            (channel for channel in external_channels if channel in draft_text),
            "",
        )
        if proposed and not declared_channels:
            reasons.append(
                "EU data residency requires a structured verified channel declaration; "
                "unstructured external data channel "
                f"{proposed!r}"
            )
    if policy.human_payment_approval:
        hitl_text = " ".join(opp.draft.hitl_points).casefold()
        declared_actions = opp.draft.payment_actions
        if declared_actions:
            if any(not action.human_approval_required for action in declared_actions):
                reasons.append("payments require an explicit human approval checkpoint")
            if any(action.autonomous for action in declared_actions):
                reasons.append("payments may not be released autonomously")
        else:
            if not (
                ("payment" in hitl_text or "invoice" in hitl_text)
                and re.search(r"\b(?:human|review|approv)", hitl_text)
            ):
                reasons.append("payments require an explicit human approval checkpoint")
            if re.search(
                r"\b(?:automat(?:e|ed|ically)|autonom(?:ous|ously))"
                r".{0,30}\b(?:release|execute|send|initiate).{0,15}\bpayment",
                draft_text,
            ):
                reasons.append("payments may not be released autonomously")
            if "payment" in draft_text or "invoice" in draft_text:
                reasons.append("payment actions require a structured declaration")
    return reasons


def sort_key(opp: Opportunity, urgent: bool = False) -> tuple[object, ...]:
    """Total ordering over opportunities.

    Ties at equal ICE are the common case, not the exception — five layers
    scoring 4/4/4 all land on 64. A single-key sort left their order to upstream
    insertion, so the ranking was not reproducible. Every tie is broken here,
    ending with ``am_id`` so the order is total.
    """
    if urgent:
        return (
            -opp.score.ease,
            -opp.ice,
            -opp.score.impact,
            -opp.critique_overall,
            opp.am_id,
        )
    return (
        -opp.ice,
        -opp.score.impact,
        -opp.score.ease,
        -opp.score.confidence,
        -opp.critique_overall,
        opp.am_id,
    )


def apply_portfolio_policy(
    opportunities: list[Opportunity],
    constraints: str = "",
    constraint_params: Mapping[str, str] | None = None,
) -> list[Opportunity]:
    """Rank and mark eligibility, retaining every opportunity.

    Returns published opportunities in rank order, followed by filtered ones in
    rank order. Nothing is discarded: a filtered opportunity was still drafted,
    critiqued, refined and scored, and the operator paid for it.
    """
    policy = parse_constraint_policy(constraints, constraint_params)
    ordered = sorted(opportunities, key=lambda o: sort_key(o, policy.urgent))

    marked: list[Opportunity] = []
    for opp in ordered:
        reasons = _exclusions(opp, policy)
        marked.append(
            opp.model_copy(
                update={
                    "eligibility": Eligibility.FILTERED if reasons else Eligibility.PUBLISHED,
                    "exclusion_reasons": reasons,
                }
            )
        )

    if policy.urgent:
        eligible = [o for o in marked if o.published]
        for index, opp in enumerate(eligible):
            if index >= URGENT_PORTFOLIO_SIZE:
                reason = (
                    f"urgent timeline publishes only the top {URGENT_PORTFOLIO_SIZE} "
                    f"by Ease then ICE (ranked {index + 1})"
                )
                position = marked.index(opp)
                marked[position] = opp.model_copy(
                    update={
                        "eligibility": Eligibility.FILTERED,
                        "exclusion_reasons": [*opp.exclusion_reasons, reason],
                    }
                )

    published = [o for o in marked if o.published]
    filtered = [o for o in marked if not o.published]
    return published + filtered


def published(opportunities: Iterable[Opportunity]) -> list[Opportunity]:
    return [o for o in opportunities if o.published]


def filtered(opportunities: Iterable[Opportunity]) -> list[Opportunity]:
    return [o for o in opportunities if not o.published]


def portfolio_stats(opportunities: list[Opportunity]) -> PortfolioStats:
    """Deterministic portfolio shape over the published set."""
    live = published(opportunities)
    ices = [o.ice for o in live]
    by_layer: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    for opp in live:
        by_layer[opp.draft.layer.value] = by_layer.get(opp.draft.layer.value, 0) + 1
        by_tier[opp.tier.value] = by_tier.get(opp.tier.value, 0) + 1
    # sort_key negates the descending fields, so the best-ranked entry is the minimum.
    top = min(live, key=sort_key) if live else None
    return PortfolioStats(
        total=len(opportunities),
        published=len(live),
        filtered=len(opportunities) - len(live),
        by_layer=by_layer,
        by_tier=by_tier,
        avg_ice=round(sum(ices) / len(ices), 1) if ices else 0.0,
        median_ice=round(statistics.median(ices), 1) if ices else 0.0,
        top_ice=max(ices) if ices else 0,
        top_id=top.am_id if top else "",
        filters={
            key: [o.am_id for o in live if strategic_filters(o)[key]] for key in FILTER_KEYS
        },
    )


def tier_for(ice: int) -> Tier:
    """Convenience re-export so callers need not import the schema enum."""
    return Tier.for_ice(ice)
