"""Map-reduce digesting with an explicit size target, caching, and parallelism.

The previous digester had no target size: ``digest_prompt`` asked the model to
"compress this file" and accepted whatever came back. Measured on a 49k-char /
8-file knowledge base, the result was **1,894 characters** — 96% of the evidence
discarded while 95% of the context budget went unused. It also ran one
sequential model call per file (62 calls for a 62-file folder) before the
pipeline performed any analysis, and re-paid every call on a re-run.

So digesting here:

* **targets a size**, computed from the remaining budget divided across batches,
  and states that target in the prompt;
* **preserves provenance** — each digest keeps the source file and the locator
  range it covers, so citations survive compression;
* **runs in parallel**, because batches are independent;
* **caches by content hash**, so re-mining the same knowledge base is free.
"""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from automation_miner.context import ContextBudget, budget_chars, estimate_tokens, renumber
from automation_miner.prompts import MAPPER_SYSTEM, PROMPT_VERSION, digest_prompt
from automation_miner.schemas import Chunk

if TYPE_CHECKING:
    from automation_miner.models.client import MinerModel, RunScopedModel

# A digest below this is a headline, not evidence.
MIN_DIGEST_TOKENS = 120
# Aim to fill most of the budget rather than undershoot it.
BUDGET_FILL = 0.85


@dataclass
class DigestOutcome:
    """What digesting did, for the run's context stats."""

    chunks: list[Chunk] = field(default_factory=list)
    calls: int = 0
    cache_hits: int = 0
    rounds: int = 0
    digested: bool = False


class DigestCache:
    """Content-addressed digest cache under ``<workspace>/.cache/digests``."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key(text: str, target_tokens: int) -> str:
        digest = hashlib.sha256()
        digest.update(PROMPT_VERSION.encode())
        digest.update(f"|{target_tokens}|".encode())
        digest.update(text.encode())
        return digest.hexdigest()

    def _path(self, key: str) -> Path | None:
        return self.root / f"{key}.txt" if self.root else None

    def get(self, key: str) -> str | None:
        path = self._path(key)
        if path is None or not path.is_file():
            self.misses += 1
            return None
        try:
            value = path.read_text(encoding="utf-8")
        except OSError:
            self.misses += 1
            return None
        self.hits += 1
        return value

    def put(self, key: str, value: str) -> None:
        path = self._path(key)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value, encoding="utf-8")
        except OSError:
            pass


@dataclass
class _Batch:
    source: str
    locator: str
    text: str
    tokens: int


def _batch_chunks(chunks: list[Chunk], batch_tokens: int) -> list[_Batch]:
    """Group consecutive chunks from one source into digest-sized batches."""
    batches: list[_Batch] = []
    current: list[Chunk] = []
    current_tokens = 0

    def flush() -> None:
        if not current:
            return
        locators = [c.locator for c in current if c.locator]
        if not locators:
            span = ""
        elif len(locators) == 1:
            span = locators[0]
        else:
            span = f"{locators[0]} … {locators[-1]}"
        batches.append(
            _Batch(
                source=current[0].source,
                locator=span,
                text="\n\n".join(c.text for c in current),
                tokens=current_tokens,
            )
        )

    for chunk in chunks:
        same_source = not current or chunk.source == current[0].source
        if current and (current_tokens + chunk.tokens > batch_tokens or not same_source):
            flush()
            current, current_tokens = [], 0
        current.append(chunk)
        current_tokens += chunk.tokens
    flush()
    return batches


def _digest_batches(
    batches: list[_Batch],
    model: MinerModel | RunScopedModel,
    target_tokens: int,
    cache: DigestCache,
    workers: int,
) -> tuple[list[Chunk], int]:
    """Digest every batch, in parallel, returning new chunks and the call count."""
    calls = 0

    def run(batch: _Batch) -> str:
        nonlocal calls
        key = cache.key(batch.text, target_tokens)
        if (cached := cache.get(key)) is not None:
            return cached
        label = batch.source + (f" ({batch.locator})" if batch.locator else "")
        result = model.chat(
            "mapper", MAPPER_SYSTEM, digest_prompt(label, batch.text, budget_chars(target_tokens))
        )
        calls += 1
        cache.put(key, result)
        return result

    if workers > 1 and len(batches) > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            texts = list(pool.map(run, batches))
    else:
        texts = [run(batch) for batch in batches]

    chunks: list[Chunk] = []
    for index, (batch, text) in enumerate(zip(batches, texts, strict=True), 1):
        body = text.strip()
        if not body:
            continue
        chunks.append(
            Chunk(
                id=f"S{index}",
                source=batch.source,
                locator=batch.locator,
                text=body,
                tokens=estimate_tokens(body),
                digested=True,
            )
        )
    return renumber(chunks), calls


def digest_evidence(
    chunks: list[Chunk],
    model: MinerModel | RunScopedModel,
    budget: ContextBudget,
    cache: DigestCache | None = None,
) -> DigestOutcome:
    """Compress an over-budget evidence index toward the budget.

    Returns the original chunks untouched when they already fit. Each round
    targets ``BUDGET_FILL`` of the budget spread across batches, so the result
    approaches the allowance from below instead of collapsing far beneath it.
    """
    outcome = DigestOutcome(chunks=chunks)
    total = sum(chunk.tokens for chunk in chunks)
    if not chunks or total <= budget.evidence_tokens:
        return outcome

    cache = cache or DigestCache()
    workers = max(1, budget.digest_workers)
    current = chunks

    for round_no in range(1, max(1, budget.max_digest_rounds) + 1):
        batches = _batch_chunks(current, budget.digest_chunk_tokens)
        if not batches:
            break
        target_total = int(budget.evidence_tokens * BUDGET_FILL)
        per_batch = max(MIN_DIGEST_TOKENS, target_total // len(batches))
        digested, calls = _digest_batches(batches, model, per_batch, cache, workers)
        outcome.calls += calls
        outcome.rounds = round_no
        outcome.digested = True
        if not digested:
            break
        new_total = sum(chunk.tokens for chunk in digested)
        # A round that fails to shrink the index will not converge; stop and trim.
        if new_total >= sum(chunk.tokens for chunk in current):
            current = digested
            break
        current = digested
        if new_total <= budget.evidence_tokens:
            break

    outcome.chunks = trim_to_budget(current, budget.evidence_tokens)
    outcome.cache_hits = cache.hits
    return outcome


def trim_to_budget(chunks: list[Chunk], budget_tokens: int) -> list[Chunk]:
    """Drop whole chunks from the tail until the index fits, keeping ids sequential.

    Trimming at chunk granularity means evidence is lost as complete, attributed
    units rather than as a sentence severed mid-clause.
    """
    kept: list[Chunk] = []
    used = 0
    for chunk in chunks:
        if used + chunk.tokens > budget_tokens:
            continue
        kept.append(chunk)
        used += chunk.tokens
    return renumber(kept) if len(kept) != len(chunks) else chunks
