"""Shared state for the mining pipeline StateGraph."""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict


JsonObject = dict[str, object]
BudgetState = dict[str, int | float]


class MinerState(TypedDict, total=False):
    """Pipeline state. List channels accumulate across Send fan-out branches."""

    # run setup
    workspace: str
    run_dir: str
    run_id: str
    status: Literal["running", "completed", "failed", "budget_exhausted"]
    input_kind: Literal["idea", "file", "kb"]
    input_value: str
    constraints: str
    policy_constraints: str
    constraint_params: dict[str, str]
    run_budget: BudgetState
    max_iterations: int
    created: str
    profile: str
    requested_mode: Literal["auto", "operational", "strategy"]
    analysis_mode: Literal["operational", "strategy"]
    start_ts: float
    stage_seconds: dict[str, float]
    resume: bool

    # transient (Send fan-out payloads)
    layer: str
    candidate: JsonObject
    candidate_portfolio: JsonObject

    # artifacts
    context: JsonObject
    input_assessment: JsonObject
    domain_map: JsonObject
    layer_analyses: Annotated[list[JsonObject], operator.add]
    pain_ledger: list[JsonObject]
    candidates: list[JsonObject]
    drafts: Annotated[list[JsonObject], operator.add]
    refined: list[JsonObject]
    opportunities: list[JsonObject]
    report_path: str
    summary_path: str
