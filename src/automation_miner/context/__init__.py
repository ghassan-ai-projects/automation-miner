"""Context budgeting, chunking, and per-stage evidence selection.

Three problems this module exists to fix, all measured on the previous
implementation:

* **The budget was 40,000 characters** (~10k tokens) named ``TOKEN_BUDGET_CHARS``
  — a sliver of the windows the routed models actually have, so large knowledge
  bases were destroyed for no reason.
* **Every stage received the same undifferentiated blob.** The ``document`` layer
  analyst read identical context to ``knowledge``, and the critique loop re-sent
  the whole thing per opportunity per round: 163,523 prompt characters for a
  single 8-file dry run.
* **Nothing was citable.** Chunk boundaries fell mid-sentence and provenance was
  lost, while ``groundedness`` is the highest-weighted rubric dimension (25%).

The design: readers emit segments with locators, those become numbered
:class:`Chunk`s (``S1``, ``S2``, …), and each stage draws the chunks most
relevant to *its* question from a shared index, within *its* own budget. A
draft then cites ``evidence_refs`` that code can verify against real chunk ids.

Relevance is deterministic BM25 over the layer's own signal vocabulary — no
embedding model, no network call, no run-to-run variation.
"""

from __future__ import annotations

from automation_miner.context.budget import (
    DEFAULT_CHUNK_OVERLAP_TOKENS,
    DEFAULT_CHUNK_TOKENS,
    estimate_tokens,
    budget_chars,
    ContextBudget,
    fit_text,
    CHARS_PER_TOKEN,
)
from automation_miner.context.chunking import (
    locator_span,
    chunk_documents,
    renumber,
    MIN_CHUNK_TOKENS,
)
from automation_miner.context.retrieval import (
    tokenize,
    EvidenceIndex,
    layer_query,
    draft_query,
    render_chunks,
    LAYER_TERMS,
    PAIN_TERMS,
)

__all__ = [
    "CHARS_PER_TOKEN",
    "ContextBudget",
    "DEFAULT_CHUNK_OVERLAP_TOKENS",
    "DEFAULT_CHUNK_TOKENS",
    "EvidenceIndex",
    "LAYER_TERMS",
    "MIN_CHUNK_TOKENS",
    "PAIN_TERMS",
    "budget_chars",
    "chunk_documents",
    "draft_query",
    "estimate_tokens",
    "fit_text",
    "layer_query",
    "locator_span",
    "render_chunks",
    "renumber",
    "tokenize",
]
