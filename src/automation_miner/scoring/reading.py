"""Read free-text constraints into typed policy, and verify the reading in code.

Keyword patterns decided binding filters from prose, and prose defeats them:
"no budget concerns" switched the low-budget filter on until negation rules
were bolted on, and every new phrasing needs another rule. Reading prose is
judgment, so a model maps the constraint text to typed flags. Trust is
checked in code: each flag must quote the words that impose it, and a clause
whose quote is not in the text is discarded. If the call fails, the run keeps
going on the keyword fallback and says so.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from automation_miner.execution import BudgetExceeded
from automation_miner.prompts import POLICY_READER_SYSTEM, policy_reading_prompt
from automation_miner.schemas import PolicyClause, PolicyReading

if TYPE_CHECKING:
    from automation_miner.models.client import MinerModel, RunScopedModel


def _normalized(text: str) -> str:
    return " ".join(text.casefold().split()).strip(" \"'“”‘’.,;:")


def verify_reading(reading: PolicyReading, text: str) -> tuple[PolicyReading, list[str]]:
    """Keep one clause per flag whose quote appears in ``text``; report the rest."""
    haystack = _normalized(text)
    kept: dict[str, PolicyClause] = {}
    warnings: list[str] = []
    for clause in reading.clauses:
        quote = _normalized(clause.quote)
        if not quote or quote not in haystack:
            warnings.append(
                f"discarded constraint reading {clause.flag}: its quote is not in the constraints"
            )
        elif clause.flag not in kept:
            kept[clause.flag] = clause
    return PolicyReading(clauses=list(kept.values())), warnings


def read_policy(
    model: MinerModel | RunScopedModel, text: str
) -> tuple[PolicyReading | None, list[str]]:
    """The verified reading of ``text``; None (keyword fallback) when empty or failed."""
    if not text.strip():
        return None, []
    try:
        reading = model.call_json(
            "mapper", POLICY_READER_SYSTEM, policy_reading_prompt(text), PolicyReading
        )
    except BudgetExceeded:
        raise
    except Exception as exc:
        return None, [f"constraint reading failed ({type(exc).__name__}); used keyword fallback"]
    return verify_reading(reading, text)


__all__ = ["read_policy", "verify_reading"]
