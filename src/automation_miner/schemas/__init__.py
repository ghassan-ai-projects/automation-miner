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


class ContextPacket(ArtifactModel):
    """Normalized, budget-bounded input for the pipeline."""

    domain: str
    domain_slug: str
    constraints: str = ""
    source_kind: Literal["idea", "file", "kb"]
    content: str
    files: list[str] = Field(default_factory=list)
    digested: bool = False
    truncated: bool = False


class StakeholderProcess(ArtifactModel):
    """One stakeholder and the domain processes they own or participate in."""

    stakeholder: str
    processes: list[str] = Field(min_length=1)


class DomainMap(ArtifactModel):
    """Phase 1 output: structured model of the domain."""

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


class LayerAnalysis(ArtifactModel):
    """Phase 2 output for one layer."""

    layer: Layer
    findings: list[str]
    pain_points: list[str]
    pain_level: Level


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


class PhasePlan(ArtifactModel):
    """Implementation path: MVP, expansion, autonomy."""

    mvp: list[str]
    expansion: list[str]
    autonomy: list[str]


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
    agents_required: str
    effort: Level
    impact_estimate: Level
    risk_level: Level


class DraftBatch(ArtifactModel):
    """Wrapper so the drafter can return 1-2 drafts as one JSON object."""

    drafts: list[OpportunityDraft] = Field(min_length=1, max_length=2)


# Critic rubric weights from DESIGN.md (sum to 1.0).
CRITIQUE_WEIGHTS: dict[str, float] = {
    "groundedness": 0.25,
    "specificity": 0.20,
    "quantified_impact": 0.20,
    "feasibility": 0.15,
    "hitl_clarity": 0.10,
    "differentiation": 0.10,
}
CRITIQUE_THRESHOLD = 7.5


class Critique(ArtifactModel):
    """Critic output: six rubric dimensions (0-10) plus feedback."""

    groundedness: float = Field(ge=0, le=10)
    specificity: float = Field(ge=0, le=10)
    quantified_impact: float = Field(ge=0, le=10)
    feasibility: float = Field(ge=0, le=10)
    hitl_clarity: float = Field(ge=0, le=10)
    differentiation: float = Field(ge=0, le=10)
    feedback: str

    @property
    def overall(self) -> float:
        return round(
            sum(getattr(self, dim) * w for dim, w in CRITIQUE_WEIGHTS.items()),
            2,
        )

    @property
    def passed(self) -> bool:
        return self.overall >= CRITIQUE_THRESHOLD


class ICEScore(ArtifactModel):
    """LLM-proposed ICE factors with rationale; product computed by code."""

    impact: int = Field(ge=1, le=5)
    confidence: int = Field(ge=1, le=5)
    ease: int = Field(ge=1, le=5)
    rationale: str

    @property
    def ice(self) -> int:
        return self.impact * self.confidence * self.ease


class Opportunity(ArtifactModel):
    """Final scored opportunity, ready to publish."""

    am_id: str = Field(pattern=r"^AM-(?:00[1-9]|0[1-9]\d|[1-9]\d{2,})$")
    domain: str
    domain_slug: str
    status: OppStatus = OppStatus.IDENTIFIED
    draft: OpportunityDraft
    score: ICEScore
    ice: int = Field(ge=1, le=125)
    critique_overall: float = Field(ge=0, le=10)
    iterations: int = Field(ge=1)
    overrides_applied: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_ice_product(self) -> Opportunity:
        if self.ice != self.score.ice:
            raise ValueError("ice must equal impact x confidence x ease")
        return self


class RunManifest(ArtifactModel):
    """run.json — what happened in one pipeline run."""

    run_id: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}_[a-z0-9]+(?:-[a-z0-9]+)*$")
    domain: str
    domain_slug: str
    constraints: str
    source_kind: Literal["idea", "file", "kb"]
    source_value: str = Field(min_length=1)
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
