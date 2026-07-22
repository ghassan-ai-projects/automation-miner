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
    max_iterations: int
    created: str
    profile: str
    start_ts: float

    # transient (Send fan-out payloads)
    layer: str
    analysis: dict[str, Any]

    # artifacts
    context: dict[str, Any]
    domain_map: dict[str, Any]
    layer_analyses: Annotated[list[dict[str, Any]], operator.add]
    drafts: Annotated[list[dict[str, Any]], operator.add]
    refined: list[dict[str, Any]]
    opportunities: list[dict[str, Any]]
    report_path: str
