"""Terminal failure recording: write the failure into the run that raised it.

Every artifact a consumer reads (manifest, summary, portfolio, report) is
marked failed, published briefs from the run are quarantined, and
``error.json`` names the stage, the budget limit that fired, and every
artifact already written — so a failed run is diagnosable from disk alone.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager
from typing import Any, Iterator, Literal

from automation_miner.artifacts.layout import RunLayout
from automation_miner.artifacts.publication import (
    mark_manifest_failed,
    mark_portfolio_failed,
    mark_summary_failed,
    quarantine_run_briefs,
    write_publication_journal,
)
from automation_miner.artifacts.registry import reindex_locked
from automation_miner.artifacts.workspace import (
    read_json,
    workspace_transaction_lock,
    write_json,
    write_text,
)
from automation_miner.execution import BudgetExceeded, RunExecutionContext
from automation_miner.schemas import PortfolioStats, StageFailure

LOGGER = logging.getLogger(__name__)


class FailureRecorder:
    """Writes one failed run's terminal state; every step is best-effort.

    A failure while recording a failure must never mask the original error,
    so each step logs its own exception and the rest still run.
    """

    def __init__(self, run_dir: Path, exc: BaseException, execution: RunExecutionContext) -> None:
        self.run_dir, self.exc, self.execution = run_dir, exc, execution
        self.layout = RunLayout(run_dir)
        self.snapshot = execution.snapshot()
        self.status: Literal["failed", "budget_exhausted"] = (
            "budget_exhausted" if isinstance(exc, BudgetExceeded) else "failed"
        )
        self.error_text = f"{type(exc).__name__}: {str(exc)[:2_000]}"
        self.quarantined: list[str] = []
        self.manifest: dict[str, Any] = {}

    @contextmanager
    def step(self, action: str) -> Iterator[None]:
        try:
            yield
        except Exception:
            LOGGER.exception(
                "Unable to %s for failed run %s at %s", action, self.run_dir.name, self.run_dir
            )

    def _telemetry(self) -> dict[str, Any]:
        return {
            "duration_seconds": self.snapshot.elapsed_seconds,
            "usage": self.execution.usage.snapshot().model_dump(mode="json"),
        }

    def quarantine(self) -> None:
        root = self.run_dir.parent.parent
        with self.step("quarantine briefs or rebuild the registry"):
            with workspace_transaction_lock(root):
                self.quarantined = quarantine_run_briefs(root, self.run_dir)
                reindex_locked(root)
        if self.layout.journal.is_file():
            with self.step("close the publication journal"):
                write_publication_journal(self.run_dir, "quarantined")

    def write_error(self) -> None:
        written = sorted(
            str(p.relative_to(self.run_dir)) for p in self.run_dir.rglob("*") if p.is_file()
        )
        snapshot = self.snapshot
        failure = StageFailure(
            run_id=self.run_dir.name, stage=snapshot.stage, error_type=type(self.exc).__name__,
            error=str(self.exc)[:2_000], created=f"{datetime.now():%Y-%m-%dT%H:%M:%S}",
            status=self.status, budget=self.execution.budget,
            budget_limit=getattr(self.exc, "limit", ""), observed_attempts=snapshot.attempts,
            observed_tokens=snapshot.tokens, stage_seconds=snapshot.stage_seconds,
            usage=self.execution.usage.snapshot(), artifacts_written=written,
            quarantined_artifacts=self.quarantined,
        )
        with self.step("persist failure artifact"):
            write_json(self.layout.error, failure)

    def mark_manifest(self) -> None:
        path = self.layout.manifest
        try:
            raw = read_json(path) if path.is_file() else {}
        except (OSError, ValueError):
            LOGGER.exception("Unable to read manifest for failed run %s", self.run_dir.name)
            raw = {}
        self.manifest = raw if isinstance(raw, dict) else {}
        if not self.manifest:
            return
        mark_manifest_failed(self.manifest, self.status)
        self.manifest.update({**self._telemetry(), "stage_seconds": self.snapshot.stage_seconds})
        with self.step("update the terminal manifest"):
            write_json(path, self.manifest)

    def mark_views(self) -> None:
        with self.step("persist the failure summary"):
            path = self.layout.summary
            summary = read_json(path) if path.is_file() else self._minimal_summary()
            if isinstance(summary, dict):
                mark_summary_failed(summary, self.status)
                summary.update(self._telemetry())
                write_json(path, summary)
        with self.step("persist the failure portfolio"):
            path = self.layout.opportunities
            portfolio = read_json(path) if path.is_file() else {}
            if isinstance(portfolio, dict):
                mark_portfolio_failed(portfolio, self.status)
                write_json(path, portfolio)
        with self.step("persist the failure report"):
            write_text(self.layout.report, self._report())

    def _report(self) -> str:
        domain = str(self.manifest.get("domain", self.run_dir.name))
        return (
            f"# Automation Mining Report: {domain}\n\n"
            f"> **Run:** `{self.run_dir.name}`  \n"
            f"> **Status:** {self.status}  \n"
            "> **Publication:** pending  \n"
            "> **Published opportunities:** 0  \n\n"
            "## Failure\n\n"
            f"- **Stage:** {self.snapshot.stage}\n"
            f"- **Error:** {self.error_text}\n"
            "- **Details:** see `error.json` and `run.json`.\n"
        )

    def _minimal_summary(self) -> dict[str, Any]:
        """A valid summary when failure precedes normal rendering."""
        m = self.manifest
        return {
            "run_id": self.run_dir.name,
            "domain": str(m.get("domain", self.run_dir.name)),
            "domain_slug": str(m.get("domain_slug", "unknown")),
            "constraints": str(m.get("constraints", "")),
            "raw_constraints": str(m.get("raw_constraints", "")),
            "constraint_params": m.get("constraint_params", {}),
            "created": str(m.get("created", "")),
            "status": self.status,
            "publication_status": "pending",
            "budget": self.execution.budget.model_dump(mode="json"),
            "dry_run": bool(m.get("dry_run", False)),
            "stats": PortfolioStats().model_dump(mode="json"),
            **self._telemetry(),
            "opportunities": [],
            "notes": [self.error_text, "See error.json for details."],
        }


def record_failure(run_dir: Path, exc: BaseException, execution: RunExecutionContext) -> None:
    """Persist terminal failure state into the exact run that raised."""
    recorder = FailureRecorder(run_dir, exc, execution)
    recorder.quarantine()
    recorder.write_error()
    recorder.mark_manifest()
    recorder.mark_views()
