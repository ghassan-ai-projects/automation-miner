"""Deterministic input-quality profiling for honest run preflight."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal

from automation_miner.schemas import Chunk, InputQuality

_SIGNALS: tuple[tuple[str, str], ...] = (
    ("owners", r"\b(?:owner|owned by|responsible|team|department|role)\b"),
    ("systems", r"\b(?:system|platform|application|sap|salesforce|excel|api)\b"),
    ("handoffs", r"\b(?:handoff|handover|hands?\s+off|transfer|re-?key|copy[- ]paste|escalat)\b"),
    ("volumes", r"\b(?:\d[\d,.]*\s*(?:items?|cases?|claims?|tickets?|rows?|per day|per week|per month)|volume|throughput)\b"),
    ("durations", r"\b(?:\d[\d,.]*\s*(?:hours?|minutes?|days?|weeks?)|duration|takes|cycle time)\b"),
    ("errors", r"\b(?:error|failure|defect|rework|duplicate|exception|incident|backlog)\b"),
    ("controls", r"\b(?:approval|audit|control|compliance|sla|policy|review|four[- ]eyes)\b"),
)


_WARNINGS = {
    "moderate": (
        "Input contains some operational signals but may leave important "
        "baselines or controls unknown. Validate claims before implementation."
    ),
    "rich": "Input contains multiple operational signals; verify cited claims and baselines.",
}


def _score(source_kind: str, signals: int, source_chars: int) -> int:
    score = signals * 12 + 10 * (source_chars >= 1_000) + 10 * (source_chars >= 5_000)
    score += 10 if source_kind == "kb" else 0
    return min(100, min(score, 30) if source_kind == "idea" else score)


def _level(signals: int, score: int) -> Literal["thin", "moderate", "rich"]:
    if signals >= 5 and score >= 60:
        return "rich"
    return "moderate" if signals >= 2 and score >= 30 else "thin"


def profile_input_quality(
    source_kind: str, chunks: Iterable[Chunk], source_chars: int
) -> InputQuality:
    """Classify retained evidence richness with transparent lexical signals."""
    material = "\n".join(chunk.text for chunk in chunks).casefold()
    signals = [name for name, pattern in _SIGNALS if re.search(pattern, material)]
    missing = [name for name, _ in _SIGNALS if name not in signals]
    score = _score(source_kind, len(signals), source_chars)
    level = _level(len(signals), score)
    warning = _WARNINGS.get(level) or (
        "Input is thin process evidence; expect discovery hypotheses rather than "
        f"implementation-ready briefs. Add {', '.join(missing[:4]) or 'operational detail'}."
    )
    return InputQuality(level=level, score=score, signals=signals, missing=missing, warning=warning)