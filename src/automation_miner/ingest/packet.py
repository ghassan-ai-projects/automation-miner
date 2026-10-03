"""Assemble the budget-bounded context packet from read documents."""

from __future__ import annotations

import re

from pathlib import Path
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Literal

from automation_miner.context import (
    ContextBudget,
    chunk_documents,
    fit_text,
    render_chunks,
)
from automation_miner.digest import DigestCache, digest_evidence, trim_to_budget
from automation_miner.quality import profile_input_quality
from automation_miner.readers import (
    SourceDocument,
)
from automation_miner.schemas import (
    Chunk,
    ContextPacket,
    ContextStats,
    InputQuality,
    SkippedFile,
)

MAX_DOMAIN_CHARS = 200
MAX_SLUG_CHARS = 80

if TYPE_CHECKING:
    from automation_miner.models.client import MinerModel, RunScopedModel


def slugify(text: str) -> str:
    """Domain slug: lowercase, hyphens for spaces, special chars removed."""
    text = re.sub(r"\(.*?\)", "", text.lower())
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:MAX_SLUG_CHARS].rstrip("-") or "domain"


def clean_domain(value: str) -> str:
    """Collapse whitespace and drop heading punctuation such as a trailing colon.

    An idea's first line is often a heading ("DHL in Germany — operational
    domain description:"), and the colon used to leak into every brief title.
    """
    text = " ".join(value.split()).strip(" \t:;,.-—–#*")
    return text[:MAX_DOMAIN_CHARS].rstrip() or "untitled-domain"


SourceKind = Literal["idea", "file", "kb"]


@dataclass
class PacketSource:
    """Everything ingestion read, and how to fit it into the evidence budget."""

    domain: str
    source_kind: SourceKind
    documents: list[SourceDocument]
    constraints: str
    budget: ContextBudget
    skipped: list[SkippedFile] = field(default_factory=list)
    model: MinerModel | RunScopedModel | None = None
    cache_root: Path | None = None
    reader_errors: list[str] = field(default_factory=list)
    preflight_callback: Callable[[InputQuality], None] | None = None
    # The input's own name (file stem, folder name); the slug follows it when set.
    slug_name: str = ""


@dataclass
class _Fit:
    chunks: list[Chunk]
    digested: bool = False
    truncated: bool = False
    calls: int = 0
    cache_hits: int = 0


def _fit_to_budget(chunks: list[Chunk], source: PacketSource) -> _Fit:
    """Digest when over budget (if a model is available), then trim whole chunks."""
    budget = source.budget
    fit = _Fit(chunks)
    if sum(chunk.tokens for chunk in chunks) <= budget.evidence_tokens:
        return fit
    if source.model is not None:
        cache = DigestCache(source.cache_root / "digests" if source.cache_root else None)
        outcome = digest_evidence(chunks, source.model, budget, cache)
        fit = _Fit(outcome.chunks, outcome.digested, False, outcome.calls, outcome.cache_hits)
    if sum(chunk.tokens for chunk in fit.chunks) > budget.evidence_tokens:
        before = len(fit.chunks)
        fit.chunks = trim_to_budget(fit.chunks, budget.evidence_tokens)
        fit.truncated = len(fit.chunks) < before
    return fit


def _stats(source: PacketSource, fit: _Fit, source_chars: int) -> ContextStats:
    evidence_chars = sum(len(chunk.text) for chunk in fit.chunks)
    evidence_tokens = sum(chunk.tokens for chunk in fit.chunks)
    limit = source.budget.evidence_tokens
    return ContextStats(
        source_files=len(source.documents) + len(source.skipped),
        included_files=len(source.documents), skipped_files=len(source.skipped),
        source_chars=source_chars, evidence_chars=evidence_chars,
        evidence_tokens=evidence_tokens, budget_tokens=limit,
        budget_used_pct=round(100 * evidence_tokens / limit, 1) if limit else 0.0,
        # Clamped at 100: chunk overlap deliberately duplicates a little text, so
        # the raw ratio can exceed 1. This metric answers "was evidence lost?".
        retention_pct=(
            min(100.0, round(100 * evidence_chars / source_chars, 1)) if source_chars else 100.0
        ),
        chunks=len(fit.chunks), digested=fit.digested, truncated=fit.truncated,
        digest_calls=fit.calls, digest_cache_hits=fit.cache_hits,
    )


def _telemetry(source: PacketSource) -> list[str]:
    """Reader errors plus per-document PDF page failures, never silently dropped."""
    telemetry = list(source.reader_errors)
    for document in source.documents:
        failed = document.meta.get("pages_failed", 0)
        if failed:
            detail = document.meta.get("page_errors", "")
            telemetry.append(
                f"{document.name}: {failed} PDF page(s) failed extraction"
                + (f" ({detail})" if detail else "")
            )
    return telemetry


def build_packet(source: PacketSource) -> ContextPacket:
    """Chunk, digest if over budget, and assemble the packet with its stats."""
    source_chars = sum(document.chars for document in source.documents)
    chunks = chunk_documents(source.documents, source.budget)
    source_quality = profile_input_quality(source.source_kind, chunks, source_chars)
    if source.preflight_callback is not None:
        source.preflight_callback(source_quality)
    fit = _fit_to_budget(chunks, source)
    stats = _stats(source, fit, source_chars)
    cleaned = clean_domain(source.domain)
    return ContextPacket(
        domain=cleaned,
        domain_slug=slugify(source.slug_name or cleaned),
        constraints=source.constraints,
        source_kind=source.source_kind,
        overview=fit_text(render_chunks(fit.chunks), source.budget.map_tokens),
        chunks=fit.chunks,
        files=[document.path for document in source.documents],
        skipped=source.skipped,
        reader_errors=_telemetry(source),
        stats=stats,
        input_quality=source_quality,
        retained_quality=profile_input_quality(source.source_kind, fit.chunks, stats.evidence_chars),
    )
