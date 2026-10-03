"""Split reader segments into numbered, citable evidence chunks."""

from __future__ import annotations

import re
from typing import Iterable

from automation_miner.context.budget import (
    ContextBudget,
    budget_chars,
    estimate_tokens,
)
from automation_miner.readers.base import SourceDocument
from automation_miner.schemas import Chunk

MIN_CHUNK_TOKENS = 40

_PARAGRAPH_RE = re.compile(r"\n\s*\n")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _hard_split(unit: str, limit: int, overlap: int) -> list[str]:
    """A unit with no usable boundary, cut into overlapping fixed windows."""
    step, back = budget_chars(limit), budget_chars(overlap)
    return [unit[start : start + step] for start in range(0, len(unit), max(1, step - back))]


def _pack(units: list[str], limit: int, overlap: int) -> list[str]:
    """Greedily pack units into pieces under ``limit``, carrying a short tail."""
    pieces: list[str] = []
    current: list[str] = []
    tokens = 0
    for unit in units:
        unit_tokens = estimate_tokens(unit)
        if unit_tokens > limit:
            if current:
                pieces.append("\n\n".join(current))
                current, tokens = [], 0
            pieces += _hard_split(unit, limit, overlap)
            continue
        if tokens + unit_tokens > limit and current:
            pieces.append("\n\n".join(current))
            tail = current[-1] if overlap and estimate_tokens(current[-1]) <= overlap else ""
            current, tokens = ([tail] if tail else []), estimate_tokens(tail)
        current.append(unit)
        tokens += unit_tokens
    return pieces + (["\n\n".join(current)] if current else [])


def _split_to_size(text: str, limit: int, overlap: int) -> list[str]:
    """Split text at paragraph, then sentence, then hard boundaries.

    Boundaries are chosen so a chunk never ends mid-sentence when a sentence
    break is available — the previous fixed-offset slicing cut through tables
    and mangled any fact that straddled the boundary.
    """
    if estimate_tokens(text) <= limit:
        return [text]
    units = [unit for unit in _PARAGRAPH_RE.split(text) if unit.strip()]
    if len(units) == 1:
        units = [unit for unit in _SENTENCE_RE.split(text) if unit.strip()]
    return [piece for piece in _pack(units, limit, overlap) if piece.strip()]


def locator_span(locators: Iterable[str]) -> str:
    """Collapse the locators of merged segments into one address.

    Merging tiny sections is worth the token saving, but silently keeping only
    the first locator would discard provenance for everything merged in — the
    exact loss this module exists to prevent. A span keeps both ends.
    """
    seen = [loc for loc in dict.fromkeys(locators) if loc]
    if not seen:
        return ""
    if len(seen) == 1:
        return seen[0]
    return f"{seen[0]} … {seen[-1]}"


def _emit_chunks(
    chunks: list[Chunk],
    index: int,
    source: str,
    locators: list[str],
    text: str,
    budget: ContextBudget,
) -> int:
    """Append one pending segment group as one or more chunks; return the next id."""
    locator = locator_span(locators)
    for piece in _split_to_size(text, budget.chunk_tokens, budget.chunk_overlap_tokens):
        chunks.append(
            Chunk(
                id=f"S{index}",
                source=source,
                locator=locator,
                text=piece,
                tokens=estimate_tokens(piece),
            )
        )
        index += 1
    return index


def _document_chunks(
    document: SourceDocument, budget: ContextBudget, chunks: list[Chunk], index: int
) -> int:
    """Chunk one document, merging tiny adjacent segments; return the next id."""
    pending, locators = "", []
    for segment in document.segments:
        text = segment.text.strip()
        if not text:
            continue
        if pending and estimate_tokens(pending) < MIN_CHUNK_TOKENS:
            pending = f"{pending}\n\n{text}"
            locators.append(segment.locator)
            continue
        if pending:
            index = _emit_chunks(chunks, index, document.name, locators, pending, budget)
        pending, locators = text, [segment.locator]
    if pending:
        index = _emit_chunks(chunks, index, document.name, locators, pending, budget)
    return index


def chunk_documents(
    documents: Iterable[SourceDocument],
    budget: ContextBudget | None = None,
    start_index: int = 1,
) -> list[Chunk]:
    """Turn reader segments into numbered, citable chunks.

    Segment locators are preserved, so a chunk knows it came from ``p.4`` of a
    named PDF. Oversized segments are split further; tiny adjacent segments are
    merged (keeping a locator span) so ids stay meaningful.
    """
    budget = budget or ContextBudget()
    chunks: list[Chunk] = []
    index = start_index
    for document in documents:
        index = _document_chunks(document, budget, chunks, index)
    return chunks


def renumber(chunks: Iterable[Chunk], start_index: int = 1) -> list[Chunk]:
    """Reassign sequential ids, used after digesting replaces the index."""
    return [
        chunk.model_copy(update={"id": f"S{i}"})
        for i, chunk in enumerate(chunks, start_index)
    ]
