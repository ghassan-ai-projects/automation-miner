"""Shared constants, result IO, and opt-in safety guards."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from automation_miner.artifacts.workspace import read_json
from automation_miner.models.config import MinerConfig
from automation_miner.schemas import (
    RunBudget,
)


ROOT = Path(__file__).resolve().parents[4]
PILOT_BUDGET = RunBudget()
RATING_DIMENSIONS = (
    "groundedness",
    "specificity",
    "actionability",
    "auditability",
    "honesty",
    "differentiation",
    "polish",
)
EPISTEMIC_STATUSES = {"observed", "inferred", "proposed", "benchmarked", "unknown"}
MIN_WEIGHTED_KAPPA = 0.4
IDENTITY_KEY_PARTS = ("model", "provider", "profile", "route", "prompt", "response")
CANONICAL_CORPUS_SHA256 = "8e8937649cc087721341292f60b8bed8f8e43a25879e3971e563269a8a927239"
MAX_GATE_CRITIC_TOKENS = 1_000


class EvaluationError(RuntimeError):
    """A live-evaluation precondition or artifact contract failed."""


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise EvaluationError(f"{label} must be a JSON object")
    return value


def _load_object(path: Path) -> Mapping[str, Any]:
    try:
        return _mapping(read_json(path), str(path))
    except (OSError, ValueError) as exc:
        raise EvaluationError(f"cannot read JSON input {path}") from exc


def _write_result(path: Path, payload: Mapping[str, Any], force: bool) -> None:
    if path.exists() and not force:
        raise EvaluationError(f"result exists; pass --force to replace {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git(args: list[str], failure: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise EvaluationError(failure) from exc
    return result.stdout.strip()


def _git_commit() -> str:
    """The evaluated commit; refuses a dirty tree so results map to exact code."""
    if _git(["status", "--porcelain"], "unable to inspect repository state"):
        raise EvaluationError("repository working tree must be clean for live evaluation")
    commit = _git(["rev-parse", "HEAD"], "unable to resolve the repository commit")
    if not commit:
        raise EvaluationError("repository commit is empty")
    return commit


def _require_live(args: argparse.Namespace) -> None:
    if not args.live:
        raise EvaluationError("refusing provider calls without --live")
    if not args.privacy_approved:
        raise EvaluationError(
            "refusing provider calls without --privacy-approved for redacted, non-production input"
        )


def _require_external_path(path: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT)
    except ValueError:
        return resolved
    raise EvaluationError(f"{label} must be outside the repository: {resolved}")


def _guard_config(config: MinerConfig) -> RunBudget:
    budget = RunBudget.model_validate(config.budget)
    limits = (
        ("max_attempts", budget.max_attempts, PILOT_BUDGET.max_attempts),
        ("max_tokens", budget.max_tokens, PILOT_BUDGET.max_tokens),
        ("max_seconds", budget.max_seconds, PILOT_BUDGET.max_seconds),
    )
    exceeded = [name for name, actual, maximum in limits if actual > maximum]
    if exceeded:
        raise EvaluationError(
            "configured pilot budget exceeds the safety ceiling: " + ", ".join(exceeded)
        )
    if config.workers_for("critique") != 1 or config.workers_for("score") != 1:
        raise EvaluationError("pilot evaluation requires critique=1 and score=1 concurrency")
    return budget


def _require_api_keys(config: MinerConfig, roles: Sequence[str]) -> dict[str, tuple[str, str]]:
    routes: dict[str, tuple[str, str]] = {}
    missing: list[str] = []
    for role in roles:
        route = config.resolve(role)
        if route.provider == "mock":
            missing.append(f"{role}:mock-provider")
        elif not os.environ.get(route.api_key_env):
            missing.append(f"{role}:{route.api_key_env}")
        routes[role] = (route.provider, route.model)
    if missing:
        raise EvaluationError("live provider prerequisites failed: " + ", ".join(missing))
    return routes


def _guard_critic_config(config: MinerConfig) -> RunBudget:
    budget = _guard_config(config)
    route = config.resolve("critic")
    if route.max_tokens > MAX_GATE_CRITIC_TOKENS:
        raise EvaluationError(
            "critic-gate requires critic max_tokens <= "
            f"{MAX_GATE_CRITIC_TOKENS} for the shared pilot ceiling"
        )
    return budget
