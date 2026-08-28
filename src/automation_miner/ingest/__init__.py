"""Input normalization: idea string, file, or KB folder → ContextPacket.

Every input becomes a numbered evidence index (a :class:`Chunk` list) plus a
budget-bounded ``overview`` used for domain mapping. Downstream stages select
the chunks relevant to their own question instead of receiving one shared blob.

Failure handling is per-file. A malformed ``.json``, a password-protected PDF, a
file over the size cap, or a format with no available reader is recorded in
``skipped`` with a reason and the run continues — previously any one of those
aborted ingestion of the entire folder.

Oversized single files are digested like knowledge bases rather than hard-cut:
a 220k-char brief used to be truncated mid-sentence to 18% of its content with
nothing but a boolean to show for it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from automation_miner.context import (
    ContextBudget,
    chunk_documents,
    estimate_tokens,
    fit_text,
    render_chunks,
)
from automation_miner.digest import DigestCache, digest_evidence
from automation_miner.quality import profile_input_quality
from automation_miner.readers import (
    ReaderError,
    ReaderRegistry,
    Segment,
    SourceDocument,
    build_registry,
)
from automation_miner.schemas import (
    Chunk,
    ContextPacket,
    ContextStats,
    InputQuality,
    SkippedFile,
)

if TYPE_CHECKING:
    from automation_miner.models.client import MinerModel, RunScopedModel

MAX_DOMAIN_CHARS = 200
MAX_SLUG_CHARS = 80
# Bound on how much of a tree one run will walk, so a symlink loop or an
# accidentally huge folder fails loudly instead of hanging.
MAX_KB_FILES = 5_000


def slugify(text: str) -> str:
    """Domain slug: lowercase, hyphens for spaces, special chars removed."""
    text = re.sub(r"\(.*?\)", "", text.lower())
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:MAX_SLUG_CHARS].rstrip("-") or "domain"


def _clean_domain(value: str) -> str:
    return " ".join(value.split()).strip()[:MAX_DOMAIN_CHARS] or "untitled-domain"


def _enumerate_files(folder: Path) -> tuple[list[Path], list[SkippedFile]]:
    """List candidate files, refusing to follow directory symlinks out of the tree."""
    files: list[Path] = []
    skipped: list[SkippedFile] = []
    root = folder.resolve()
    for path in sorted(folder.rglob("*")):
        if len(files) >= MAX_KB_FILES:
            skipped.append(
                SkippedFile(
                    path=str(path),
                    reason=f"knowledge base exceeds the {MAX_KB_FILES} file limit",
                )
            )
            break
        if path.is_dir():
            continue
        try:
            resolved = path.resolve()
        except OSError as exc:
            skipped.append(SkippedFile(path=str(path), reason=f"cannot resolve path: {exc}"))
            continue
        if not resolved.is_relative_to(root):
            skipped.append(
                SkippedFile(path=str(path), reason="symlink points outside the knowledge base")
            )
            continue
        if not path.is_file():
            continue
        files.append(path)
    return files, skipped


def _read_all(
    paths: list[Path], registry: ReaderRegistry
) -> tuple[list[SourceDocument], list[SkippedFile]]:
    """Extract every file, isolating failures so one bad file cannot end the run."""
    documents: list[SourceDocument] = []
    skipped: list[SkippedFile] = []
    for path in paths:
        try:
            document = registry.read(path)
        except ReaderError as exc:
            reader = registry.reader_for(path)
            reason = str(exc)
            if exc.meta.get("page_errors"):
                reason += f"; page telemetry: {exc.meta['page_errors']}"
            skipped.append(
                SkippedFile(
                    path=str(path),
                    reason=reason,
                    reader=getattr(reader, "name", "") if reader else "",
                )
            )
            continue
        except Exception as exc:  # a plugin reader may raise anything
            skipped.append(
                SkippedFile(path=str(path), reason=f"{type(exc).__name__}: {exc}")
            )
            continue
        if not document.segments:
            skipped.append(
                SkippedFile(path=str(path), reason="no text extracted", reader=document.reader)
            )
            continue
        documents.append(document)
    return documents, skipped


def _build_packet(
    *,
    domain: str,
    source_kind: str,
    documents: list[SourceDocument],
    skipped: list[SkippedFile],
    constraints: str,
    budget: ContextBudget,
    model: MinerModel | RunScopedModel | None,
    cache_root: Path | None,
    reader_errors: list[str],
    preflight_callback: Callable[[InputQuality], None] | None = None,
) -> ContextPacket:
    """Chunk, digest if over budget, and assemble the packet with its stats."""
    source_chars = sum(document.chars for document in documents)
    chunks: list[Chunk] = chunk_documents(documents, budget)
    raw_tokens = sum(chunk.tokens for chunk in chunks)
    source_quality = profile_input_quality(source_kind, chunks, source_chars)
    if preflight_callback is not None:
        preflight_callback(source_quality)

    digested = False
    truncated = False
    digest_calls = 0
    cache_hits = 0

    if raw_tokens > budget.evidence_tokens:
        if model is not None:
            outcome = digest_evidence(
                chunks,
                model,
                budget,
                DigestCache(cache_root / "digests" if cache_root else None),
            )
            chunks = outcome.chunks
            digested = outcome.digested
            digest_calls = outcome.calls
            cache_hits = outcome.cache_hits
        if sum(chunk.tokens for chunk in chunks) > budget.evidence_tokens:
            from automation_miner.digest import trim_to_budget

            before = len(chunks)
            chunks = trim_to_budget(chunks, budget.evidence_tokens)
            truncated = len(chunks) < before

    evidence_chars = sum(len(chunk.text) for chunk in chunks)
    evidence_tokens = sum(chunk.tokens for chunk in chunks)
    overview = fit_text(render_chunks(chunks), budget.map_tokens)

    stats = ContextStats(
        source_files=len(documents) + len(skipped),
        included_files=len(documents),
        skipped_files=len(skipped),
        source_chars=source_chars,
        evidence_chars=evidence_chars,
        evidence_tokens=evidence_tokens,
        budget_tokens=budget.evidence_tokens,
        budget_used_pct=round(
            100 * evidence_tokens / budget.evidence_tokens, 1
        )
        if budget.evidence_tokens
        else 0.0,
        # Clamped at 100: chunk overlap deliberately duplicates a little text, so
        # the raw ratio can exceed 1. This metric answers "was evidence lost?",
        # not "how many characters are we shipping".
        retention_pct=(
            min(100.0, round(100 * evidence_chars / source_chars, 1))
            if source_chars
            else 100.0
        ),
        chunks=len(chunks),
        digested=digested,
        truncated=truncated,
        digest_calls=digest_calls,
        digest_cache_hits=cache_hits,
    )
    retained_quality = profile_input_quality(source_kind, chunks, evidence_chars)
    telemetry = list(reader_errors)
    for document in documents:
        failed_pages = document.meta.get("pages_failed", 0)
        if failed_pages:
            detail = document.meta.get("page_errors", "")
            telemetry.append(
                f"{document.name}: {failed_pages} PDF page(s) failed extraction"
                + (f" ({detail})" if detail else "")
            )

    cleaned = _clean_domain(domain)
    return ContextPacket(
        domain=cleaned,
        domain_slug=slugify(cleaned),
        constraints=constraints,
        source_kind=source_kind,  # type: ignore[arg-type]
        overview=overview,
        chunks=chunks,
        files=[document.path for document in documents],
        skipped=skipped,
        reader_errors=telemetry,
        stats=stats,
        input_quality=source_quality,
        retained_quality=retained_quality,
    )


def ingest_idea(
    idea: str,
    constraints: str = "",
    budget: ContextBudget | None = None,
    preflight_callback: Callable[[InputQuality], None] | None = None,
) -> ContextPacket:
    """Use a raw idea/domain string directly as context."""
    content = idea.strip()
    if not content:
        raise ValueError("Idea input must not be empty")
    budget = budget or ContextBudget()
    document = SourceDocument(
        path="<idea>",
        reader="idea",
        media_type="text",  # type: ignore[arg-type]
        segments=[Segment(text=content)],
    )
    packet = _build_packet(
        domain=content.splitlines()[0],
        source_kind="idea",
        documents=[document],
        skipped=[],
        constraints=constraints,
        budget=budget,
        model=None,
        cache_root=None,
        reader_errors=[],
        preflight_callback=preflight_callback,
    )
    return packet.model_copy(update={"files": []})


def ingest_file(
    path: Path,
    constraints: str = "",
    model: MinerModel | RunScopedModel | None = None,
    budget: ContextBudget | None = None,
    registry: ReaderRegistry | None = None,
    cache_root: Path | None = None,
    preflight_callback: Callable[[InputQuality], None] | None = None,
) -> ContextPacket:
    """Read one file of any registered format as context."""
    if not path.is_file():
        raise ValueError(f"Input file does not exist or is not a file: {path}")
    registry = registry or build_registry()
    budget = budget or ContextBudget()
    try:
        document = registry.read(path)
    except ReaderError as exc:
        raise ValueError(f"Cannot read {path}: {exc}") from exc
    if not document.segments:
        raise ValueError(f"No text could be extracted from {path}")
    return _build_packet(
        domain=path.stem,
        source_kind="file",
        documents=[document],
        skipped=[],
        constraints=constraints,
        budget=budget,
        model=model,
        cache_root=cache_root,
        reader_errors=list(registry.errors),
        preflight_callback=preflight_callback,
    )


def ingest_kb(
    folder: Path,
    constraints: str = "",
    model: MinerModel | RunScopedModel | None = None,
    budget: ContextBudget | None = None,
    registry: ReaderRegistry | None = None,
    cache_root: Path | None = None,
    preflight_callback: Callable[[InputQuality], None] | None = None,
) -> ContextPacket:
    """Normalize a knowledge-base folder into one bounded evidence index."""
    if not folder.is_dir():
        raise ValueError(f"Knowledge-base folder does not exist or is not a directory: {folder}")
    registry = registry or build_registry()
    budget = budget or ContextBudget()

    candidates, walk_skips = _enumerate_files(folder)
    if not candidates:
        raise ValueError(f"No files found in {folder}")

    documents, read_skips = _read_all(candidates, registry)
    skipped = walk_skips + read_skips
    if not documents:
        reasons = "; ".join(f"{Path(s.path).name}: {s.reason}" for s in skipped[:5])
        raise ValueError(f"No readable files in {folder}. Skipped: {reasons}")

    return _build_packet(
        domain=folder.name,
        source_kind="kb",
        documents=documents,
        skipped=skipped,
        constraints=constraints,
        budget=budget,
        model=model,
        cache_root=cache_root,
        reader_errors=list(registry.errors),
        preflight_callback=preflight_callback,
    )


def evidence_tokens(packet: ContextPacket) -> int:
    """Token size of a packet's evidence index."""
    return sum(estimate_tokens(chunk.text) for chunk in packet.chunks)
