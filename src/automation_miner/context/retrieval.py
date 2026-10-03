"""Deterministic BM25 evidence selection over each stage's signal vocabulary."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from html import escape
from typing import Iterable

from automation_miner.context.budget import estimate_tokens, fit_text
from automation_miner.schemas import Chunk, Layer

# BM25 parameters (standard defaults).
_BM25_K1 = 1.5
_BM25_B = 0.75

# Unicode-aware: "Überwachung" is one token, not "berwachung".
_WORD_RE = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*")


LAYER_TERMS: dict[Layer, tuple[str, ...]] = {
    Layer.DOCUMENT: (
        "form", "forms", "document", "documents", "spreadsheet", "excel", "csv",
        "report", "reports", "template", "invoice", "invoices", "contract", "filing",
        "data", "entry", "extract", "extraction", "reconcile", "reconciliation",
        "record", "records", "archive", "scan", "pdf", "copy", "paste", "transcribe",
        "field", "fields", "validate", "validation", "etl", "import", "export",
        # German
        "formular", "dokument", "dokumente", "rechnung", "rechnungen", "vertrag",
        "erfassung", "eingabe", "abgleich", "bericht", "vorlage", "akte", "tabelle",
        "abtippen", "schadenanzeige", "beleg", "belege", "datenpflege",
    ),
    Layer.COMMUNICATION: (
        "email", "emails", "inbox", "chat", "message", "messages", "meeting",
        "meetings", "status", "update", "updates", "notify", "notification",
        "escalate", "escalation", "sla", "reminder", "follow", "coordination",
        "handoff", "call", "calls", "distribute", "cc", "triage", "routing",
        "stakeholder", "communication",
        # German
        "postfach", "nachricht", "rückfrage", "rückfragen", "eskalation", "abstimmung",
        "besprechung", "benachrichtigung", "anruf", "anrufe", "telefon", "weiterleitung",
    ),
    Layer.DECISION: (
        "approve", "approval", "approvals", "approver", "decision", "decisions",
        "rule", "rules", "policy", "policies", "exception", "exceptions", "route",
        "routing", "threshold", "delegate", "delegation", "authorize", "sign",
        "criteria", "eligibility", "review", "reject", "rejection", "compliance",
        "judgment", "discretion", "gate",
        # German
        "freigabe", "genehmigung", "prüfung", "entscheidung", "regel", "regeln",
        "ausnahme", "ausnahmen", "klassifizierung", "zuordnung", "schwelle", "deckung",
    ),
    Layer.MONITORING: (
        "monitor", "monitoring", "alert", "alerts", "alerting", "threshold",
        "anomaly", "dashboard", "dashboards", "incident", "incidents", "breach",
        "track", "tracking", "detect", "detection", "kpi", "metric", "metrics",
        "downtime", "error", "errors", "audit", "log", "logs", "sla", "outage",
        "check", "checks",
        # German
        "überwachung", "kennzahl", "kennzahlen", "rückstau", "warteschlange", "alarm",
        "frist", "fristen", "verzögerung", "auslastung", "störung", "fehlerquote",
    ),
    Layer.KNOWLEDGE: (
        "onboarding", "onboard", "sop", "sops", "training", "train", "knowledge",
        "documentation", "procedure", "procedures", "tribal", "expert", "expertise",
        "faq", "wiki", "handbook", "certify", "certification", "learn", "learning",
        "instruction", "instructions", "guide", "question", "questions", "manual",
        "playbook", "handover",
        # German
        "schulung", "einarbeitung", "wissen", "handbuch", "richtlinie", "anleitung",
        "arbeitsanweisung", "leitfaden", "weiterbildung", "übergabe",
    ),
}

# Terms that indicate automation-relevant pain regardless of layer.
PAIN_TERMS: tuple[str, ...] = (
    "manual", "manually", "tedious", "repetitive", "error", "errors", "bottleneck",
    "delay", "delays", "slow", "rework", "duplicate", "backlog", "overtime",
    "hours", "minutes", "days", "week", "weekly", "daily", "monthly", "volume",
    "per", "cost", "spend", "fte", "headcount", "friction", "workaround",
    # German
    "manuell", "fehler", "doppelt", "nacharbeit", "verzögerung", "engpass",
    "rückstand", "aufwand", "überstunden", "stunden", "minuten", "tage", "woche",
    "wöchentlich", "täglich", "kosten", "mehrfach", "medienbruch",
)


def tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


class _Selection:
    """Chunks chosen so far for one stage, within its token budget."""

    def __init__(self, chunks: list[Chunk], budget: int) -> None:
        self.chunks, self.budget = chunks, budget
        self.chosen: list[int] = []
        self.used = 0
        self.sources: set[str] = set()

    def take(self, i: int) -> bool:
        cost = self.chunks[i].tokens
        if self.used + cost > self.budget:
            return False
        self.chosen.append(i)
        self.sources.add(self.chunks[i].source)
        self.used += cost
        return True

    def diversify(self, ranked: list[int], min_sources: int) -> None:
        """One chunk from each distinct source, best-scoring first."""
        seen: set[str] = set()
        for i in ranked:
            source = self.chunks[i].source
            if source in seen or i in self.chosen:
                continue
            seen.add(source)
            if len(self.sources) >= min_sources and len(seen) > min_sources:
                break
            self.take(i)

    def fill(self, ranked: list[int], scores: list[float]) -> None:
        """Remaining budget to the best-scoring chunks; irrelevant ones only if empty."""
        for i in ranked:
            if i in self.chosen or (scores[i] <= 0 and self.chosen):
                continue
            if not self.take(i) and self.used >= self.budget:
                break


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
        self, query: Iterable[str], budget_tokens: int, *, min_sources: int = 2,
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
        ranked = sorted(range(len(self.chunks)), key=lambda i: (-scores[i], self.chunks[i].id))
        picked = _Selection(self.chunks, budget_tokens)
        pinned_ids = set(pinned)
        for i, chunk in enumerate(self.chunks):
            if chunk.id in pinned_ids:
                picked.take(i)
        if min_sources > 1:
            picked.diversify(ranked, min_sources)
        picked.fill(ranked, scores)
        if picked.chosen:
            return [self.chunks[i] for i in sorted(set(picked.chosen))]
        # Every chunk individually exceeds the budget. Handing the stage no
        # evidence at all is worse than handing it the most relevant excerpt.
        best = self.chunks[ranked[0]]
        text = fit_text(best.text, budget_tokens)
        return [best.model_copy(update={"text": text, "tokens": estimate_tokens(text)})]

    def resolve(self, refs: Iterable[str]) -> tuple[list[str], list[str]]:
        """Split cited refs into known and unknown ids."""
        known = self.by_id()
        valid: list[str] = []
        invalid: list[str] = []
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
    blocks = [
        f"{chunk.label}\n<untrusted-evidence id=\"{chunk.id}\">\n"
        f"{escape(chunk.text.strip(), quote=False)}\n</untrusted-evidence>"
        for chunk in chunks
    ]
    body = "\n\n".join(blocks)
    if not header:
        return body
    return f"{header}\n\n{body}" if body else header
