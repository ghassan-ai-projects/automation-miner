"""Long runs report progress as they go, and provider spend is accounted."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from automation_miner.execution import BudgetExceeded, RunExecutionContext, StageProgress
from automation_miner.graph.runner import run_mine
from automation_miner.models.client import MinerModel
from automation_miner.models.config import load_config
from automation_miner.schemas import RunBudget


def test_progress_is_emitted_once_per_stage_in_pipeline_order(workspace: Path) -> None:
    events: list[StageProgress] = []
    run_mine(workspace_path=workspace, idea="Progress", dry_run=True, progress_callback=events.append)
    stages = [event.stage for event in events]
    assert stages[:3] == ["ingest", "input_assessment", "domain_map"]
    assert stages[-1] == "publish" and len(stages) == len(set(stages))
    assert events[-1].calls > events[2].calls > 0


def test_provider_cost_is_recorded_per_role_and_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    completion = {
        "choices": [{"message": {"content": '{"ok": true}'}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0021},
    }
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=completion)))
    model = MinerModel(load_config(None), http_client=client)
    model.chat("critic", "s", "p")
    model.chat("critic", "s", "p")
    usage = model.usage.snapshot()
    assert usage.by_role["critic"].cost_usd == 0.0042 and usage.cost_usd == 0.0042
    assert json.loads(usage.model_dump_json())["cost_usd"] == 0.0042


def test_cost_ceiling_stops_the_run() -> None:
    context = RunExecutionContext("run", RunBudget(max_cost_usd=0.01))
    context.record_cost(0.006)
    with pytest.raises(BudgetExceeded, match="max_cost_usd"):
        context.record_cost(0.006)
