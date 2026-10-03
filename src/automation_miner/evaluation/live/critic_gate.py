"""Two-profile critic-gate evaluation over the labelled corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from automation_miner.execution import BudgetExceeded, BudgetSnapshot, RunExecutionContext
from automation_miner.models.client import MinerModel, UsageTracker
from automation_miner.models.config import MinerConfig, load_config
from automation_miner.prompts import CRITIC_SYSTEM, critique_prompt
from automation_miner.schemas import (
    Critique,
)
from automation_miner.evaluation.live.common import (
    CANONICAL_CORPUS_SHA256,
    EvaluationError,
    _mapping,
    _load_object,
    _write_result,
    _now,
    _git_commit,
    _require_live,
    _require_external_path,
    _require_api_keys,
    _guard_critic_config,
    PILOT_BUDGET,
)
from automation_miner.evaluation.live.artifacts import (
    _fence_evaluation_evidence,
)


def _corpus_payload(path: Path) -> tuple[str, list[Any], Mapping[str, Any]]:
    """The fingerprint-checked corpus: version, raw cases, and label rationales."""
    payload = _load_object(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != CANONICAL_CORPUS_SHA256:
        raise EvaluationError("critic corpus fingerprint does not match the versioned canonical corpus")
    version = str(payload.get("version", ""))
    raw_cases = payload.get("cases")
    rationales = payload.get("label_rationales")
    if not version or not isinstance(raw_cases, list) or len(raw_cases) != 20:
        raise EvaluationError("critic corpus must have a version and exactly 20 cases")
    if not isinstance(rationales, dict):
        raise EvaluationError("critic corpus must include external label rationales")
    expected_passes = sum(
        1 for case in raw_cases if isinstance(case, dict) and case.get("expected_pass") is True
    )
    if expected_passes != 10:
        raise EvaluationError("critic corpus must contain exactly 10 pass and 10 block cases")
    return version, raw_cases, rationales


def _corpus_case(raw: object, rationales: Mapping[str, Any], ids: set[str]) -> dict[str, Any]:
    case = dict(_mapping(raw, "critic corpus case"))
    case_id = case.get("id")
    if not isinstance(case_id, str) or not case_id or case_id in ids:
        raise EvaluationError("critic corpus case ids must be unique non-empty strings")
    if not isinstance(case.get("expected_pass"), bool):
        raise EvaluationError(f"critic corpus case {case_id} has no boolean expected_pass")
    if not isinstance(rationales.get(case_id), str) or not rationales[case_id].strip():
        raise EvaluationError(f"critic corpus case {case_id} has no label rationale")
    draft = case.get("draft_json", case.get("draft"))
    if isinstance(draft, dict):
        case["draft_json"] = json.dumps(draft, ensure_ascii=False)
    if not isinstance(case.get("draft_json"), str) or not isinstance(case.get("evidence"), str):
        raise EvaluationError(f"critic corpus case {case_id} is missing model input fields")
    ids.add(case_id)
    return case


def _load_corpus(path: Path) -> tuple[str, list[dict[str, Any]]]:
    version, raw_cases, rationales = _corpus_payload(path)
    ids: set[str] = set()
    return version, [_corpus_case(raw, rationales, ids) for raw in raw_cases]


def _confusion(outcomes: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Count outcomes per confusion cell; a ``None`` prediction is an abstention."""
    counts = dict.fromkeys(
        ("true_positives", "true_negatives", "false_positives", "false_negatives", "abstentions"), 0
    )
    for outcome in outcomes:
        expected, predicted = bool(outcome["expected_pass"]), outcome.get("predicted_pass")
        if predicted is None:
            cell = "abstentions"
        else:
            correct = bool(predicted) == expected
            cell = f"{'true' if correct else 'false'}_{'positives' if predicted else 'negatives'}"
        counts[cell] += 1
    return counts


def gate_metrics(outcomes: Sequence[Mapping[str, Any]]) -> dict[str, int | float]:
    """Compute confusion metrics; ``None`` predictions are abstentions."""
    counts = _confusion(outcomes)
    tp, fp, fn = counts["true_positives"], counts["false_positives"], counts["false_negatives"]
    decided = tp + counts["true_negatives"] + fp + fn
    return {
        "cases": len(outcomes),
        "decided": decided,
        **counts,
        "precision": round(tp / (tp + fp), 4) if tp + fp else 0.0,
        "recall": round(tp / (tp + fn), 4) if tp + fn else 0.0,
        "abstention_rate": round(counts["abstentions"] / len(outcomes), 4) if outcomes else 0.0,
    }


def _abstained(case: Mapping[str, Any], error_type: str = "") -> dict[str, Any]:
    outcome: dict[str, Any] = {
        "id": str(case["id"]),
        "expected_pass": bool(case["expected_pass"]),
        "predicted_pass": None,
        "abstained": True,
    }
    if error_type:
        outcome["error_type"] = error_type
    return outcome


def _critique_case(
    model: MinerModel, case: Mapping[str, Any], tracker: UsageTracker,
    execution: RunExecutionContext,
) -> dict[str, Any]:
    """One critic verdict; any error except an exhausted budget becomes an abstention."""
    prompt = critique_prompt(
        str(case["draft_json"]), [], _fence_evaluation_evidence(str(case["evidence"])),
        str(case.get("constraints", "")),
    )
    try:
        critique = model.call_json(
            "critic", CRITIC_SYSTEM, prompt, Critique, usage=tracker, execution=execution
        )
    except BudgetExceeded:
        raise
    except Exception as exc:
        return _abstained(case, type(exc).__name__)
    return {**_abstained(case), "predicted_pass": critique.passed, "abstained": False}


def _critique_all(
    model: MinerModel, cases: Sequence[Mapping[str, Any]], tracker: UsageTracker,
    execution: RunExecutionContext,
) -> tuple[str, list[dict[str, Any]]]:
    """Run every case; an exhausted budget marks this and all later cases as abstained."""
    outcomes: list[dict[str, Any]] = []
    for case in cases:
        try:
            outcomes.append(_critique_case(model, case, tracker, execution))
        except BudgetExceeded:
            rest = cases[len(outcomes) :]
            outcomes.extend(_abstained(remaining, "BudgetExceeded") for remaining in rest)
            return "budget_exhausted", outcomes
    return "completed", outcomes


def _admission(started: BudgetSnapshot, snapshot: BudgetSnapshot) -> dict[str, Any]:
    """What one profile's evaluation consumed of the shared execution budget."""
    return {
        "attempts": snapshot.attempts - started.attempts,
        "tokens": snapshot.tokens - started.tokens,
        "elapsed_seconds": round(snapshot.elapsed_seconds - started.elapsed_seconds, 3),
    }


def _run_critic_set(
    config: MinerConfig,
    profile: str,
    cases: Sequence[Mapping[str, Any]],
    execution: RunExecutionContext,
) -> dict[str, Any]:
    _guard_critic_config(config)
    provider, model_name = _require_api_keys(config, ("critic",))["critic"]
    model = MinerModel(config, dry_run=False)
    tracker = UsageTracker()
    started = execution.snapshot()
    try:
        status, outcomes = _critique_all(model, cases, tracker, execution)
    finally:
        model.close()
    return {
        "profile": profile, "provider": provider, "model": model_name, "status": status,
        "budget": execution.budget.model_dump(mode="json"),
        "usage": tracker.snapshot().model_dump(mode="json"),
        "admission": _admission(started, execution.snapshot()),
        "metrics": gate_metrics(outcomes),
        "outcomes": outcomes,
    }


def _gate_configs(args: argparse.Namespace, workspace: Path) -> dict[str, MinerConfig]:
    """Both critic profiles, each held to the exact pilot budget."""
    configs = {name: load_config(workspace, name) for name in (args.profile, args.strong_profile)}
    if any(_guard_critic_config(config) != PILOT_BUDGET for config in configs.values()):
        raise EvaluationError("critic-gate profiles must use the exact pilot budget")
    return configs


def _gate_payload(
    commit: str, version: str, cases: int, aggregate: BudgetSnapshot,
    evaluations: dict[str, Any],
) -> dict[str, Any]:
    return {
        "kind": "critic_gate", "version": "critic-gate-v1", "generated_at": _now(),
        "commit": commit,
        "corpus": {"version": version, "cases": cases, "raw_inputs_saved": False},
        "privacy": {"operator_approved_redacted_input": True},
        "aggregate_admission": {
            "attempts": aggregate.attempts, "tokens": aggregate.tokens,
            "elapsed_seconds": aggregate.elapsed_seconds,
            "budget": PILOT_BUDGET.model_dump(mode="json"),
        },
        "evaluations": evaluations,
    }


def _critic_gate(args: argparse.Namespace) -> int:
    _require_live(args)
    workspace = _require_external_path(args.workspace, "workspace")
    result_path = _require_external_path(args.result, "result")
    if args.profile == args.strong_profile:
        raise EvaluationError("--profile and --strong-profile must select different profiles")
    version, cases = _load_corpus(args.corpus)
    commit = _git_commit()
    configs = _gate_configs(args, workspace)
    execution = RunExecutionContext("critic-gate", PILOT_BUDGET)
    evaluations = {
        name: _run_critic_set(config, name, cases, execution) for name, config in configs.items()
    }
    payload = _gate_payload(commit, version, len(cases), execution.snapshot(), evaluations)
    _write_result(result_path, payload, args.force)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    clean = (e["status"] == "completed" and e["metrics"]["abstentions"] == 0 for e in evaluations.values())
    return 0 if all(clean) else 1
