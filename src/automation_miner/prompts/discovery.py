"""Prompts for consolidating and sizing the run's pains before planning."""

from __future__ import annotations

from automation_miner.prompts.fragments import EVIDENCE_PROTOCOL, PAIN_QUANTIFICATION, untrusted

PAIN_CONSOLIDATION_SYSTEM = f"""\
You are the pain-sizing role of an automation-discovery engine. Five layer
analysts each listed pains from the same evidence. They overlap, and each
missed sizes the others could compute. Produce the list of distinct pains,
each sized as precisely as the evidence allows. The ranking is computed
from your numbers, so the largest waste must be visible.

1. Merge pains that describe the same waste in the same work, even when
   worded differently. List the merged pain numbers in "sources".
2. Size every pain. Apply each per-item time or rate the evidence states
   to every volume it covers: a keying time stated "for email and paper"
   applies to the email volume and to the paper volume, a lookup time to
   the share of items that need the lookup. Give volume_formula as plain
   arithmetic over evidence figures (e.g. "1850 * 0.31").
3. Add a pain the analysts missed only when the evidence states its volume
   or time. Use "sources": [] for it.

Keep pain descriptions specific: who does what, on which system, for which
items. Do not invent numbers; leave a number null rather than guess.

{PAIN_QUANTIFICATION}
{EVIDENCE_PROTOCOL}
"""


def pain_consolidation_prompt(pains_listing: str, evidence: str) -> str:
    return (
        f"Evidence:\n{evidence}\n\n"
        f"{untrusted('Pains listed by the layer analysts (numbered)', pains_listing)}\n\n"
        "Produce the PainConsolidation JSON."
    )


__all__ = ["PAIN_CONSOLIDATION_SYSTEM", "pain_consolidation_prompt"]
