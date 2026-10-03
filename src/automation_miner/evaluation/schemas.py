"""Contracts for run evaluation: deterministic lint plus an independent judge."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from automation_miner.schemas import ArtifactModel

JUDGE_DIMENSIONS: tuple[str, ...] = (
    "specificity",
    "insight",
    "actionability",
    "domain_expertise",
    "epistemic_honesty",
    "readability",
)


class LintFinding(ArtifactModel):
    code: str
    severity: Literal["error", "warning"]
    excerpt: str = ""


class BriefLint(ArtifactModel):
    brief: str
    words: int = 0
    hedge_count: int = 0
    hedges_per_1k_words: float = 0.0
    errors: int = 0
    warnings: int = 0
    findings: list[LintFinding] = Field(default_factory=list)


class AuditedClaim(ArtifactModel):
    """One statement about the subject organization, checked against the evidence."""

    claim: str
    verdict: Literal["supported", "overstated", "unsupported", "assumption", "domain_knowledge"]
    note: str = ""


class ClaimAudit(ArtifactModel):
    """Every organization-specific claim in a brief, each with a verdict.

    A narrow, enumerated check is something a cheap judge does reliably; a
    holistic "how honest is this?" grade it does not (it rated 0 fabricated
    facts where a stronger reference judge found 19).
    """

    claims: list[AuditedClaim] = Field(default_factory=list)

    @property
    def fabricated(self) -> list[AuditedClaim]:
        return [c for c in self.claims if c.verdict in {"overstated", "unsupported"}]


class BriefJudgement(ArtifactModel):
    """An independent reviewer's 1-5 grades for one published brief.

    Weaknesses come first so the grades follow from the critique instead of
    the critique being written to justify a grade.
    """

    weaknesses: list[str] = Field(default_factory=list, max_length=4)
    strengths: list[str] = Field(default_factory=list, max_length=3)
    specificity: int = Field(ge=1, le=5)
    insight: int = Field(ge=1, le=5)
    actionability: int = Field(ge=1, le=5)
    domain_expertise: int = Field(ge=1, le=5)
    epistemic_honesty: int = Field(ge=1, le=5)
    readability: int = Field(ge=1, le=5)
    overall: int = Field(ge=1, le=5)
    fabricated_facts: list[str] = Field(default_factory=list)


class PortfolioJudgement(ArtifactModel):
    """Whole-run view: did the run find the right, distinct opportunities?"""

    missed_opportunities: list[str] = Field(default_factory=list)
    near_duplicates: list[str] = Field(default_factory=list)
    summary: str = ""
    diversity: int = Field(ge=1, le=5)
    coverage: int = Field(ge=1, le=5)
    ranking_sanity: int = Field(ge=1, le=5)


class JudgedBrief(ArtifactModel):
    am_id: str
    title: str
    judgement: BriefJudgement


class RunEvaluation(ArtifactModel):
    """evaluation.json — measured quality of one completed run."""

    run_id: str
    status: str
    analysis_mode: str = ""
    total: int = 0
    published: int = 0
    publication_rate: float = 0.0
    discovery_hypotheses: int = 0
    duration_seconds: float = 0.0
    total_tokens: int = 0
    model_calls: int = 0
    lint: list[BriefLint] = Field(default_factory=list)
    lint_errors: int = 0
    hedges: int = 0
    judge_model: str = ""
    briefs: list[JudgedBrief] = Field(default_factory=list)
    portfolio: PortfolioJudgement | None = None
    means: dict[str, float] = Field(default_factory=dict)
    fabricated_facts: int = 0
    min_overall: int = 0
