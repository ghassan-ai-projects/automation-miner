"""Analysis contracts: input assessment, domain map, layer analysis, candidate plan."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from automation_miner.schemas.base import ArtifactModel, Layer, Level


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
    addresses_pains: list[str] = Field(
        default_factory=list, description="Pain-ledger ids (P1, P2, ...) this candidate removes."
    )
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


class PainPoint(ArtifactModel):
    """One concrete pain, quantified where the evidence allows.

    Numbers are what let code rank pains: 1,850 claims/week x 9 minutes of
    re-keying is ~277 hours a week, and that should outrank a vague complaint.
    """

    pain: str
    who: str = ""
    volume_per_week: float | None = Field(
        default=None, ge=0, description="Items, cases, or events affected per week."
    )
    minutes_per_item: float | None = Field(
        default=None, ge=0, description="Time lost per affected item, in minutes."
    )
    other_cost: str = Field(
        default="",
        description="Non-time cost in one line: revenue, error rate, SLA misses, risk.",
    )
    observed: bool = Field(
        description="True only when the numbers come from the evidence, not estimates."
    )
    evidence_refs: list[str] = Field(default_factory=list)

    @property
    def weekly_hours(self) -> float | None:
        if self.volume_per_week is None or self.minutes_per_item is None:
            return None
        return round(self.volume_per_week * self.minutes_per_item / 60, 1)


class RankedPain(PainPoint):
    """A pain in the run's ledger, ranked by code and given a citable id."""

    id: str = Field(pattern=r"^P\d+$")
    layer: Layer


class ConsolidatedPain(PainPoint):
    """One distinct pain after merging every layer's descriptions of it."""

    layer: Layer
    sources: list[int] = Field(
        default_factory=list, description="Numbers of the listed pains this one merges."
    )
    volume_formula: str = Field(
        default="",
        description="Arithmetic over evidence figures giving volume_per_week, e.g. '1850 * 0.31'.",
    )


class PainConsolidation(ArtifactModel):
    """The run's distinct, sized pains: merged, completed, and quantified."""

    pains: list[ConsolidatedPain] = Field(default_factory=list)


class LayerAnalysis(ArtifactModel):
    """Phase 2 output for one layer."""

    layer: Layer
    findings: list[str]
    pain_points: list[PainPoint]
    pain_level: Level
    evidence_refs: list[str] = Field(default_factory=list)
