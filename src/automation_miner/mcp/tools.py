"""MCP tool handlers — pure Python, no mcp import, directly testable.

Every handler takes (workspace_root, args) and returns a JSON-able dict.
``dispatch`` wraps them in the success/error envelope.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from automation_miner import __version__
from automation_miner.artifacts.registry import reindex
from automation_miner.artifacts.workspace import Workspace, read_json
from automation_miner.mcp.errors import MCPError, MCPErrorCode, MCPResponse
from automation_miner.models.config import load_config

INPUT_TYPES = ("auto", "idea", "file", "kb")


def _mine_domain(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    from automation_miner.graph.build import run_mine

    input_value = args.get("input", "")
    if not isinstance(input_value, str) or not input_value.strip():
        raise MCPError(MCPErrorCode.VALIDATION_ERROR, "input is required")
    raw_input = input_value.strip()
    input_type = str(args.get("input_type", "auto"))
    if input_type not in INPUT_TYPES:
        raise MCPError(
            MCPErrorCode.VALIDATION_ERROR,
            f"input_type must be one of {INPUT_TYPES}",
        )
    path = Path(raw_input)
    if input_type == "auto":
        input_type = "kb" if path.is_dir() else "file" if path.is_file() else "idea"

    raw_iterations = args.get("max_iterations", 2)
    if isinstance(raw_iterations, bool):
        raise MCPError(MCPErrorCode.VALIDATION_ERROR, "max_iterations must be an integer")
    try:
        max_iterations = int(raw_iterations)
    except (TypeError, ValueError) as exc:
        raise MCPError(
            MCPErrorCode.VALIDATION_ERROR, "max_iterations must be an integer"
        ) from exc

    dry_run = args.get("dry_run", False)
    if not isinstance(dry_run, bool):
        raise MCPError(MCPErrorCode.VALIDATION_ERROR, "dry_run must be a boolean")
    constraint_params = args.get("constraint_params", {})
    if not isinstance(constraint_params, dict):
        raise MCPError(
            MCPErrorCode.VALIDATION_ERROR, "constraint_params must be an object"
        )

    kwargs: dict[str, Any] = {
        "workspace_path": root,
        "constraints": str(args.get("constraints", "")),
        "max_iterations": max_iterations,
        "profile": str(args.get("profile", "default")),
        "dry_run": dry_run,
        "mode": str(args.get("mode", "auto")),
        "constraint_params": constraint_params,
    }
    if input_type == "idea":
        kwargs["idea"] = raw_input
    elif input_type == "file":
        kwargs["file"] = path
    else:
        kwargs["kb"] = path

    try:
        result = run_mine(**kwargs)
    except ValueError as exc:
        raise MCPError(MCPErrorCode.VALIDATION_ERROR, str(exc)) from exc
    run_dir = Path(result["run_dir"])
    summary_path = run_dir / "summary.json"
    # The summary is returned inline so a driving agent does not have to choose
    # between parsing report.md and loading every full draft from
    # opportunities.json just to learn what the run produced.
    summary = read_json(summary_path) if summary_path.is_file() else {}
    return {
        "run_id": result["run_id"],
        "opportunities": [
            entry["am_id"]
            for entry in summary.get("opportunities", [])
            if entry.get("eligibility") == "published"
        ],
        "filtered": [
            entry["am_id"]
            for entry in summary.get("opportunities", [])
            if entry.get("eligibility") != "published"
        ],
        "summary": summary,
        "artifacts": {
            "run_dir": str(run_dir),
            "report": result.get("report_path", ""),
            "summary_json": str(summary_path),
            "opportunities_json": str(run_dir / "opportunities.json"),
            "registry": str(root / "registry.json"),
        },
    }


def _list_runs(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    return {"runs": Workspace(root).list_runs()}


def _list_domains(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    registry = _registry(root)
    return {"domains": registry.get("domains", [])}


def _get_opportunity(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    ws = Workspace(root)
    try:
        found = ws.find_opportunity(str(args.get("am_id", "")))
    except ValueError as exc:
        raise MCPError(MCPErrorCode.VALIDATION_ERROR, str(exc)) from exc
    if found is None:
        am_id = str(args.get("am_id", "")).upper()
        raise MCPError(MCPErrorCode.NOT_FOUND, f"Opportunity {am_id} not found")
    am_id, path = found
    return {"am_id": am_id, "path": str(path), "brief": path.read_text("utf-8")}


def _query_registry(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    min_ice: int | None = None
    if "min_ice" in args and args["min_ice"] is not None:
        value = args["min_ice"]
        if isinstance(value, bool):
            raise MCPError(MCPErrorCode.VALIDATION_ERROR, "min_ice must be an integer")
        try:
            min_ice = int(value)
        except (TypeError, ValueError) as exc:
            raise MCPError(MCPErrorCode.VALIDATION_ERROR, "min_ice must be an integer") from exc
        if not 0 <= min_ice <= 125:
            raise MCPError(MCPErrorCode.VALIDATION_ERROR, "min_ice must be between 0 and 125")

    entries = _registry(root).get("entries", [])
    if layer := args.get("layer"):
        entries = [e for e in entries if e["l"] == layer]
    if min_ice is not None:
        entries = [e for e in entries if e["ice"] >= min_ice]
    if status := args.get("status"):
        entries = [e for e in entries if e["s"] == status]
    if domain := args.get("domain"):
        entries = [e for e in entries if e["d"] == domain]
    return {"entries": entries, "count": len(entries)}


def _get_run_report(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    run_id = str(args.get("run_id", ""))
    try:
        path = Workspace(root).run_report_path(run_id)
    except ValueError as exc:
        raise MCPError(MCPErrorCode.VALIDATION_ERROR, str(exc)) from exc
    if not path.is_file():
        raise MCPError(MCPErrorCode.NOT_FOUND, f"No report for run {run_id!r}")
    return {"run_id": run_id, "report": path.read_text(encoding="utf-8")}


def _get_run_summary(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    run_id = str(args.get("run_id", ""))
    try:
        path = Workspace(root).run_summary_path(run_id)
    except ValueError as exc:
        raise MCPError(MCPErrorCode.VALIDATION_ERROR, str(exc)) from exc
    if not path.is_file():
        raise MCPError(MCPErrorCode.NOT_FOUND, f"No summary for run {run_id!r}")
    return {"run_id": run_id, "summary": read_json(path)}


def _list_readers(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    from automation_miner.readers import build_registry

    registry = build_registry(load_config(root).readers)
    return {
        "readers": [
            {
                "name": row.name,
                "suffixes": list(row.suffixes),
                "media_type": row.media_type,
                "available": row.available,
                "reason": row.reason,
                "source": row.source,
            }
            for row in registry.describe()
        ],
        "formats": list(registry.suffixes),
        "errors": registry.errors,
    }


def _reindex(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    registry = reindex(root)
    return {"registry": str(root / "registry.json"), "stats": registry["stats"]}


def _server_info(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    config = load_config(root)
    return {
        "name": "automation-miner-mcp",
        "version": __version__,
        "workspace": str(root),
        "config_source": config.source,
        "routing": config.routing_table(),
    }


def _registry(root: Path) -> dict[str, Any]:
    path = root / "registry.json"
    if not path.is_file():
        raise MCPError(MCPErrorCode.NOT_FOUND, f"No registry at {path}; run reindex first")
    return read_json(path)


HANDLERS = {
    "mine_domain": _mine_domain,
    "list_runs": _list_runs,
    "list_domains": _list_domains,
    "get_opportunity": _get_opportunity,
    "query_registry": _query_registry,
    "get_run_report": _get_run_report,
    "get_run_summary": _get_run_summary,
    "list_readers": _list_readers,
    "reindex": _reindex,
    "server_info": _server_info,
}

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "mine_domain": {
        "type": "object",
        "properties": {
            "input": {"type": "string", "description": "Idea text, file path, or KB folder."},
            "input_type": {"type": "string", "enum": list(INPUT_TYPES), "default": "auto"},
            "constraints": {"type": "string", "default": ""},
            "constraint_params": {
                "type": "object",
                "additionalProperties": {
                    "type": ["string", "number", "boolean"]
                },
                "default": {},
                "description": (
                    "Open-ended binding parameters, e.g. "
                    '{"agent":"openclaw","deployment":"local-only"}.'
                ),
            },
            "mode": {
                "type": "string",
                "enum": ["auto", "operational", "strategy"],
                "default": "auto",
            },
            "profile": {"type": "string", "default": "default"},
            "max_iterations": {"type": "integer", "minimum": 1, "maximum": 10, "default": 2},
            "dry_run": {
                "type": "boolean",
                "default": False,
                "description": "Force the deterministic mock provider.",
            },
        },
        "required": ["input"],
    },
    "list_runs": {"type": "object", "properties": {}},
    "list_domains": {"type": "object", "properties": {}},
    "get_opportunity": {
        "type": "object",
        "properties": {"am_id": {"type": "string", "description": "e.g. AM-001"}},
        "required": ["am_id"],
    },
    "query_registry": {
        "type": "object",
        "properties": {
            "layer": {"type": "string"},
            "min_ice": {"type": "integer", "minimum": 0, "maximum": 125},
            "status": {"type": "string"},
            "domain": {"type": "string"},
        },
    },
    "get_run_report": {
        "type": "object",
        "properties": {"run_id": {"type": "string"}},
        "required": ["run_id"],
    },
    "get_run_summary": {
        "type": "object",
        "properties": {"run_id": {"type": "string"}},
        "required": ["run_id"],
    },
    "list_readers": {"type": "object", "properties": {}},
    "reindex": {"type": "object", "properties": {}},
    "server_info": {"type": "object", "properties": {}},
}

TOOL_DESCRIPTIONS = {
    "mine_domain": (
        "Run the full mining pipeline over a domain. Returns the compact run summary "
        "inline (per-opportunity ICE, tier, filters, eligibility) plus artifact paths."
    ),
    "list_runs": "List all mining run ids in the workspace.",
    "list_domains": "List all domains in the registry with totals and top ICE.",
    "get_opportunity": "Return the full AM-XXX opportunity brief markdown.",
    "query_registry": "Query registry entries filtered by layer, min ICE, status, or domain.",
    "get_run_report": "Return the report.md content of one run.",
    "get_run_summary": (
        "Return the compact summary.json of one run: portfolio stats, context stats, "
        "token usage, and one row per opportunity. Prefer this over get_run_report "
        "when deciding what to act on."
    ),
    "list_readers": (
        "List document readers, the file formats each handles, and whether its "
        "dependencies are installed."
    ),
    "reindex": "Rebuild registry.json from the opps/ tree.",
    "server_info": "Server version, active model routing, workspace path.",
}


def dispatch(tool: str, args: dict[str, Any], workspace: Path) -> MCPResponse:
    """Call a tool handler and wrap the result in the response envelope."""
    handler = HANDLERS.get(tool)
    if handler is None:
        return MCPResponse(
            success=False,
            error=MCPError(MCPErrorCode.UNKNOWN_TOOL, f"Unknown tool: {tool}"),
        )
    try:
        return MCPResponse(success=True, data=handler(workspace, args))
    except MCPError as exc:
        return MCPResponse(success=False, error=exc)
    except Exception as exc:
        return MCPResponse(
            success=False, error=MCPError(MCPErrorCode.INTERNAL_ERROR, str(exc))
        )
