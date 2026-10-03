"""Review stages: critique with surgical repair, comparative scoring, ranking."""

from __future__ import annotations

import time
from typing import Any

from automation_miner.artifacts.workspace import write_json
from automation_miner.context import draft_query, render_chunks
from automation_miner.graph.loop import run_critique_loop
from automation_miner.graph.publish import publish_run
from automation_miner.graph.repair import repair_blocked_draft, repair_note
from automation_miner.graph.score_call import score_portfolio
from automation_miner.graph.stages.base import StageBase, Update, layout_of, parallel_map
from automation_miner.graph.state import MinerState
from automation_miner.schemas import (
    LAYER_ORDER,
    ICEScore,
    Level,
    ContextPacket,
    Layer,
    Opportunity,
    OpportunityDraft,
    Tier,
)
from automation_miner.scoring import (
    apply_confidence_cap,
    artifact_type_for,
    apply_constraint_overrides,
    apply_portfolio_policy,
    compute_ice,
    evidence_confidence_cap,
    context_policy,
    validate_coherence,
)


class ReviewStages(StageBase):
    def _critique_evidence(self, state: MinerState, draft: OpportunityDraft) -> str:
        """Built once per opportunity and reused across every critique round."""
        ctx = ContextPacket.model_validate(state["context"])
        query = draft_query(draft.layer, [draft.title, draft.problem], ctx.domain)
        selected = self._index(state).select(
            query, self.budget.critique_tokens, pinned=draft.evidence_refs
        )
        return render_chunks(selected)

    def _unblock(
        self, state: MinerState, am_id: str, final: OpportunityDraft, chosen: dict[str, Any],
        evidence: str,
    ) -> tuple[OpportunityDraft, list[str], list[str]]:
        """Surgical repair of a blocked draft: (draft, gate reasons, repair notes)."""
        gate_reasons = list(chosen["gate_reasons"])
        if not gate_reasons:
            return final, [], []
        critique = chosen["critique"]
        defects = critique["grounding_violations"] + critique["constraint_violations"]
        constraints = ContextPacket.model_validate(state["context"]).constraints
        repaired, record = repair_blocked_draft(self.model, final, defects, evidence, constraints)
        write_json(layout_of(state).critique / f"{am_id}.repair.json", record)
        if repaired is None:
            return final, gate_reasons, []
        return repaired, [], [repair_note(defects)]

    def _review_one(
        self, state: MinerState, am_id: str, draft: OpportunityDraft, others: list[str]
    ) -> dict[str, Any]:
        """Critique loop for one draft, then a surgical repair if it ended blocked."""
        ctx = ContextPacket.model_validate(state["context"])
        evidence = self._critique_evidence(state, draft)
        final, history = run_critique_loop(
            self.model, draft, others, state["max_iterations"], evidence, ctx.constraints
        )
        for entry in history:
            write_json(layout_of(state).critique_round(am_id, entry["version"]), entry)
        chosen = next(entry for entry in history if entry["selected"])
        final, gate_reasons, notes = self._unblock(state, am_id, final, chosen, evidence)
        return {
            "am_id": am_id, "domain": ctx.domain, "domain_slug": ctx.domain_slug,
            "draft": final.model_dump(mode="json"), "critique_overall": chosen["overall"],
            "quality_gate_reasons": gate_reasons, "repair_notes": notes,
            "iterations": len(history),
        }

    def critique_refine(self, state: MinerState) -> Update:
        self._mark_stage("critique_refine")
        started = time.time()
        ordered = [
            OpportunityDraft.model_validate(d)
            for d in sorted(
                state["drafts"],
                key=lambda d: (LAYER_ORDER.index(Layer(str(d["layer"]))), str(d["title"])),
            )
        ]
        reserved = self.workspace.reserve_am_numbers(len(ordered))
        titles = [draft.title for draft in ordered]

        def process(position: int) -> dict[str, Any]:
            others = [t for i, t in enumerate(titles) if i != position]
            am_id = f"AM-{reserved[position]:03d}"
            return self._review_one(state, am_id, ordered[position], others)

        workers = self.model.config.workers_for("critique")
        refined = parallel_map(process, range(len(ordered)), workers)
        return {"refined": refined, "stage_seconds": self._timed(state, "critique_refine", started)}

    def _validated(
        self, state: MinerState, draft: OpportunityDraft, proposed: ICEScore, fallback: bool
    ) -> tuple[ICEScore, Level, list[str], list[str]]:
        """Coherence caps, evidence cap, then constraint overrides.

        Returns (score, overridden risk, calibration notes, applied overrides).
        """
        ctx = ContextPacket.model_validate(state["context"])
        unresolved = [ref for ref in draft.evidence_refs if ref not in ctx.chunk_ids()]
        score, calibration = validate_coherence(proposed, draft, unresolved)
        cap = evidence_confidence_cap(draft, ctx.retained_quality.level, state["analysis_mode"])
        score, capped = apply_confidence_cap(score, *cap)
        calibration += capped
        if fallback:
            calibration.append("scored individually: missing from the comparative call")
        score, risk, applied = apply_constraint_overrides(
            score, draft.risk_level, context_policy(ctx)
        )
        return score, risk, calibration, applied

    def _scored(
        self, state: MinerState, item: dict[str, Any], draft: OpportunityDraft,
        proposed: ICEScore, fallback: bool,
    ) -> dict[str, Any]:
        score, risk, calibration, applied = self._validated(state, draft, proposed, fallback)
        ctx = ContextPacket.model_validate(state["context"])
        ice = compute_ice(score.impact, score.confidence, score.ease)
        keep = ("am_id", "domain", "domain_slug", "critique_overall", "iterations",
                "quality_gate_reasons")
        return Opportunity.model_validate(
            {
                **{key: item[key] for key in keep},
                "draft": draft.model_copy(update={"risk_level": risk}), "score": score,
                "ice": ice, "tier": Tier.for_ice(ice), "overrides_applied": applied,
                "calibration": calibration, "source_risk_level": draft.risk_level,
                "unresolved_refs": [r for r in draft.evidence_refs if r not in ctx.chunk_ids()],
                "repair_notes": item.get("repair_notes", []),
                "artifact_type": artifact_type_for(
                    score, draft, ctx.retained_quality.level, state["analysis_mode"]
                ),
            }
        ).model_dump(mode="json")

    def score(self, state: MinerState) -> Update:
        """LLM proposes factors side by side; code validates, caps, and overrides."""
        self._mark_stage("score")
        started = time.time()
        drafts = [OpportunityDraft.model_validate(item["draft"]) for item in state["refined"]]
        items = [
            (str(item["am_id"]), draft, float(str(item["critique_overall"])))
            for item, draft in zip(state["refined"], drafts, strict=True)
        ]
        proposed, fallback = score_portfolio(self.model, items, state["constraints"])
        opportunities = [
            self._scored(state, item, draft, proposed[am_id], am_id in fallback)
            for item, (am_id, draft, _) in zip(state["refined"], items, strict=True)
        ]
        return {"opportunities": opportunities, "stage_seconds": self._timed(state, "score", started)}

    def rank_filter(self, state: MinerState) -> Update:
        self._mark_stage("rank_filter")
        started = time.time()
        ranked = apply_portfolio_policy(
            [Opportunity.model_validate(o) for o in state["opportunities"]],
            policy=context_policy(ContextPacket.model_validate(state["context"])),
        )
        return {
            "opportunities": [o.model_dump(mode="json") for o in ranked],
            "stage_seconds": self._timed(state, "rank_filter", started),
        }

    def publish(self, state: MinerState) -> Update:
        self._mark_stage("publish")
        started = time.time()
        return publish_run(
            state,
            self.model,
            self.workspace,
            self.execution,
            lambda: self._timed(state, "publish", started),
        )
