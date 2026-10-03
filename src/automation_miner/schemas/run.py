"""Run telemetry contracts: usage, summary, manifest, failure."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from automation_miner.schemas.base import ArtifactModel, Eligibility, Layer, Level, Tier
from automation_miner.schemas.context import ContextStats, InputQuality, RunBudget
from automation_miner.schemas.opportunity import PortfolioStats


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
    cost_usd: float = 0.0
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
    cost_usd: float = Field(
        default=0.0, description="Provider-reported spend; 0 when the provider omits it."
    )
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
