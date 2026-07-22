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

    raw_input = str(args.get("input", ""))
    if not raw_input:
        raise MCPError(MCPErrorCode.VALIDATION_ERROR, "input is required")
    input_type = str(args.get("input_type", "auto"))
    if input_type not in INPUT_TYPES:
        raise MCPError(
            MCPErrorCode.VALIDATION_ERROR,
            f"input_type must be one of {INPUT_TYPES}",
        )
    path = Path(raw_input)
    if input_type == "auto":
        input_type = "kb" if path.is_dir() else "file" if path.is_file() else "idea"

    kwargs: dict[str, Any] = {
        "workspace_path": root,
        "constraints": str(args.get("constraints", "")),
        "max_iterations": int(args.get("max_iterations", 2)),
        "profile": str(args.get("profile", "default")),
        "dry_run": bool(args.get("dry_run", False)),
    }
    if input_type == "idea":
        kwargs["idea"] = raw_input
    elif input_type == "file":
        kwargs["file"] = path
    else:
        kwargs["kb"] = path

    result = run_mine(**kwargs)
    run_dir = Path(result["run_dir"])
    return {
        "run_id": result["run_id"],
        "opportunities": [o["am_id"] for o in result.get("opportunities", [])],
        "artifacts": {
            "run_dir": str(run_dir),
            "report": result.get("report_path", ""),
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
    am_id = str(args.get("am_id", "")).upper()
    if not am_id.startswith("AM-"):
        am_id = f"AM-{am_id}"
    ws = Workspace(root)
    matches = sorted(ws.opps_dir.rglob(f"{am_id}-*.md")) if ws.opps_dir.exists() else []
    if not matches:
        raise MCPError(MCPErrorCode.NOT_FOUND, f"Opportunity {am_id} not found")
    return {"am_id": am_id, "path": str(matches[0]), "brief": matches[0].read_text("utf-8")}


def _query_registry(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    entries = _registry(root).get("entries", [])
    if layer := args.get("layer"):
        entries = [e for e in entries if e["l"] == layer]
    if min_ice := args.get("min_ice"):
        entries = [e for e in entries if e["ice"] >= int(min_ice)]
    if status := args.get("status"):
        entries = [e for e in entries if e["s"] == status]
    if domain := args.get("domain"):
        entries = [e for e in entries if e["d"] == domain]
    return {"entries": entries, "count": len(entries)}


def _get_run_report(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    run_id = str(args.get("run_id", ""))
    path = root / "runs" / run_id / "report.md"
    if not path.is_file():
        raise MCPError(MCPErrorCode.NOT_FOUND, f"No report for run {run_id!r}")
    return {"run_id": run_id, "report": path.read_text(encoding="utf-8")}


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
            "profile": {"type": "string", "default": "default"},
            "max_iterations": {"type": "integer", "default": 2},
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
            "min_ice": {"type": "integer"},
            "status": {"type": "string"},
            "domain": {"type": "string"},
        },
    },
    "get_run_report": {
        "type": "object",
        "properties": {"run_id": {"type": "string"}},
        "required": ["run_id"],
    },
    "reindex": {"type": "object", "properties": {}},
    "server_info": {"type": "object", "properties": {}},
}

TOOL_DESCRIPTIONS = {
    "mine_domain": "Run the full mining pipeline over a domain; returns run summary + artifact paths.",
    "list_runs": "List all mining run ids in the workspace.",
    "list_domains": "List all domains in the registry with totals and top ICE.",
    "get_opportunity": "Return the full AM-XXX opportunity brief markdown.",
    "query_registry": "Query registry entries filtered by layer, min ICE, status, or domain.",
    "get_run_report": "Return the report.md content of one run.",
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
    except (ValueError, RuntimeError) as exc:
        return MCPResponse(
            success=False, error=MCPError(MCPErrorCode.INTERNAL_ERROR, str(exc))
        )
