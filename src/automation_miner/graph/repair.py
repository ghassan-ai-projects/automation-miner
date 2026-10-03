"""Surgical repair of a strong draft blocked by a few specific defects.

In the first improved run the portfolio's best idea (ICE 36, a pre-billing
screen worth ~EUR 780k/yr) was filtered for one unsupported half-sentence, and
the full-rewrite refiner made the draft worse (critic 8.2 -> 6.8) instead of
fixing it. A blocked draft now gets one targeted repair: the repair role fixes
exactly the quoted defects and copies everything else through, a verifier
checks only those defects plus anything new, and code re-checks prose hygiene.
The repair is adopted only when all three are clean; otherwise the original
block stands and stays visible.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from automation_miner.derivations import arithmetic_issues, check_derivations, verified_notes
from automation_miner.hygiene import draft_hedges
from automation_miner.prompts import (
    REPAIR_SYSTEM,
    VERIFIER_SYSTEM,
    repair_prompt,
    verify_prompt,
)
from automation_miner.schemas import OpportunityDraft, RepairVerdict

if TYPE_CHECKING:
    from automation_miner.models.client import MinerModel, RunScopedModel

# Repair is for a near-miss, not a rewrite: a draft with more blocking defects
# than this needs another full critique round, not surgery.
MAX_REPAIRABLE_DEFECTS = 4
# A verifier can find a second defect the first repair introduced (a real run
# replaced one wrong derived count with another); one more pass fixes those.
MAX_REPAIR_ROUNDS = 2


def _repair_once(
    model: MinerModel | RunScopedModel, draft: OpportunityDraft, defects: list[str],
    evidence: str, constraints: str,
) -> tuple[OpportunityDraft, RepairVerdict, int]:
    prompt = repair_prompt(draft.model_dump_json(), defects, evidence, constraints)
    repaired = model.call_json("refiner", REPAIR_SYSTEM, prompt, OpportunityDraft)
    repaired = repaired.model_copy(
        update={"layer": draft.layer, "addresses_pains": draft.addresses_pains}
    )
    checks = check_derivations(repaired)
    check = verify_prompt(
        repaired.model_dump_json(), defects, evidence, constraints, verified_notes(checks)
    )
    verdict = model.call_json("critic", VERIFIER_SYSTEM, check, RepairVerdict)
    # A repair that breaks its own arithmetic is not clean, whatever the verifier says.
    return repaired, verdict, len(draft_hedges(repaired)) + len(arithmetic_issues(checks))


def repair_blocked_draft(
    model: MinerModel | RunScopedModel, draft: OpportunityDraft, defects: list[str],
    evidence: str, constraints: str,
) -> tuple[OpportunityDraft | None, dict[str, Any]]:
    """Return the repaired draft (or None) and a record for the run trace."""
    record: dict[str, Any] = {"defects": defects, "adopted": False, "rounds": []}
    if not defects or len(defects) > MAX_REPAIRABLE_DEFECTS:
        record["skipped"] = f"{len(defects)} defects is outside the repairable range"
        return None, record
    current, open_defects = draft, defects
    for _ in range(MAX_REPAIR_ROUNDS):
        current, verdict, hedges = _repair_once(model, current, open_defects, evidence, constraints)
        record["rounds"].append({"defects": open_defects, "verdict": verdict.model_dump(), "hedges": hedges})
        if verdict.clean and not hedges:
            record.update({"adopted": True, "draft": current.model_dump(mode="json")})
            return current, record
        open_defects = verdict.unresolved + verdict.new_violations
        if not open_defects or len(open_defects) > MAX_REPAIRABLE_DEFECTS:
            break
    return None, record


def repair_note(defects: list[str]) -> str:
    count = len(defects)
    return (
        f"repaired {count} blocking defect{'s' if count != 1 else ''} surgically; "
        "an independent verification found no remaining or new violations"
    )
