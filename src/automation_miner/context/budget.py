"""Token estimation and per-stage context budgets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Chars per token. Deliberately conservative: over-estimating tokens keeps the
# pipeline inside real model windows, and the ratio only has to be stable, not
# perfect, for budgeting to work.
CHARS_PER_TOKEN = 3.6

DEFAULT_CHUNK_TOKENS = 700
DEFAULT_CHUNK_OVERLAP_TOKENS = 60


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
    trimmed = head.rstrip() + marker
    open_count = trimmed.count("<untrusted-evidence ")
    close_count = trimmed.count("</untrusted-evidence>")
    if open_count > close_count:
        trimmed += "\n" + "\n".join(
            "</untrusted-evidence>" for _ in range(open_count - close_count)
        )
    return trimmed
