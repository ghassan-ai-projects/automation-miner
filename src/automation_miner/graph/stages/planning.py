"""Planning stages: pain ledger, portfolio plan with coverage check, drafting."""

from __future__ import annotations

import time
from typing import Any

from langgraph.types import Send

from automation_miner.artifacts.briefs import title_slug
from automation_miner.artifacts.workspace import read_json, write_json
from automation_miner.context import draft_query, render_chunks
from automation_miner.discovery import (
    rank_pains,
    coverage_report,
    ledger_records,
    render_ledger,
    same_domain,
    uncovered_pains,
)
from automation_miner.graph.stages.base import StageBase, Update, layout_of, to_json
from automation_miner.graph.state import MinerState
from automation_miner.prompts import (
    DRAFTER_SYSTEM,
    PORTFOLIO_PLANNER_SYSTEM,
    candidate_draft_prompt,
    coverage_revision_prompt,
    portfolio_plan_prompt,
)
from automation_miner.consolidation import consolidate, consolidated_pool, raw_pool
from automation_miner.schemas import (
    PainConsolidation,
    LAYER_ORDER,
    CandidatePortfolio,
    ContextPacket,
    Layer,
    LayerAnalysis,
    OpportunityCandidate,
    OpportunityDraft,
    RankedPain,
)


class PlanningStages(StageBase):
    def _prior_ideas(self, domain_slug: str) -> list[dict[str, Any]]:
        """Recent published ideas for this domain, so a re-run does not repeat itself.

        Only the same domain counts (matched by slug words, so differently named
        inputs about one domain share memory); unrelated domains are noise.
        """
        path = self.workspace.root / "registry.json"
        if not path.is_file():
            return []
        try:
            entries = read_json(path).get("entries", [])
        except (OSError, ValueError):
            return []
        return [
            {
                "id": entry.get("i", ""),
                "title": entry.get("t", ""),
                "layer": entry.get("l", ""),
                "domain": entry.get("d", ""),
            }
            for entry in entries
            if same_domain(domain_slug, str(entry.get("d", "")))
        ][-50:]

    def _plan(
        self, state: MinerState, analyses: list[LayerAnalysis], ledger: list[RankedPain]
    ) -> tuple[CandidatePortfolio, list[RankedPain]]:
        """Plan against the ledger; revise once if top pains are uncovered."""
        ctx = ContextPacket.model_validate(state["context"])
        prompt = portfolio_plan_prompt(
            to_json(state["domain_map"]), to_json([a.model_dump(mode="json") for a in analyses]),
            ctx.overview, ctx.constraints, to_json(self._prior_ideas(ctx.domain_slug)),
            render_ledger(ledger),
        )
        plan = self.model.call_json("drafter", PORTFOLIO_PLANNER_SYSTEM, prompt, CandidatePortfolio)
        gap = uncovered_pains(ledger, plan)
        if gap:
            revision = coverage_revision_prompt(
                plan.model_dump_json(indent=2), render_ledger(gap), ctx.constraints
            )
            plan = self.model.call_json(
                "drafter", PORTFOLIO_PLANNER_SYSTEM, revision, CandidatePortfolio
            )
        return plan, gap

    def _ledger(
        self, state: MinerState, analyses: list[LayerAnalysis]
    ) -> tuple[list[RankedPain], list[str]]:
        """Consolidate and size the analysts' pains once (reused on resume), then rank."""
        layout, pool = layout_of(state), raw_pool(analyses)
        consolidation = self._reuse(state, layout.pain_consolidation, PainConsolidation)
        notes: list[str] = []
        if consolidation is None:
            ctx = ContextPacket.model_validate(state["context"])
            result, notes = consolidate(self.model, pool, ctx.overview)
            consolidation = result or PainConsolidation()
            write_json(layout.pain_consolidation, consolidation)
        merged, merge_notes = consolidated_pool(consolidation, pool)
        return rank_pains(merged), notes + merge_notes

    def plan_portfolio(self, state: MinerState) -> Update:
        """Rank pains in code, plan against them, and revise once for coverage."""
        self._mark_stage("plan_portfolio")
        started = time.time()
        analyses = sorted(
            (LayerAnalysis.model_validate(a) for a in state["layer_analyses"]),
            key=lambda a: LAYER_ORDER.index(a.layer),
        )
        ledger, notes = self._ledger(state, analyses)
        layout = layout_of(state)
        cached = self._reuse(state, layout.candidate_portfolio, CandidatePortfolio)
        if cached is not None:
            return self._planned(state, cached, ledger, started)
        plan, gap = self._plan(state, analyses, ledger)
        coverage = {
            **coverage_report(ledger, plan), "revised_for": [pain.id for pain in gap],
            "notes": notes,
        }
        write_json(layout.candidate_portfolio, plan)
        write_json(layout.pain_ledger, {"pains": ledger_records(ledger), "coverage": coverage})
        return self._planned(state, plan, ledger, started)

    def _planned(
        self,
        state: MinerState,
        result: CandidatePortfolio,
        ledger: list[RankedPain],
        started: float,
    ) -> Update:
        return {
            "candidates": [candidate.model_dump(mode="json") for candidate in result.candidates],
            "candidate_portfolio": result.model_dump(mode="json"),
            "pain_ledger": [pain.model_dump(mode="json") for pain in ledger],
            "stage_seconds": self._timed(state, "plan_portfolio", started),
        }

    @staticmethod
    def fanout_candidates(state: MinerState) -> list[Send]:
        shared = {
            "context": state["context"],
            "domain_map": state["domain_map"],
            "run_dir": state["run_dir"],
            "constraints": state["constraints"],
            "analysis_mode": state["analysis_mode"],
            "candidate_portfolio": state["candidate_portfolio"],
            "pain_ledger": state.get("pain_ledger", []),
            "resume": state.get("resume", False),
        }
        return [
            Send("draft_candidate", {**shared, "candidate": candidate})
            for candidate in state["candidates"]
        ]

    def _draft_evidence(self, state: MinerState, candidate: OpportunityCandidate) -> str:
        """Most relevant chunks, always including the evidence behind the pains
        this candidate removes, whatever BM25 ranks highest for its title."""
        ctx = ContextPacket.model_validate(state["context"])
        ledger = [RankedPain.model_validate(p) for p in state.get("pain_ledger", [])]
        pain_refs = [
            ref for pain in ledger if pain.id in candidate.addresses_pains
            for ref in pain.evidence_refs
        ]
        terms = [candidate.title, candidate.value_thesis, candidate.differentiation]
        selected = self._index(state).select(
            draft_query(candidate.layer, terms, ctx.domain), self.budget.draft_tokens,
            pinned=list(dict.fromkeys([*candidate.evidence_refs, *pain_refs])),
        )
        return render_chunks(selected)

    def draft_candidate(self, state: MinerState) -> Update:
        self._mark_stage("draft_opportunities")
        started = time.time()
        candidate = OpportunityCandidate.model_validate(state["candidate"])
        draft_path = layout_of(state).candidate_draft(title_slug(candidate.title))
        cached = self._reuse(state, draft_path, OpportunityDraft)
        if cached is not None:
            return {"drafts": [cached.model_dump(mode="json")]}
        ctx = ContextPacket.model_validate(state["context"])
        prompt = candidate_draft_prompt(
            candidate.model_dump_json(indent=2), to_json(state["candidate_portfolio"]),
            self._draft_evidence(state, candidate), ctx.constraints,
            to_json(state["domain_map"]), state["analysis_mode"],
        )
        draft = self.model.call_json("drafter", DRAFTER_SYSTEM, prompt, OpportunityDraft)
        draft = draft.model_copy(
            update={"layer": Layer(candidate.layer), "addresses_pains": candidate.addresses_pains}
        )
        write_json(draft_path, draft)
        self._record_worker("draft_opportunities", started)
        return {"drafts": [draft.model_dump(mode="json")]}
