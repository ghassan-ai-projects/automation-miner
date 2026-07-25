"""Shared state for the mining pipeline StateGraph."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class MinerState(TypedDict, total=False):
    """Pipeline state. List channels accumulate across Send fan-out branches."""

    # run setup
    workspace: str
    run_dir: str
    run_id: str
    input_kind: str  # idea | file | kb
    input_value: str
    constraints: str
    constraint_params: dict[str, str]
    max_iterations: int
    created: str
    profile: str
    requested_mode: str
    analysis_mode: str
    start_ts: float
    stage_seconds: dict[str, float]

    # transient (Send fan-out payloads)
    layer: str
    analysis: dict[str, Any]
    candidate: dict[str, Any]
    candidate_portfolio: dict[str, Any]

    # artifacts
    context: dict[str, Any]
    input_assessment: dict[str, Any]
    domain_map: dict[str, Any]
    layer_analyses: Annotated[list[dict[str, Any]], operator.add]
    candidates: list[dict[str, Any]]
    drafts: Annotated[list[dict[str, Any]], operator.add]
    refined: list[dict[str, Any]]
    opportunities: list[dict[str, Any]]
    report_path: str
    summary_path: str
