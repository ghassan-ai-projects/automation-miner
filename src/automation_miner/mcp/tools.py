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
from automation_miner.mcp.catalog import TOOL_DESCRIPTIONS, TOOL_SCHEMAS
from automation_miner.mcp.errors import MCPError, MCPErrorCode, MCPResponse
from automation_miner.mcp.lifecycle import LIFECYCLE_HANDLERS
from automation_miner.mcp.mine import mine_domain
from automation_miner.models.config import load_config


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


def _get_run_manifest(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    run_id = str(args.get("run_id", ""))
    try:
        path = Workspace(root).run_report_path(run_id).with_name("run.json")
    except ValueError as exc:
        raise MCPError(MCPErrorCode.VALIDATION_ERROR, str(exc)) from exc
    if not path.is_file():
        raise MCPError(MCPErrorCode.NOT_FOUND, f"No manifest for run {run_id!r}")
    return {"run_id": run_id, "manifest": read_json(path)}


def _get_run_error(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    run_id = str(args.get("run_id", ""))
    try:
        path = Workspace(root).run_report_path(run_id).with_name("error.json")
    except ValueError as exc:
        raise MCPError(MCPErrorCode.VALIDATION_ERROR, str(exc)) from exc
    if not path.is_file():
        raise MCPError(MCPErrorCode.NOT_FOUND, f"No error for run {run_id!r}")
    return {"run_id": run_id, "error": read_json(path)}


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


def _evaluate_run(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    from automation_miner.evaluation import evaluate_run
    from automation_miner.models.client import MinerModel

    run_id = str(args.get("run_id", ""))
    try:
        run_dir = Workspace(root).run_summary_path(run_id).parent
    except ValueError as exc:
        raise MCPError(MCPErrorCode.VALIDATION_ERROR, str(exc)) from exc
    if not (run_dir / "summary.json").is_file():
        raise MCPError(MCPErrorCode.NOT_FOUND, f"No completed run {run_id!r}")
    judge = args.get("judge", False)
    dry_run = args.get("dry_run", False)
    if not isinstance(judge, bool) or not isinstance(dry_run, bool):
        raise MCPError(MCPErrorCode.VALIDATION_ERROR, "judge and dry_run must be booleans")
    model = (
        MinerModel(load_config(root, str(args.get("profile", "default"))), dry_run=dry_run)
        if judge
        else None
    )
    try:
        evaluation = evaluate_run(run_dir, root, model)
    finally:
        if model is not None:
            model.close()
    return evaluation.model_dump(mode="json")


def _registry(root: Path) -> dict[str, Any]:
    path = root / "registry.json"
    if not path.is_file():
        raise MCPError(MCPErrorCode.NOT_FOUND, f"No registry at {path}; run reindex first")
    return read_json(path)


HANDLERS = {
    "mine_domain": mine_domain,
    "list_runs": _list_runs,
    "list_domains": _list_domains,
    "get_opportunity": _get_opportunity,
    "query_registry": _query_registry,
    "get_run_report": _get_run_report,
    "get_run_summary": _get_run_summary,
    "get_run_manifest": _get_run_manifest,
    "get_run_error": _get_run_error,
    "evaluate_run": _evaluate_run,
    "list_readers": _list_readers,
    "reindex": _reindex,
    "server_info": _server_info,
    **LIFECYCLE_HANDLERS,
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


__all__ = ["HANDLERS", "TOOL_DESCRIPTIONS", "TOOL_SCHEMAS", "dispatch"]
