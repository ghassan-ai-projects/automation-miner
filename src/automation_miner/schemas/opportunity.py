"""Opportunity contracts: draft, critique, ICE score, scored opportunity."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from automation_miner.schemas.base import (
    ArtifactModel,
    Eligibility,
    Layer,
    Level,
    OppStatus,
    Tier,
)


class RiskRow(ArtifactModel):
    risk: str
    likelihood: Level
    impact: Level
    mitigation: str


class ImpactRow(ArtifactModel):
    dimension: str
    current: str
    automated: str
    improvement: str
    basis: str
    assumption: bool


class PhasePlan(ArtifactModel):
    """Implementation path: MVP, expansion, autonomy."""

    mvp: list[str]
    expansion: list[str]
    autonomy: list[str]


class ExternalDataChannel(ArtifactModel):
    """A structured external channel declaration used by residency policy."""

    name: str
    purpose: str
    hosting_region: str
    eu_hosting_verified: bool = False


class PaymentAction(ArtifactModel):
    """A structured payment action declaration used by approval policy."""

    action: str
    autonomous: bool = False
    human_approval_required: bool = True


class OpportunityDraft(ArtifactModel):
    """A single automation opportunity draft (pre-scoring)."""

    layer: Layer
    title: str
    problem: str
    proposed_automation: str
    inputs: list[str]
    steps: list[str]
    outputs: list[str]
    hitl_points: list[str]
    technical_requirements: list[str]
    dependencies: list[str]
    constraints: list[str]
    impact_analysis: list[ImpactRow]
    implementation: PhasePlan
    risks: list[RiskRow]
    agent_count: int = Field(ge=1, le=20)
    agent_topology: str
    effort: Level
    impact_estimate: Level
    risk_level: Level
    evidence_refs: list[str] = Field(default_factory=list)
    assumptions: list[str]
    validation_questions: list[str]
    success_metrics: list[str] = Field(
        default_factory=list,
        description="2-4 MVP go/no-go measures, each with a baseline source and target.",
    )
    addresses_pains: list[str] = Field(
        default_factory=list, description="Pain-ledger ids; set by code from the plan."
    )
    external_data_channels: list[ExternalDataChannel] = Field(default_factory=list)
    payment_actions: list[PaymentAction] = Field(default_factory=list)


# Critic rubric weights (sum to 1.0).
CRITIQUE_WEIGHTS: dict[str, float] = {
    "groundedness": 0.25,
    "specificity": 0.20,
    "quantified_impact": 0.20,
    "feasibility": 0.15,
    "hitl_clarity": 0.10,
    "differentiation": 0.10,
}
CRITIQUE_THRESHOLD = 7.5
# Inspiration remains visible below the aspirational refinement target. Only
# materially weak drafts and hard semantic/constraint violations are filtered.
PUBLICATION_QUALITY_FLOOR = 6.0


class Critique(ArtifactModel):
    """Critic output: six rubric dimensions (0-10) plus feedback."""

    groundedness: float = Field(ge=0, le=10)
    specificity: float = Field(ge=0, le=10)
    quantified_impact: float = Field(ge=0, le=10)
    feasibility: float = Field(ge=0, le=10)
    hitl_clarity: float = Field(ge=0, le=10)
    differentiation: float = Field(ge=0, le=10)
    grounding_violations: list[str]
    constraint_violations: list[str]
    writing_issues: list[str] = Field(default_factory=list)
    feedback: str

    @property
    def overall(self) -> float:
        return round(
            sum(getattr(self, dim) * w for dim, w in CRITIQUE_WEIGHTS.items()),
            2,
        )

    @property
    def passed(self) -> bool:
        return (
            self.overall >= CRITIQUE_THRESHOLD
            and not self.grounding_violations
            and not self.constraint_violations
        )

    @property
    def gate_reasons(self) -> list[str]:
        """Deterministic publication blockers reported through structured fields."""
        reasons = [f"grounding: {issue}" for issue in self.grounding_violations]
        reasons += [f"constraint: {issue}" for issue in self.constraint_violations]
        return reasons


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


class ICEScore(ArtifactModel):
    """LLM-proposed ICE factors with per-factor rationale; product computed by code.

    One rationale per factor rather than a single paragraph: an operator
    disputing a score needs to know why *Ease* is 4, and a shared paragraph
    makes that unauditable.
    """

    impact: int = Field(ge=1, le=5)
    confidence: int = Field(ge=1, le=5)
    ease: int = Field(ge=1, le=5)
    impact_rationale: str
    confidence_rationale: str
    ease_rationale: str

    @property
    def ice(self) -> int:
        return self.impact * self.confidence * self.ease


class PortfolioScore(ICEScore):
    """One opportunity's factors from the comparative portfolio scoring call."""

    am_id: str


class PortfolioScores(ArtifactModel):
    """Every opportunity scored side by side, so the scale is used relatively.

    Scored one at a time, a model anchors every draft at the middle rung and
    the whole portfolio collapses into a single tier.
    """

    scores: list[PortfolioScore] = Field(min_length=1)


class RepairVerdict(ArtifactModel):
    """Narrow re-check after a surgical repair of blocking violations."""

    unresolved: list[str] = Field(default_factory=list)
    new_violations: list[str] = Field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.unresolved and not self.new_violations


class Opportunity(ArtifactModel):
    """Final scored opportunity."""

    am_id: str = Field(pattern=r"^AM-(?:00[1-9]|0[1-9]\d|[1-9]\d{2,})$")
    domain: str
    domain_slug: str
    status: OppStatus = OppStatus.IDENTIFIED
    draft: OpportunityDraft
    score: ICEScore
    ice: int = Field(ge=1, le=125)
    tier: Tier
    critique_overall: float = Field(ge=0, le=10)
    iterations: int = Field(ge=1)
    eligibility: Eligibility = Eligibility.PUBLISHED
    exclusion_reasons: list[str] = Field(default_factory=list)
    overrides_applied: list[str] = Field(default_factory=list)
    calibration: list[str] = Field(default_factory=list)
    unresolved_refs: list[str] = Field(default_factory=list)
    quality_gate_reasons: list[str] = Field(default_factory=list)
    repair_notes: list[str] = Field(default_factory=list)
    artifact_type: Literal["opportunity_brief", "discovery_hypothesis"] = "opportunity_brief"
    source_risk_level: Level | None = None

    @model_validator(mode="after")
    def validate_derived_fields(self) -> Opportunity:
        if self.ice != self.score.ice:
            raise ValueError("ice must equal impact x confidence x ease")
        if self.tier is not Tier.for_ice(self.ice):
            raise ValueError(f"tier must be {Tier.for_ice(self.ice).value!r} for ICE {self.ice}")
        if self.eligibility is Eligibility.FILTERED and not self.exclusion_reasons:
            raise ValueError("filtered opportunities must record at least one exclusion reason")
        return self

    @property
    def published(self) -> bool:
        return self.eligibility is Eligibility.PUBLISHED


class PortfolioStats(ArtifactModel):
    """Deterministic shape of one run's portfolio, for reports and summaries."""

    total: int = 0
    published: int = 0
    filtered: int = 0
    by_layer: dict[str, int] = Field(default_factory=dict)
    by_tier: dict[str, int] = Field(default_factory=dict)
    avg_ice: float = 0.0
    median_ice: float = 0.0
    top_ice: int = 0
    top_id: str = ""
    filters: dict[str, list[str]] = Field(default_factory=dict)
