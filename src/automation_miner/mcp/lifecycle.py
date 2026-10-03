"""MCP handlers for what happens after a run: one-pager export, status, outcomes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from automation_miner.artifacts.lifecycle import outcome_rows, record_outcome, set_status
from automation_miner.mcp.errors import MCPError, MCPErrorCode

_VERDICTS = ("met", "partial", "missed")


def _text(args: dict[str, Any], key: str, required: bool = False) -> str:
    value = args.get(key, "")
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise MCPError(MCPErrorCode.VALIDATION_ERROR, f"{key} must be a string")
    if required and not str(value).strip():
        raise MCPError(MCPErrorCode.VALIDATION_ERROR, f"{key} is required")
    return str(value)


def _not_found_or_invalid(exc: Exception) -> MCPError:
    code = MCPErrorCode.NOT_FOUND if "not found" in str(exc) else MCPErrorCode.VALIDATION_ERROR
    return MCPError(code, str(exc))


def set_opportunity_status(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    try:
        event = set_status(
            root, _text(args, "am_id", True), _text(args, "status", True), _text(args, "note")
        )
    except ValueError as exc:
        raise _not_found_or_invalid(exc) from exc
    return event.model_dump(mode="json")


def record_opportunity_outcome(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    verdict = args.get("verdict")
    if verdict is not None and verdict not in _VERDICTS:
        raise MCPError(MCPErrorCode.VALIDATION_ERROR, "verdict must be met, partial, or missed")
    try:
        event = record_outcome(
            root, _text(args, "am_id", True), _text(args, "metric", True),
            _text(args, "measured", True), baseline=_text(args, "baseline"),
            verdict=verdict, note=_text(args, "note"),
        )
    except ValueError as exc:
        raise _not_found_or_invalid(exc) from exc
    return event.model_dump(mode="json")


def export_one_pager_tool(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    from automation_miner.artifacts.export import export_one_pager
    from automation_miner.artifacts.workspace import Workspace

    try:
        run_dir = Workspace(root).run_summary_path(_text(args, "run_id", True)).parent
        top = int(args.get("top", 5))
        path = export_one_pager(run_dir, root, top=top)
    except (TypeError, ValueError) as exc:
        raise _not_found_or_invalid(exc) from exc
    return {"path": str(path), "bytes": path.stat().st_size}


def list_outcomes(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    rows = outcome_rows(root)
    return {"outcomes": rows, "count": len(rows)}


LIFECYCLE_SCHEMAS: dict[str, dict[str, Any]] = {
    "set_opportunity_status": {
        "type": "object",
        "properties": {
            "am_id": {"type": "string", "description": "e.g. AM-001"},
            "status": {
                "type": "string",
                "enum": ["identified", "evaluating", "designing", "implementing", "live",
                         "deprecated"],
            },
            "note": {"type": "string", "default": ""},
        },
        "required": ["am_id", "status"],
    },
    "record_opportunity_outcome": {
        "type": "object",
        "properties": {
            "am_id": {"type": "string"},
            "metric": {
                "type": "string",
                "description": "Success-measure number from the brief ('1'), or a metric name.",
            },
            "measured": {"type": "string", "description": "Measured value, with units."},
            "baseline": {"type": "string", "default": ""},
            "verdict": {"type": "string", "enum": list(_VERDICTS)},
            "note": {"type": "string", "default": ""},
        },
        "required": ["am_id", "metric", "measured"],
    },
    "list_outcomes": {"type": "object", "properties": {}},
    "export_one_pager": {
        "type": "object",
        "properties": {
            "run_id": {"type": "string"},
            "top": {"type": "integer", "minimum": 1, "maximum": 50, "default": 5},
        },
        "required": ["run_id"],
    },
}

LIFECYCLE_DESCRIPTIONS = {
    "set_opportunity_status": (
        "Move a published brief through its lifecycle (identified → evaluating → designing "
        "→ implementing → live, or deprecated). Recorded in lifecycle.json and the brief."
    ),
    "record_opportunity_outcome": (
        "Record a measured result against one of a brief's success measures, with an "
        "optional baseline and a met/partial/missed verdict."
    ),
    "list_outcomes": (
        "Every measured outcome joined with the ICE score its brief was published at — "
        "evidence for whether high-scoring ideas deliver."
    ),
}

LIFECYCLE_DESCRIPTIONS["export_one_pager"] = (
    "Write a completed run's stakeholder one-pager: a self-contained HTML page with the "
    "recommended opportunities, first steps, success measures, and risks. Returns its path."
)

LIFECYCLE_HANDLERS = {
    "export_one_pager": export_one_pager_tool,
    "set_opportunity_status": set_opportunity_status,
    "record_opportunity_outcome": record_opportunity_outcome,
    "list_outcomes": list_outcomes,
}
