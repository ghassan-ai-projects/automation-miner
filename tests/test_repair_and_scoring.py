"""Surgical repair, comparative scoring, and code-side caps on proposed scores."""

from __future__ import annotations

from typing import Any

from automation_miner.evaluation.judge import honesty_from_audit
from automation_miner.graph.repair import MAX_REPAIRABLE_DEFECTS, repair_blocked_draft
from automation_miner.graph.score_call import score_portfolio
from automation_miner.models import mock
from automation_miner.schemas import ICEScore, OpportunityDraft, RepairVerdict
from automation_miner.scoring import (
    apply_confidence_cap,
    artifact_type_for,
    evidence_confidence_cap,
)


def _draft(**update: Any) -> OpportunityDraft:
    draft = OpportunityDraft.model_validate(mock.call_json("drafter", "OpportunityDraft", ""))
    return draft.model_copy(update=update)


class ScriptedModel:
    def __init__(self, responses: dict[str, list[Any]]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def call_json(self, role: str, system: str, prompt: str, schema: type) -> Any:
        self.calls.append(schema.__name__)
        return self.responses[schema.__name__].pop(0)


def test_clean_repair_is_adopted_and_keeps_plan_links() -> None:
    original = _draft(addresses_pains=["P1"])
    repaired = _draft(problem="Clerks re-key ~9 minutes per email or paper FNOL.")
    model = ScriptedModel({"OpportunityDraft": [repaired], "RepairVerdict": [RepairVerdict()]})
    result, record = repair_blocked_draft(model, original, ['problem: "x"'], "", "")
    assert result is not None and record["adopted"]
    assert result.addresses_pains == ["P1"] and result.layer == original.layer


def test_repair_is_rejected_when_verifier_or_hygiene_objects() -> None:
    stubborn = ScriptedModel(
        {
            "OpportunityDraft": [_draft(), _draft()],
            "RepairVerdict": [RepairVerdict(unresolved=['"x"'])] * 2,
        }
    )
    assert repair_blocked_draft(stubborn, _draft(), ["d"], "", "")[0] is None
    hedged = _draft(problem="Clerks re-key claims (inferred from S2: 're-key').")
    model = ScriptedModel({"OpportunityDraft": [hedged], "RepairVerdict": [RepairVerdict()]})
    assert repair_blocked_draft(model, _draft(), ["d"], "", "")[0] is None


def test_second_round_fixes_a_defect_the_first_repair_introduced() -> None:
    fixed = _draft(problem="38% of schaden@ emails are follow-ups.")
    model = ScriptedModel(
        {
            "OpportunityDraft": [_draft(problem="~243/week are follow-ups."), fixed],
            "RepairVerdict": [RepairVerdict(new_violations=['"~243/week" wrong base']),
                              RepairVerdict()],
        }
    )
    result, record = repair_blocked_draft(model, _draft(), ['"392/week"'], "", "")
    assert result is not None and result.problem == fixed.problem
    assert [r["defects"] for r in record["rounds"]] == [['"392/week"'], ['"~243/week" wrong base']]


def test_repair_skips_drafts_that_need_a_rewrite_not_surgery() -> None:
    model = ScriptedModel({})
    result, record = repair_blocked_draft(
        model, _draft(), ["d"] * (MAX_REPAIRABLE_DEFECTS + 1), "", ""
    )
    assert result is None and "skipped" in record and model.calls == []


def _ice(i: int, c: int, e: int) -> dict[str, Any]:
    return {"impact": i, "confidence": c, "ease": e, "impact_rationale": "r",
            "confidence_rationale": "r", "ease_rationale": "r"}


def test_comparative_scoring_falls_back_for_missing_or_duplicated_ids() -> None:
    from automation_miner.schemas import PortfolioScores

    items = [("AM-001", _draft(), 8.0), ("AM-002", _draft(), 7.0), ("AM-003", _draft(), 7.5)]
    comparative = PortfolioScores.model_validate(
        {"scores": [{"am_id": "AM-001", **_ice(5, 4, 3)},
                    {"am_id": "AM-002", **_ice(2, 3, 4)},
                    {"am_id": "AM-002", **_ice(3, 3, 3)}]}
    )
    fallback = ICEScore.model_validate(_ice(3, 3, 3))
    model = ScriptedModel({"PortfolioScores": [comparative], "ICEScore": [fallback, fallback]})
    scores, missing = score_portfolio(model, items, "")
    assert scores["AM-001"].impact == 5
    assert missing == ["AM-002", "AM-003"]
    assert model.calls == ["PortfolioScores", "ICEScore", "ICEScore"]


def test_confidence_is_capped_by_the_evidence_behind_the_brief() -> None:
    estimated = _draft()  # mock impact rows are all estimates
    assert evidence_confidence_cap(estimated, "rich", "operational")[0] == 3
    assert evidence_confidence_cap(estimated, "thin", "operational")[0] == 2
    rows = [row.model_copy(update={"assumption": False}) for row in estimated.impact_analysis]
    observed = estimated.model_copy(update={"impact_analysis": rows})
    assert evidence_confidence_cap(observed, "rich", "operational")[0] == 5
    assert evidence_confidence_cap(observed, "rich", "strategy")[0] == 3
    score = ICEScore.model_validate(_ice(4, 5, 4))
    capped, notes = apply_confidence_cap(score, 3, "no impact row rests on an observed baseline")
    assert capped.confidence == 3 and notes == [
        "confidence 5 -> 3: no impact row rests on an observed baseline"
    ]


def test_framing_is_decided_in_code() -> None:
    score = ICEScore.model_validate(_ice(4, 4, 4))
    cited = _draft(evidence_refs=["S1"])
    assert artifact_type_for(score, cited, "rich", "operational") == "opportunity_brief"
    assert artifact_type_for(score, cited, "rich", "strategy") == "discovery_hypothesis"
    assert artifact_type_for(score, cited, "thin", "operational") == "discovery_hypothesis"
    assert artifact_type_for(score, _draft(), "rich", "operational") == "discovery_hypothesis"
    low = ICEScore.model_validate(_ice(4, 2, 4))
    assert artifact_type_for(low, cited, "rich", "operational") == "discovery_hypothesis"


def test_judge_honesty_is_derived_from_the_audit() -> None:
    assert [honesty_from_audit(n) for n in (0, 1, 2, 3, 4, 5, 6, 40)] == [5, 4, 3, 3, 2, 2, 1, 1]


def test_judge_samples_are_merged_by_mean_grade_and_median_fabrication() -> None:
    from automation_miner.evaluation.judge import _merge
    from automation_miner.evaluation.schemas import BriefJudgement

    def judgement(grade: int, facts: int) -> BriefJudgement:
        dims = dict.fromkeys(
            ("specificity", "insight", "actionability", "domain_expertise",
             "epistemic_honesty", "readability", "overall"), grade,
        )
        return BriefJudgement(**dims, fabricated_facts=[f"f{i}" for i in range(facts)])

    merged = _merge([judgement(2, 4), judgement(4, 0), judgement(3, 1)])
    assert merged.overall == 3 and merged.insight == 3
    assert len(merged.fabricated_facts) == 1
