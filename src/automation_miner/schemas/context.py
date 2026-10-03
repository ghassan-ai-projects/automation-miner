"""Ingestion contracts: evidence chunks, context packet, input quality, run budget."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from automation_miner.schemas.base import ArtifactModel


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

    max_attempts: int = Field(default=200, ge=1)
    max_tokens: int = Field(default=1_500_000, ge=1)
    max_seconds: float = Field(default=2_400.0, gt=0)
    max_cost_usd: float | None = Field(
        default=None, gt=0, description="Optional spend ceiling, from provider-reported cost."
    )


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
