"""Pydantic models for every artifact the pipeline produces.

These are the structured-output contracts between the LLM roles and the
deterministic code. Every model is also the on-disk JSON artifact shape.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ArtifactModel(BaseModel):
    """Strict base contract for model responses and persisted artifacts."""

    model_config = ConfigDict(extra="forbid")


class Layer(StrEnum):
    """The five orthogonal analysis layers from the spec."""

    DOCUMENT = "document"
    COMMUNICATION = "communication"
    DECISION = "decision"
    MONITORING = "monitoring"
    KNOWLEDGE = "knowledge"


class AnalysisMode(StrEnum):
    """How evidence should be interpreted before opportunities are generated."""

    AUTO = "auto"
    OPERATIONAL = "operational"
    STRATEGY = "strategy"


LAYER_ORDER: list[Layer] = list(Layer)

LAYER_TITLES: dict[Layer, str] = {
    Layer.DOCUMENT: "Document & Data Processing",
    Layer.COMMUNICATION: "Communication & Coordination",
    Layer.DECISION: "Decision & Approval",
    Layer.MONITORING: "Monitoring & Alerting",
    Layer.KNOWLEDGE: "Knowledge & Training",
}


class Level(StrEnum):
    """Low/Medium/High estimate levels (effort, impact, risk, pain)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def rank(self) -> int:
        return {Level.LOW: 1, Level.MEDIUM: 2, Level.HIGH: 3}[self]


class OppStatus(StrEnum):
    """Lifecycle status of an opportunity brief."""

    IDENTIFIED = "identified"
    EVALUATING = "evaluating"
    DESIGNING = "designing"
    IMPLEMENTING = "implementing"
    LIVE = "live"
    DEPRECATED = "deprecated"


class Tier(StrEnum):
    """ICE band, so a score is legible without remembering the 1-125 scale."""

    VISION = "vision"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @classmethod
    def for_ice(cls, ice: int) -> Tier:
        if ice >= 80:
            return cls.VISION
        if ice >= 60:
            return cls.HIGH
        if ice >= 40:
            return cls.MEDIUM
        return cls.LOW

    @property
    def label(self) -> str:
        return {
            Tier.VISION: "Vision (ICE 80+)",
            Tier.HIGH: "High (ICE 60-79)",
            Tier.MEDIUM: "Medium (ICE 40-59)",
            Tier.LOW: "Low (ICE <40)",
        }[self]

    @property
    def rank(self) -> int:
        return {Tier.VISION: 4, Tier.HIGH: 3, Tier.MEDIUM: 2, Tier.LOW: 1}[self]


class Eligibility(StrEnum):
    """Whether an opportunity reached publication or was filtered by policy.

    Filtered opportunities are retained rather than deleted: they were drafted,
    critiqued, refined and scored, so discarding them silently hides work the
    operator paid for.
    """

    PUBLISHED = "published"
    FILTERED = "filtered"


# ---------------------------------------------------------------------------
# Ingestion / context
# ---------------------------------------------------------------------------


class SkippedFile(ArtifactModel):
    """A file the pipeline did not read, and why — never silently dropped."""

    path: str
    reason: str
    reader: str = ""


class Chunk(ArtifactModel):
    """One citable unit of evidence.

    ``id`` is short (``S12``) because it is repeated in prompts and cited back by
    the drafter; ``locator`` is the address inside the source document, in that
    format's own terms (``p.4``, ``Sheet1!rows 2-13``, a markdown heading path).
    """

    id: str = Field(pattern=r"^S\d+$")
    source: str
    locator: str = ""
    text: str
    tokens: int = Field(ge=0)
    digested: bool = False

    @property
    def label(self) -> str:
        return f"[{self.id}] {self.source}" + (f" {self.locator}" if self.locator else "")


class ContextStats(ArtifactModel):
    """Accounting for what ingestion kept, dropped, and compressed."""

    source_files: int = 0
    included_files: int = 0
    skipped_files: int = 0
    source_chars: int = 0
    evidence_chars: int = 0
    evidence_tokens: int = 0
    budget_tokens: int = 0
    budget_used_pct: float = 0.0
    retention_pct: float = 100.0
    chunks: int = 0
    digested: bool = False
    truncated: bool = False
    digest_calls: int = 0
    digest_cache_hits: int = 0


class InputQuality(ArtifactModel):
    """Deterministic evidence-richness signal used for preflight and framing."""

    level: Literal["thin", "moderate", "rich"] = "thin"
    score: int = Field(default=0, ge=0, le=100)
    signals: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    warning: str = ""


class RunBudget(ArtifactModel):
    """Hard per-invocation admission limits."""

    max_attempts: int = Field(default=70, ge=1)
    max_tokens: int = Field(default=120_000, ge=1)
    max_seconds: float = Field(default=1_800.0, gt=0)


class ContextPacket(ArtifactModel):
    """Normalized, budget-bounded input for the pipeline.

    ``chunks`` is the evidence index every downstream stage selects from;
    ``overview`` is the bounded global view used for domain mapping.
    """

    domain: str
    domain_slug: str
    constraints: str = ""
    raw_constraints: str = ""
    constraint_params: dict[str, str] = Field(default_factory=dict)
    source_kind: Literal["idea", "file", "kb"]
    overview: str
    chunks: list[Chunk] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    skipped: list[SkippedFile] = Field(default_factory=list)
    reader_errors: list[str] = Field(default_factory=list)
    stats: ContextStats = Field(default_factory=ContextStats)
    input_quality: InputQuality = Field(default_factory=InputQuality)
    retained_quality: InputQuality = Field(default_factory=InputQuality)

    def chunk_ids(self) -> set[str]:
        return {chunk.id for chunk in self.chunks}


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


class EvidenceClaim(ArtifactModel):
    """A claim with source locations that directly support it."""

    claim: str
    evidence_refs: list[str] = Field(min_length=1)


class InputAssessment(ArtifactModel):
    """Preflight classification that prevents using the wrong analysis framework."""

    recommended_mode: Literal["operational", "strategy"]
    source_type: str
    rationale: str
    operational_evidence_refs: list[str] = Field(default_factory=list)
    strategic_evidence_refs: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)


class StakeholderProcess(ArtifactModel):
    """One stakeholder and the domain processes they own or participate in."""

    stakeholder: str
    processes: list[str] = Field(min_length=1)
    evidence_refs: list[str]


class DomainMap(ArtifactModel):
    """Phase 1 output: structured model of the domain."""

    analysis_mode: Literal["operational", "strategy"]
    core_function: str
    stakeholders: list[str]
    stakeholder_processes: list[StakeholderProcess]
    information_flow: str
    decision_density: str
    compliance_surface: str
    technology_maturity: str
    scale_indicators: str
    manual_friction: list[str]
    workflow_patterns: str
    verified_current_state: list[EvidenceClaim]
    stated_gaps: list[EvidenceClaim]
    proposed_initiatives: list[EvidenceClaim]
    benchmarks: list[EvidenceClaim]
    unknowns: list[str]


class OpportunityCandidate(ArtifactModel):
    """Portfolio-level idea selected before independent briefs are drafted."""

    layer: Layer
    title: str
    value_thesis: str
    why_now: str
    differentiation: str
    evidence_refs: list[str] = Field(default_factory=list)


class CandidatePortfolio(ArtifactModel):
    """A deliberately diverse set of high-value candidates for one run."""

    candidates: list[OpportunityCandidate] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def unique_titles(self) -> CandidatePortfolio:
        normalized = [candidate.title.casefold().strip() for candidate in self.candidates]
        if len(normalized) != len(set(normalized)):
            raise ValueError("candidate titles must be unique")
        return self


class LayerAnalysis(ArtifactModel):
    """Phase 2 output for one layer."""

    layer: Layer
    findings: list[str]
    pain_points: list[str]
    pain_level: Level
    evidence_refs: list[str] = Field(default_factory=list)


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


# ---------------------------------------------------------------------------
# Run manifest / telemetry
# ---------------------------------------------------------------------------


class RoleUsage(ArtifactModel):
    """Per-role call and token accounting."""

    calls: int = 0
    logical_calls: int = 0
    attempts: int = 0
    retries: int = 0
    failures: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    attempted_tokens: int = 0
    seconds: float = 0.0
    exact: bool = False

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class RunUsage(ArtifactModel):
    """Whole-run totals. Token counts are exact when the provider reports them."""

    calls: int = 0
    logical_calls: int = 0
    attempts: int = 0
    retries: int = 0
    failures: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    attempted_tokens: int = 0
    seconds: float = 0.0
    exact: bool = False
    by_role: dict[str, RoleUsage] = Field(default_factory=dict)


class SummaryEntry(ArtifactModel):
    """One row of summary.json — enough for an agent to triage without the full brief."""

    am_id: str
    title: str
    layer: Layer
    ice: int
    tier: Tier
    impact: int
    confidence: int
    ease: int
    effort: Level
    risk_level: Level
    critique: float
    iterations: int
    eligibility: Eligibility
    exclusion_reasons: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)
    problem: str
    brief_path: str = ""
    artifact_type: Literal["opportunity_brief", "discovery_hypothesis"] = "opportunity_brief"


class RunSummary(ArtifactModel):
    """summary.json — the compact, agent-facing view of a run."""

    run_id: str
    domain: str
    domain_slug: str
    constraints: str = ""
    raw_constraints: str = ""
    constraint_params: dict[str, str] = Field(default_factory=dict)
    created: str = ""
    status: Literal["running", "completed", "failed", "budget_exhausted"] = "completed"
    publication_status: Literal["pending", "complete"] = "complete"
    budget: RunBudget = Field(default_factory=RunBudget)
    duration_seconds: float = 0.0
    dry_run: bool = False
    stats: PortfolioStats = Field(default_factory=PortfolioStats)
    context: ContextStats = Field(default_factory=ContextStats)
    input_quality: InputQuality = Field(default_factory=InputQuality)
    retained_quality: InputQuality = Field(default_factory=InputQuality)
    usage: RunUsage = Field(default_factory=RunUsage)
    opportunities: list[SummaryEntry] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class RunManifest(ArtifactModel):
    """run.json — what happened in one pipeline run."""

    run_id: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}_[a-z0-9]+(?:-[a-z0-9]+)*$")
    domain: str
    domain_slug: str
    constraints: str
    raw_constraints: str = ""
    constraint_params: dict[str, str] = Field(default_factory=dict)
    source_kind: Literal["idea", "file", "kb"]
    source_value: str = Field(min_length=1)
    analysis_mode: Literal["operational", "strategy"]
    requested_mode: Literal["auto", "operational", "strategy"] = "auto"
    status: Literal["running", "completed", "failed", "budget_exhausted"] = "running"
    publication_status: Literal["pending", "complete"] = "pending"
    budget: RunBudget = Field(default_factory=RunBudget)
    created: str
    finished: str = ""
    duration_seconds: float = Field(default=0.0, ge=0)
    max_iterations: int = Field(ge=1, le=10)
    profile: str
    config_source: str
    prompt_version: str
    dry_run: bool
    models: dict[str, str] = Field(default_factory=dict)
    opportunities: list[str] = Field(default_factory=list)
    filtered: list[str] = Field(default_factory=list)
    stage_seconds: dict[str, float] = Field(default_factory=dict)
    usage: RunUsage = Field(default_factory=RunUsage)
    context: ContextStats = Field(default_factory=ContextStats)
    input_quality: InputQuality = Field(default_factory=InputQuality)
    retained_quality: InputQuality = Field(default_factory=InputQuality)


class StageFailure(ArtifactModel):
    """error.json — written when a stage raises, so a failed run is diagnosable."""

    run_id: str = ""
    stage: str
    error_type: str
    error: str
    created: str
    status: Literal["failed", "budget_exhausted"] = "failed"
    budget: RunBudget = Field(default_factory=RunBudget)
    budget_limit: str = ""
    observed_attempts: int = 0
    observed_tokens: int = 0
    stage_seconds: dict[str, float] = Field(default_factory=dict)
    usage: RunUsage = Field(default_factory=RunUsage)
    artifacts_written: list[str] = Field(default_factory=list)
    quarantined_artifacts: list[str] = Field(default_factory=list)
