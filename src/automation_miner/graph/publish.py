"""The publication transaction: the last stage of a run.

Briefs are staged inside the run directory, the manifest and views are
written, staged briefs are promoted into ``opps/``, and the registry is rebuilt
under the workspace lock. The publication journal records every step so a
crash at any point is recoverable (see ``artifacts/publication.py``).
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from automation_miner.artifacts.briefs import render_brief, title_slug
from automation_miner.artifacts.layout import LAYOUT_VERSION, RunLayout
from automation_miner.artifacts.publication import (
    complete_publication_views,
    promote_publication,
    write_publication_journal,
)
from automation_miner.artifacts.registry import reindex_locked
from automation_miner.artifacts.reports import render_report, render_run_md, render_summary
from automation_miner.artifacts.workspace import (
    Workspace,
    workspace_transaction_lock,
    write_json,
    write_text,
)
from automation_miner.execution import RunExecutionContext
from automation_miner.graph.state import MinerState
from automation_miner.models.client import MinerModel, RunScopedModel
from automation_miner.prompts import PROMPT_VERSION
from automation_miner.schemas import (
    ContextPacket,
    DomainMap,
    LayerAnalysis,
    RankedPain,
    Opportunity,
    RunBudget,
    RunManifest,
)
from automation_miner.scoring import portfolio_stats, published


def _now() -> str:
    return f"{datetime.now():%Y-%m-%dT%H:%M:%S}"


class Publication:
    """One run's publication transaction, broken into its recoverable steps."""

    def __init__(
        self,
        state: MinerState,
        model: MinerModel | RunScopedModel,
        workspace: Workspace,
        execution: RunExecutionContext | None,
    ) -> None:
        self.state, self.model, self.workspace, self.execution = state, model, workspace, execution
        self.run_dir = Path(state["run_dir"])
        self.layout = RunLayout(self.run_dir)
        self.ctx = ContextPacket.model_validate(state["context"])
        self.ranked = [Opportunity.model_validate(o) for o in state["opportunities"]]
        self.live = published(self.ranked)
        self.stats = portfolio_stats(self.ranked)
        self.budget = RunBudget.model_validate(state["run_budget"])
        self.duration = round(time.time() - state.get("start_ts", time.time()), 2)
        self.files: list[dict[str, str]] = []
        self.brief_paths: dict[str, str] = {}

    def stage_briefs(self) -> None:
        """Render every published brief into the run's staging area."""
        labels = {
            chunk.id: chunk.source + (f" {chunk.locator}" if chunk.locator else "")
            for chunk in self.ctx.chunks
        }
        slug = self.ctx.domain_slug
        for opp in self.live:
            name = f"{opp.am_id}-{title_slug(opp.draft.title)}.md"
            staged = self.layout.publication / slug / name
            target = self.workspace.opps_dir / slug / name
            brief = render_brief(
                opp, self.state["run_id"], input_quality=self.ctx.input_quality,
                evidence_labels=labels,
            )
            write_text(staged, brief)
            self.brief_paths[opp.am_id] = str(target)
            self.files.append(
                {
                    "staged": str(staged.relative_to(self.run_dir)),
                    "target": str(target.relative_to(self.workspace.root)),
                }
            )

    def write_portfolio(self) -> None:
        write_json(
            self.layout.opportunities,
            {
                "run_id": self.state["run_id"],
                "layout": LAYOUT_VERSION,
                "domain": self.ctx.domain,
                "opportunities": [o.model_dump(mode="json") for o in self.ranked],
                "stats": self.stats.model_dump(mode="json"),
                "filters": self.stats.filters,
            },
        )

    def _identity(self) -> dict[str, Any]:
        state, ctx = self.state, self.ctx
        return {
            "run_id": state["run_id"],
            "domain": ctx.domain,
            "domain_slug": ctx.domain_slug,
            "constraints": ctx.constraints,
            "raw_constraints": ctx.raw_constraints,
            "constraint_params": ctx.constraint_params,
            "source_kind": ctx.source_kind,
            "source_value": state["input_value"],
            "analysis_mode": state["analysis_mode"],
            "requested_mode": state["requested_mode"],
            "created": state["created"],
            "max_iterations": state["max_iterations"],
            "profile": state.get("profile", "default"),
        }

    def manifest(self, stage_seconds: dict[str, float]) -> RunManifest:
        return RunManifest.model_validate(
            {
                **self._identity(),
                "finished": _now(),
                "duration_seconds": self.duration,
                "config_source": self.model.config.source,
                "prompt_version": PROMPT_VERSION,
                "dry_run": self.model.dry_run,
                "models": self.model.routing_table(),
                "opportunities": [o.am_id for o in self.live],
                "filtered": [o.am_id for o in self.ranked if not o.published],
                "stage_seconds": stage_seconds,
                "usage": self.model.usage.snapshot(),
                "context": self.ctx.stats,
                "input_quality": self.ctx.input_quality,
                "retained_quality": self.ctx.retained_quality,
                "status": "completed",
                "publication_status": "pending",
                "budget": self.budget,
            }
        )

    def write_views(self) -> None:
        """Summary, run log, and report: the human and agent views of the result."""
        usage = self.model.usage.snapshot()
        state = self.state
        summary = render_summary(
            run_id=state["run_id"], context=self.ctx, ranked=self.ranked, stats=self.stats,
            usage=usage, created=state["created"], duration_seconds=self.duration,
            dry_run=self.model.dry_run, brief_paths=self.brief_paths, status="completed",
            publication_status="pending", budget=self.budget,
        )
        write_json(self.layout.summary, summary)
        domain_map = DomainMap.model_validate(state["domain_map"])
        analyses = [LayerAnalysis.model_validate(a) for a in state["layer_analyses"]]
        write_text(
            self.layout.run_log,
            render_run_md(
                state["run_id"], self.ctx, domain_map, analyses, self.ranked, self.stats, usage
            ),
        )
        ledger = [RankedPain.model_validate(pain) for pain in state.get("pain_ledger", [])]
        report = render_report(
            run_id=state["run_id"], context=self.ctx, ranked=self.ranked, stats=self.stats,
            usage=usage, models=self.model.routing_table(), status="completed",
            publication_status="pending", budget=self.budget, pain_ledger=ledger,
        )
        write_text(self.layout.report, report)

    def commit(self, manifest: RunManifest) -> None:
        """Mark the manifest and views complete and rebuild the registry, atomically."""
        with workspace_transaction_lock(self.workspace.root):
            write_json(
                self.layout.manifest,
                manifest.model_copy(update={"finished": _now(), "publication_status": "complete"}),
            )
            write_publication_journal(self.run_dir, "manifest_complete", files=self.files)
            complete_publication_views(self.run_dir)
            reindex_locked(self.workspace.root)
            write_publication_journal(self.run_dir, "complete", files=self.files)

    def publish(self, manifest: RunManifest) -> None:
        """Journalled sequence: stage, promote, write views, commit."""
        write_json(self.layout.manifest, manifest)
        write_publication_journal(self.run_dir, "staged", files=self.files)
        promote_publication(self.run_dir, self.workspace.root, self.files)
        self.write_views()
        write_publication_journal(self.run_dir, "views_written", files=self.files)
        self.check_deadline()
        self.commit(manifest)
        self.check_deadline()

    def check_deadline(self) -> None:
        if self.execution is not None:
            self.execution.remaining_seconds()


def publish_run(
    state: MinerState,
    model: MinerModel | RunScopedModel,
    workspace: Workspace,
    execution: RunExecutionContext | None,
    timed: Callable[[], dict[str, float]],
) -> dict[str, Any]:
    """Stage, record, and promote one completed run's portfolio."""
    publication = Publication(state, model, workspace, execution)
    publication.stage_briefs()
    publication.write_portfolio()
    stage_seconds = timed()
    if execution is not None:
        stage_seconds = {**execution.snapshot().stage_seconds, **stage_seconds}
    publication.publish(publication.manifest(stage_seconds))
    return {
        "report_path": str(publication.layout.report),
        "summary_path": str(publication.layout.summary),
        "status": "completed",
        "stage_seconds": stage_seconds,
    }
