"""Shared plumbing for pipeline stages: timing, evidence index, run layout."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, TypeVar

from pydantic import BaseModel

from automation_miner.artifacts.layout import RunLayout
from automation_miner.artifacts.workspace import Workspace, read_json
from automation_miner.context import ContextBudget, EvidenceIndex
from automation_miner.execution import RunExecutionContext
from automation_miner.graph.state import MinerState
from automation_miner.models.client import MinerModel, RunScopedModel
from automation_miner.schemas import Chunk, InputQuality

Update = dict[str, Any]
M = TypeVar("M", bound=BaseModel)


class StageBase:
    """Binds the stages to one model client, workspace, and context budget."""

    def __init__(
        self,
        model: MinerModel | RunScopedModel,
        workspace: Workspace,
        budget: ContextBudget | None = None,
        preflight_callback: Callable[[InputQuality], None] | None = None,
    ) -> None:
        self.model = model
        self.workspace = workspace
        self.budget = budget or ContextBudget.from_config(model.config.context)
        self.preflight_callback = preflight_callback
        self.execution: RunExecutionContext | None = (
            model.execution if isinstance(model, RunScopedModel) else None
        )

    def _mark_stage(self, stage: str) -> None:
        if self.execution is not None:
            self.execution.set_stage(stage)
            self.execution.remaining_seconds()

    def _timed(self, state: MinerState, stage: str, started: float) -> dict[str, float]:
        elapsed = round(time.time() - started, 2)
        if self.execution is not None:
            self.execution.record_stage(stage, elapsed)
        return {**state.get("stage_seconds", {}), stage: elapsed}

    def _record_worker(self, stage: str, started: float) -> None:
        """Fan-out workers record their own duration; the slowest one wins."""
        if self.execution is not None:
            self.execution.record_stage(stage, time.time() - started)
            self.execution.remaining_seconds()

    @staticmethod
    def _reuse(state: MinerState, path: Path, schema: type[M]) -> M | None:
        """On resume, the stage's persisted artifact instead of a new model call."""
        if not state.get("resume") or not path.is_file():
            return None
        try:
            return schema.model_validate(read_json(path))
        except (OSError, ValueError):
            return None

    @staticmethod
    def _index(state: MinerState) -> EvidenceIndex:
        chunks = state["context"].get("chunks", [])
        if not isinstance(chunks, list):
            raise ValueError("context chunks must be a list")
        return EvidenceIndex([Chunk.model_validate(chunk) for chunk in chunks])


def layout_of(state: MinerState) -> RunLayout:
    return RunLayout(Path(state["run_dir"]))


def parallel_map(
    fn: Callable[[Any], dict[str, Any]], items: Any, workers: int
) -> list[dict[str, Any]]:
    """Map over items, preserving input order so runs stay reproducible."""
    materialized = list(items)
    if workers <= 1 or len(materialized) <= 1:
        return [fn(item) for item in materialized]
    with ThreadPoolExecutor(max_workers=min(workers, len(materialized))) as pool:
        return list(pool.map(fn, materialized))


def to_json(value: Any) -> str:
    return json.dumps(value, indent=2, default=str)
