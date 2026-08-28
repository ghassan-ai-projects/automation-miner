"""Deterministic input-quality profiling for honest run preflight."""

from __future__ import annotations

import re
from collections.abc import Iterable

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


def profile_input_quality(
    source_kind: str, chunks: Iterable[Chunk], source_chars: int
) -> InputQuality:
    """Classify retained evidence richness with transparent lexical signals."""
    material = "\n".join(chunk.text for chunk in chunks).casefold()
    signals = [name for name, pattern in _SIGNALS if re.search(pattern, material)]
    missing = [name for name, _ in _SIGNALS if name not in signals]

    score = len(signals) * 12
    if source_chars >= 1_000:
        score += 10
    if source_chars >= 5_000:
        score += 10
    if source_kind == "kb":
        score += 10
    if source_kind == "idea":
        score = min(score, 30)
    score = min(100, score)

    if len(signals) >= 5 and score >= 60:
        level = "rich"
    elif len(signals) >= 2 and score >= 30:
        level = "moderate"
    else:
        level = "thin"

    if level == "thin":
        missing_text = ", ".join(missing[:4]) or "operational detail"
        warning = (
            "Input is thin process evidence; expect discovery hypotheses rather "
            f"than implementation-ready briefs. Add {missing_text}."
        )
    elif level == "moderate":
        warning = (
            "Input contains some operational signals but may leave important "
            "baselines or controls unknown. Validate claims before implementation."
        )
    else:
        warning = "Input contains multiple operational signals; verify cited claims and baselines."

    return InputQuality(
        level=level,
        score=score,
        signals=signals,
        missing=missing,
        warning=warning,
    )
