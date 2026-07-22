"""Pydantic models for every artifact the pipeline produces.

These are the structured-output contracts between the LLM roles and the
deterministic code. Every model is also the on-disk JSON artifact shape.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


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


class ContextPacket(BaseModel):
    """Normalized, budget-bounded input for the pipeline."""

    domain: str
    domain_slug: str
    constraints: str = ""
    source_kind: Literal["idea", "file", "kb"]
    content: str
    files: list[str] = Field(default_factory=list)
    digested: bool = False
    truncated: bool = False


class DomainMap(BaseModel):
    """Phase 1 output: structured model of the domain."""

    core_function: str
    stakeholders: list[str]
    information_flow: str
    decision_density: str
    compliance_surface: str
    technology_maturity: str
    scale_indicators: str
    manual_friction: list[str]
    workflow_patterns: str


class LayerAnalysis(BaseModel):
    """Phase 2 output for one layer."""

    layer: Layer
    findings: list[str]
    pain_points: list[str]
    pain_level: Level


class RiskRow(BaseModel):
    risk: str
    likelihood: Level
    impact: Level
    mitigation: str


class ImpactRow(BaseModel):
    dimension: str
    current: str
    automated: str
    improvement: str


class PhasePlan(BaseModel):
    """Implementation path: MVP, expansion, autonomy."""

    mvp: list[str]
    expansion: list[str]
    autonomy: list[str]


class OpportunityDraft(BaseModel):
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


class DraftBatch(BaseModel):
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


class Critique(BaseModel):
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


class ICEScore(BaseModel):
    """LLM-proposed ICE factors with rationale; product computed by code."""

    impact: int = Field(ge=1, le=5)
    confidence: int = Field(ge=1, le=5)
    ease: int = Field(ge=1, le=5)
    rationale: str

    @property
    def ice(self) -> int:
        return self.impact * self.confidence * self.ease


class Opportunity(BaseModel):
    """Final scored opportunity, ready to publish."""

    am_id: str
    domain: str
    domain_slug: str
    status: OppStatus = OppStatus.IDENTIFIED
    draft: OpportunityDraft
    score: ICEScore
    ice: int
    critique_overall: float
    iterations: int
    overrides_applied: list[str] = Field(default_factory=list)


class RunManifest(BaseModel):
    """run.json — what happened in one pipeline run."""

    run_id: str
    domain: str
    domain_slug: str
    constraints: str
    source_kind: str
    created: str
    finished: str = ""
    duration_seconds: float = 0.0
    max_iterations: int
    profile: str
    dry_run: bool
    models: dict[str, str] = Field(default_factory=dict)
    opportunities: list[str] = Field(default_factory=list)
