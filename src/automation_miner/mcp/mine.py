"""The ``mine_domain`` MCP tool: validate arguments and run the pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from automation_miner.artifacts.workspace import read_json
from automation_miner.mcp.catalog import INPUT_TYPES
from automation_miner.mcp.errors import MCPError, MCPErrorCode


def _run_failure_details(exc: BaseException) -> dict[str, str]:
    run_id = str(getattr(exc, "run_id", ""))
    if not run_id:
        return {}
    run_dir = str(getattr(exc, "run_dir", ""))
    return {
        "run_id": run_id,
        "run_dir": run_dir,
        "error": str(Path(run_dir) / "error.json"),
    }


def _invalid(message: str) -> MCPError:
    return MCPError(MCPErrorCode.VALIDATION_ERROR, message)


def _input(args: dict[str, Any]) -> dict[str, Any]:
    """Resolve ``input``/``input_type`` into exactly one run_mine source kwarg."""
    raw = args.get("input", "")
    if not isinstance(raw, str) or not raw.strip():
        raise _invalid("input is required")
    raw = raw.strip()
    kind = str(args.get("input_type", "auto"))
    if kind not in INPUT_TYPES:
        raise _invalid(f"input_type must be one of {INPUT_TYPES}")
    path = Path(raw)
    if kind == "auto":
        kind = "kb" if path.is_dir() else "file" if path.is_file() else "idea"
    elif kind == "file" and not path.is_file():
        raise _invalid(f"file does not exist: {raw}")
    elif kind == "kb" and not path.is_dir():
        raise _invalid(f"kb directory does not exist: {raw}")
    return {"idea": raw} if kind == "idea" else {kind: path}


def _options(args: dict[str, Any]) -> dict[str, Any]:
    raw_iterations = args.get("max_iterations", 2)
    try:
        if isinstance(raw_iterations, bool):
            raise ValueError
        max_iterations = int(raw_iterations)
    except (TypeError, ValueError) as exc:
        raise _invalid("max_iterations must be an integer") from exc
    dry_run = args.get("dry_run", False)
    if not isinstance(dry_run, bool):
        raise _invalid("dry_run must be a boolean")
    constraint_params = args.get("constraint_params", {})
    if not isinstance(constraint_params, dict):
        raise _invalid("constraint_params must be an object")
    return {
        "constraints": str(args.get("constraints", "")), "max_iterations": max_iterations,
        "profile": str(args.get("profile", "default")), "dry_run": dry_run,
        "mode": str(args.get("mode", "auto")), "constraint_params": constraint_params,
    }


def _envelope(root: Path, result: dict[str, Any]) -> dict[str, Any]:
    """The summary inline, so a driving agent need not parse report.md or load
    every full draft from opportunities.json to learn what the run produced."""
    run_dir = Path(result["run_dir"])
    summary_path = run_dir / "summary.json"
    summary = read_json(summary_path) if summary_path.is_file() else {}
    entries = summary.get("opportunities", [])
    return {
        "run_id": result["run_id"],
        "opportunities": [e["am_id"] for e in entries if e.get("eligibility") == "published"],
        "filtered": [e["am_id"] for e in entries if e.get("eligibility") != "published"],
        "summary": summary,
        "artifacts": {
            "run_dir": str(run_dir), "report": result.get("report_path", ""),
            "summary_json": str(summary_path),
            "opportunities_json": str(run_dir / "opportunities.json"),
            "registry": str(root / "registry.json"),
        },
    }


def mine_domain(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    from automation_miner.graph.runner import run_mine

    kwargs = {"workspace_path": root, **_options(args), **_input(args)}
    try:
        result = run_mine(**kwargs)
    except ValueError as exc:
        details = _run_failure_details(exc)
        if details:
            raise MCPError(MCPErrorCode.INTERNAL_ERROR, str(exc), details=details) from exc
        raise _invalid(str(exc)) from exc
    except Exception as exc:
        details = _run_failure_details(exc)
        raise MCPError(MCPErrorCode.INTERNAL_ERROR, str(exc), details=details) from exc
    return _envelope(root, dict(result))
