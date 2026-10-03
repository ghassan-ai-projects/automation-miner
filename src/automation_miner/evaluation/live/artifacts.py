"""Execute the bounded live smoke run and record its validated, redacted result."""

from __future__ import annotations

import argparse
import json
from html import escape
from pathlib import Path

from automation_miner.evaluation.live.common import (
    EvaluationError,
    _git_commit,
    _guard_config,
    _now,
    _require_api_keys,
    _require_external_path,
    _require_live,
    _write_result,
)
from automation_miner.evaluation.live.validation import validate_run_artifacts
from automation_miner.graph.runner import run_mine
from automation_miner.models.client import MinerModel
from automation_miner.models.config import ROLES, MinerConfig, load_config

__all__ = ["_fence_evaluation_evidence", "_smoke", "validate_run_artifacts"]


def _fence_evaluation_evidence(value: str) -> str:
    """Apply the same data boundary to corpus evidence used by the critic."""
    return (
        "<untrusted-evidence id=\"EVAL-SOURCE\">\n"
        f"{escape(value, quote=False)}\n"
        "</untrusted-evidence>"
    )


def _prepare_smoke(args: argparse.Namespace) -> tuple[Path, Path, MinerConfig]:
    """Every guard that must pass before a provider call: flags, paths, budget, keys."""
    _require_live(args)
    workspace = _require_external_path(args.workspace, "workspace")
    result_path = _require_external_path(args.result, "result")
    for input_path, label in ((args.file, "file"), (args.kb, "knowledge base")):
        if input_path is not None:
            _require_external_path(input_path, label)
    config = load_config(workspace, args.profile)
    _guard_config(config)
    _require_api_keys(config, ROLES)
    if args.iterations != 1:
        raise EvaluationError("pilot smoke requires --iterations 1")
    return workspace, result_path, config


def _live_run_dir(args: argparse.Namespace, workspace: Path, model: MinerModel) -> Path:
    """Run once; a failed run still yields its directory so its artifacts are checked."""
    try:
        result = run_mine(
            workspace_path=workspace, idea=args.idea, file=args.file, kb=args.kb,
            constraints=args.constraints, max_iterations=args.iterations,
            profile=args.profile, dry_run=False, mode=args.mode, model=model,
        )
    except Exception as exc:
        raw_run_dir = getattr(exc, "run_dir", "")
        if not raw_run_dir:
            raise EvaluationError("live run failed before a run directory was created") from exc
        return Path(str(raw_run_dir))
    return Path(str(result["summary_path"])).parent


def _smoke(args: argparse.Namespace) -> int:
    workspace, result_path, config = _prepare_smoke(args)
    commit = _git_commit()
    model = MinerModel(config, dry_run=False)
    try:
        run_dir = _live_run_dir(args, workspace, model)
    finally:
        model.close()
    run_record = validate_run_artifacts(run_dir)
    payload = {
        "kind": "live_smoke",
        "version": "live-smoke-v1",
        "generated_at": _now(),
        "commit": commit,
        "profile": args.profile,
        "privacy": {"raw_inputs_saved": False, "operator_approved_redacted_input": True},
        "run": run_record,
    }
    _write_result(result_path, payload, args.force)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    passed = run_record["status"] == "completed" and run_record["artifact_validation"] == "pass"
    return 0 if passed else 1
