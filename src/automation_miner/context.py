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

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable

from automation_miner.readers.base import SourceDocument
from automation_miner.schemas import Chunk, Layer

# Chars per token. Deliberately conservative: over-estimating tokens keeps the
# pipeline inside real model windows, and the ratio only has to be stable, not
# perfect, for budgeting to work.
CHARS_PER_TOKEN = 3.6

DEFAULT_CHUNK_TOKENS = 700
DEFAULT_CHUNK_OVERLAP_TOKENS = 60
MIN_CHUNK_TOKENS = 40

# BM25 parameters (standard defaults).
_BM25_K1 = 1.5
_BM25_B = 0.75

_WORD_RE = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
_PARAGRAPH_RE = re.compile(r"\n\s*\n")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def estimate_tokens(text: str) -> int:
    """Approximate token count.

    Latin script averages close to ``CHARS_PER_TOKEN``; CJK is roughly one token
    per character, so those are counted separately rather than under-estimated
    by a factor of three.
    """
    if not text:
        return 0
    wide = sum(1 for ch in text if "　" <= ch <= "鿿" or "가" <= ch <= "힯")
    narrow = len(text) - wide
    return max(1, wide + int(narrow / CHARS_PER_TOKEN + 0.5))


def budget_chars(tokens: int) -> int:
    """Character allowance corresponding to a token budget."""
    return int(tokens * CHARS_PER_TOKEN)


@dataclass(frozen=True)
class ContextBudget:
    """Token ceilings per pipeline stage.

    Defaults are cost-conscious rather than window-maximal: the evidence index
    may be large, but each individual call receives only the slice relevant to
    its question. That is both higher fidelity and cheaper than the previous
    behaviour of sending one blob everywhere.
    """

    evidence_tokens: int = 60_000
    map_tokens: int = 24_000
    layer_tokens: int = 16_000
    draft_tokens: int = 16_000
    # Deliberately the tightest budget: this one multiplies by opportunities x
    # rounds, and the critic's job is to verify the claims of *one* draft against
    # the evidence it cites (which is pinned into the pack), not to re-read the
    # whole knowledge base.
    critique_tokens: int = 6_000
    score_tokens: int = 3_000
    chunk_tokens: int = DEFAULT_CHUNK_TOKENS
    chunk_overlap_tokens: int = DEFAULT_CHUNK_OVERLAP_TOKENS
    digest_chunk_tokens: int = 3_000
    digest_target_ratio: float = 0.35
    max_digest_rounds: int = 3
    digest_workers: int = 4

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> ContextBudget:
        """Build from a ``[context]`` table, ignoring unknown keys."""
        if not config:
            return cls()
        fields = {f for f in cls.__dataclass_fields__}
        values: dict[str, Any] = {}
        for key, value in config.items():
            name = str(key).lower()
            if name not in fields:
                continue
            try:
                values[name] = float(value) if "ratio" in name else int(value)
            except (TypeError, ValueError):
                continue
        return cls(**values)

    def for_stage(self, stage: str) -> int:
        """Token budget for a named stage, falling back to the layer budget."""
        return {
            "map": self.map_tokens,
            "layer": self.layer_tokens,
            "draft": self.draft_tokens,
            "critique": self.critique_tokens,
            "score": self.score_tokens,
        }.get(stage, self.layer_tokens)


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


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

    pieces: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for unit in units:
        unit_tokens = estimate_tokens(unit)
        if unit_tokens > limit:
            if current:
                pieces.append("\n\n".join(current))
                current, current_tokens = [], 0
            step = budget_chars(limit)
            back = budget_chars(overlap)
            start = 0
            while start < len(unit):
                pieces.append(unit[start : start + step])
                start += max(1, step - back)
            continue
        if current_tokens + unit_tokens > limit and current:
            pieces.append("\n\n".join(current))
            tail = current[-1] if overlap and estimate_tokens(current[-1]) <= overlap else ""
            current = [tail] if tail else []
            current_tokens = estimate_tokens(tail)
        current.append(unit)
        current_tokens += unit_tokens
    if current:
        pieces.append("\n\n".join(current))
    return [piece for piece in pieces if piece.strip()]


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
        pending_text = ""
        pending_locators: list[str] = []
        for segment in document.segments:
            text = segment.text.strip()
            if not text:
                continue
            if pending_text and estimate_tokens(pending_text) < MIN_CHUNK_TOKENS:
                pending_text = f"{pending_text}\n\n{text}"
                pending_locators.append(segment.locator)
                continue
            if pending_text:
                index = _emit_chunks(
                    chunks, index, document.name, pending_locators, pending_text, budget
                )
            pending_text, pending_locators = text, [segment.locator]
        if pending_text:
            index = _emit_chunks(
                chunks, index, document.name, pending_locators, pending_text, budget
            )
    return chunks


def renumber(chunks: Iterable[Chunk], start_index: int = 1) -> list[Chunk]:
    """Reassign sequential ids, used after digesting replaces the index."""
    return [
        chunk.model_copy(update={"id": f"S{i}"})
        for i, chunk in enumerate(chunks, start_index)
    ]


# ---------------------------------------------------------------------------
# Relevance
# ---------------------------------------------------------------------------

# Signal vocabulary derived from each layer's analysis questions and common
# automation patterns.
LAYER_TERMS: dict[Layer, tuple[str, ...]] = {
    Layer.DOCUMENT: (
        "form", "forms", "document", "documents", "spreadsheet", "excel", "csv",
        "report", "reports", "template", "invoice", "invoices", "contract", "filing",
        "data", "entry", "extract", "extraction", "reconcile", "reconciliation",
        "record", "records", "archive", "scan", "pdf", "copy", "paste", "transcribe",
        "field", "fields", "validate", "validation", "etl", "import", "export",
    ),
    Layer.COMMUNICATION: (
        "email", "emails", "inbox", "chat", "message", "messages", "meeting",
        "meetings", "status", "update", "updates", "notify", "notification",
        "escalate", "escalation", "sla", "reminder", "follow", "coordination",
        "handoff", "call", "calls", "distribute", "cc", "triage", "routing",
        "stakeholder", "communication",
    ),
    Layer.DECISION: (
        "approve", "approval", "approvals", "approver", "decision", "decisions",
        "rule", "rules", "policy", "policies", "exception", "exceptions", "route",
        "routing", "threshold", "delegate", "delegation", "authorize", "sign",
        "criteria", "eligibility", "review", "reject", "rejection", "compliance",
        "judgment", "discretion", "gate",
    ),
    Layer.MONITORING: (
        "monitor", "monitoring", "alert", "alerts", "alerting", "threshold",
        "anomaly", "dashboard", "dashboards", "incident", "incidents", "breach",
        "track", "tracking", "detect", "detection", "kpi", "metric", "metrics",
        "downtime", "error", "errors", "audit", "log", "logs", "sla", "outage",
        "check", "checks",
    ),
    Layer.KNOWLEDGE: (
        "onboarding", "onboard", "sop", "sops", "training", "train", "knowledge",
        "documentation", "procedure", "procedures", "tribal", "expert", "expertise",
        "faq", "wiki", "handbook", "certify", "certification", "learn", "learning",
        "instruction", "instructions", "guide", "question", "questions", "manual",
        "playbook", "handover",
    ),
}

# Terms that indicate automation-relevant pain regardless of layer.
PAIN_TERMS: tuple[str, ...] = (
    "manual", "manually", "tedious", "repetitive", "error", "errors", "bottleneck",
    "delay", "delays", "slow", "rework", "duplicate", "backlog", "overtime",
    "hours", "minutes", "days", "week", "weekly", "daily", "monthly", "volume",
    "per", "cost", "spend", "fte", "headcount", "friction", "workaround",
)


def tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


@dataclass
class EvidenceIndex:
    """A BM25-searchable index over the run's chunks.

    Deterministic by construction: identical inputs always select identical
    evidence, so a run is reproducible and a regression is attributable.
    """

    chunks: list[Chunk] = field(default_factory=list)
    _tokens: list[list[str]] = field(default_factory=list, repr=False)
    _freqs: list[Counter[str]] = field(default_factory=list, repr=False)
    _doc_freq: Counter[str] = field(default_factory=Counter, repr=False)
    _avg_len: float = 0.0

    def __post_init__(self) -> None:
        self._tokens = [tokenize(chunk.text) for chunk in self.chunks]
        self._freqs = [Counter(tokens) for tokens in self._tokens]
        self._doc_freq = Counter()
        for freq in self._freqs:
            self._doc_freq.update(freq.keys())
        lengths = [len(tokens) for tokens in self._tokens]
        self._avg_len = (sum(lengths) / len(lengths)) if lengths else 0.0

    @property
    def total_tokens(self) -> int:
        return sum(chunk.tokens for chunk in self.chunks)

    def by_id(self) -> dict[str, Chunk]:
        return {chunk.id: chunk for chunk in self.chunks}

    def score(self, query: Iterable[str]) -> list[float]:
        """BM25 score per chunk for a bag of query terms."""
        terms = [term for term in query if term]
        count = len(self.chunks)
        if not count or not terms:
            return [0.0] * count
        scores = [0.0] * count
        for term in terms:
            df = self._doc_freq.get(term, 0)
            if not df:
                continue
            idf = math.log(1 + (count - df + 0.5) / (df + 0.5))
            for i, freq in enumerate(self._freqs):
                tf = freq.get(term, 0)
                if not tf:
                    continue
                length = len(self._tokens[i]) or 1
                norm = tf * (_BM25_K1 + 1) / (
                    tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * length / (self._avg_len or 1))
                )
                scores[i] += idf * norm
        return scores

    def select(
        self,
        query: Iterable[str],
        budget_tokens: int,
        *,
        min_sources: int = 2,
        pinned: Iterable[str] = (),
    ) -> list[Chunk]:
        """Highest-scoring chunks that fit the budget, in document order.

        ``min_sources`` reserves room for chunks from distinct files so a single
        verbose document cannot crowd out the rest of the knowledge base.
        ``pinned`` ids are always included when they fit.
        """
        if not self.chunks:
            return []
        scores = self.score(query)
        ranked = sorted(
            range(len(self.chunks)),
            key=lambda i: (-scores[i], self.chunks[i].id),
        )
        pinned_ids = set(pinned)

        chosen: list[int] = []
        used = 0
        sources: set[str] = set()

        def take(i: int) -> bool:
            nonlocal used
            cost = self.chunks[i].tokens
            if used + cost > budget_tokens:
                return False
            chosen.append(i)
            sources.add(self.chunks[i].source)
            used += cost
            return True

        for i, chunk in enumerate(self.chunks):
            if chunk.id in pinned_ids:
                take(i)

        # First pass: one chunk from each distinct source, best-scoring first.
        if min_sources > 1:
            seen: set[str] = set()
            for i in ranked:
                source = self.chunks[i].source
                if source in seen or i in chosen:
                    continue
                seen.add(source)
                if len(sources) >= min_sources and len(seen) > min_sources:
                    break
                take(i)

        for i in ranked:
            if i in chosen:
                continue
            if scores[i] <= 0 and chosen:
                continue
            if not take(i) and used >= budget_tokens:
                break

        if not chosen:
            # Every chunk individually exceeds the budget. Handing the stage no
            # evidence at all is worse than handing it the most relevant excerpt.
            best = self.chunks[ranked[0]]
            text = fit_text(best.text, budget_tokens)
            return [best.model_copy(update={"text": text, "tokens": estimate_tokens(text)})]

        return [self.chunks[i] for i in sorted(set(chosen))]

    def resolve(self, refs: Iterable[str]) -> tuple[list[str], list[str]]:
        """Split cited refs into known and unknown ids."""
        known = self.by_id()
        valid, invalid = [], []
        for ref in refs:
            (valid if ref in known else invalid).append(ref)
        return valid, invalid


def layer_query(layer: Layer, domain: str = "", extra: Iterable[str] = ()) -> list[str]:
    """Query terms for one layer: its signal vocabulary plus pain and domain words."""
    terms = list(LAYER_TERMS[layer]) + list(PAIN_TERMS)
    terms += tokenize(domain)
    for item in extra:
        terms += tokenize(item)
    return terms


def draft_query(layer: Layer, analysis_terms: Iterable[str], domain: str = "") -> list[str]:
    """Query terms for drafting: the layer plus the findings it produced."""
    return layer_query(layer, domain, analysis_terms)


def render_chunks(chunks: Iterable[Chunk], header: str = "") -> str:
    """Render chunks as citable evidence blocks.

    The ``[S12] file locator`` label is what the drafter cites back in
    ``evidence_refs`` and what a reviewer follows to the source document.
    """
    blocks = [f"{chunk.label}\n{chunk.text.strip()}" for chunk in chunks]
    body = "\n\n".join(blocks)
    if not header:
        return body
    return f"{header}\n\n{body}" if body else header


def fit_text(text: str, budget_tokens: int, marker: str = "\n\n[... trimmed to fit budget ...]") -> str:
    """Trim text to a token budget at a paragraph boundary where possible."""
    if estimate_tokens(text) <= budget_tokens:
        return text
    limit = budget_chars(budget_tokens) - len(marker)
    if limit <= 0:
        return marker.strip()
    head = text[:limit]
    cut = max(head.rfind("\n\n"), head.rfind("\n"), head.rfind(". "))
    if cut > limit // 2:
        head = head[: cut + 1]
    return head.rstrip() + marker
