"""Guarded real-provider smoke, critic-gate, and human-score evaluation.

The commands in this module are deliberately opt-in. They never run a provider
call without both ``--live`` and ``--privacy-approved``. Result files contain
metadata and aggregate measurements only; raw inputs, prompts, and provider
responses remain outside the repository and are never copied into a result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Mapping, Sequence

from automation_miner.artifacts.workspace import read_json
from automation_miner.execution import BudgetExceeded, RunExecutionContext
from automation_miner.graph.build import run_mine
from automation_miner.models.client import MinerModel, UsageTracker
from automation_miner.models.config import MinerConfig, ROLES, load_config
from automation_miner.prompts import CRITIC_SYSTEM, critique_prompt
from automation_miner.schemas import (
    Critique,
    ContextPacket,
    Opportunity,
    RunBudget,
    RunManifest,
    RunSummary,
    StageFailure,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT_BUDGET = RunBudget(max_attempts=70, max_tokens=120_000, max_seconds=1_800.0)
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


def _git_commit() -> str:
    try:
        clean = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise EvaluationError("unable to inspect repository state") from exc
    if clean.stdout.strip():
        raise EvaluationError("repository working tree must be clean for live evaluation")
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise EvaluationError("unable to resolve the repository commit") from exc
    commit = result.stdout.strip()
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


def _source_descriptor(manifest: Mapping[str, Any]) -> dict[str, str]:
    kind = str(manifest.get("source_kind", "unknown"))
    if kind == "idea":
        name = "<redacted-idea>"
    else:
        name = "<redacted-source>"
    return {"kind": kind, "name": name}


def _fence_evaluation_evidence(value: str) -> str:
    """Apply the same data boundary to corpus evidence used by the critic."""
    return (
        "<untrusted-evidence id=\"EVAL-SOURCE\">\n"
        f"{escape(value, quote=False)}\n"
        "</untrusted-evidence>"
    )


def _usage_budget_errors(manifest: Mapping[str, Any]) -> list[str]:
    usage = _mapping(manifest.get("usage", {}), "manifest usage")
    budget = _mapping(manifest.get("budget", {}), "manifest budget")
    errors: list[str] = []
    checks = (("attempts", "max_attempts"), ("total_tokens", "max_tokens"))
    for observed_name, limit_name in checks:
        observed = usage.get(observed_name, 0)
        maximum = budget.get(limit_name)
        if not isinstance(observed, (int, float)) or isinstance(observed, bool):
            errors.append(f"usage-{observed_name}-invalid")
        elif not isinstance(maximum, (int, float)) or isinstance(maximum, bool):
            errors.append(f"budget-{limit_name}-invalid")
        elif observed > maximum:
            errors.append(f"budget-{observed_name}-exceeded")
    duration = manifest.get("duration_seconds", 0.0)
    maximum_seconds = budget.get("max_seconds")
    if (
        str(manifest.get("status")) == "completed"
        and isinstance(duration, (int, float))
        and isinstance(maximum_seconds, (int, float))
        and duration > maximum_seconds
    ):
        errors.append("budget-duration-exceeded")
    return errors


def validate_run_artifacts(run_dir: Path) -> dict[str, Any]:
    """Validate terminal run invariants and return only redacted metadata."""
    errors: list[str] = []
    manifest_path = run_dir / "run.json"
    try:
        manifest_raw = _load_object(manifest_path)
        RunManifest.model_validate(manifest_raw)
    except (EvaluationError, ValueError):
        manifest_raw = {}
        errors.append("manifest-invalid-or-missing")

    status = str(manifest_raw.get("status", "unknown"))
    publication_status = str(manifest_raw.get("publication_status", "unknown"))
    errors.extend(_usage_budget_errors(manifest_raw) if manifest_raw else [])
    summary_raw: Mapping[str, Any] = {}

    if status == "completed":
        if publication_status != "complete":
            errors.append("publication-not-complete")
        for name in ("summary.json", "report.md", "opportunities.json", "context.json"):
            if not (run_dir / name).is_file():
                errors.append(f"missing-{name}")
        try:
            summary_raw = _load_object(run_dir / "summary.json")
            RunSummary.model_validate(summary_raw)
            if summary_raw.get("status") != status:
                errors.append("summary-status-mismatch")
            if summary_raw.get("publication_status") != publication_status:
                errors.append("summary-publication-status-mismatch")
            if summary_raw.get("domain") != manifest_raw.get("domain"):
                errors.append("summary-domain-mismatch")
            if summary_raw.get("domain_slug") != manifest_raw.get("domain_slug"):
                errors.append("summary-domain-slug-mismatch")
            if summary_raw.get("usage") != manifest_raw.get("usage"):
                errors.append("summary-usage-mismatch")
            if summary_raw.get("budget") != manifest_raw.get("budget"):
                errors.append("summary-budget-mismatch")
            context = ContextPacket.model_validate(read_json(run_dir / "context.json"))
            opportunity_payload = _load_object(run_dir / "opportunities.json")
            raw_opportunities = opportunity_payload.get("opportunities", [])
            if not isinstance(raw_opportunities, list):
                raise EvaluationError("opportunities is not a list")
            opportunities = [Opportunity.model_validate(item) for item in raw_opportunities]
            live_ids = {opportunity.am_id for opportunity in opportunities if opportunity.published}
            manifest_id_values = manifest_raw.get("opportunities", [])
            if not isinstance(manifest_id_values, list):
                raise EvaluationError("manifest opportunities is not a list")
            manifest_ids = set(manifest_id_values)
            if len(manifest_ids) != len(manifest_id_values):
                errors.append("duplicate-manifest-opportunity-ids")
            if len(live_ids) != sum(1 for opportunity in opportunities if opportunity.published):
                errors.append("duplicate-published-opportunity-ids")
            if live_ids != manifest_ids:
                errors.append("manifest-opportunity-mismatch")
            known_ids = context.chunk_ids()
            for opportunity in opportunities:
                if opportunity.published and (
                    set(opportunity.draft.evidence_refs) - known_ids
                    or opportunity.unresolved_refs
                ):
                    errors.append(f"unresolved-published-refs-{opportunity.am_id}")
            stats = _mapping(summary_raw.get("stats", {}), "summary stats")
            if stats.get("total") != len(opportunities):
                errors.append("summary-total-mismatch")
            summary_entries = summary_raw.get("opportunities", [])
            if not isinstance(summary_entries, list):
                raise EvaluationError("summary opportunities is not a list")
            summary_ids = {
                str(entry.get("am_id"))
                for entry in summary_entries
                if isinstance(entry, dict)
            }
            opportunity_ids = {opportunity.am_id for opportunity in opportunities}
            if len(summary_ids) != len(summary_entries):
                errors.append("duplicate-summary-opportunity-ids")
            if len(opportunity_ids) != len(opportunities):
                errors.append("duplicate-ranked-opportunity-ids")
            if summary_ids != opportunity_ids:
                errors.append("summary-opportunity-set-mismatch")
            summary_live_ids = {
                str(entry.get("am_id"))
                for entry in summary_entries
                if isinstance(entry, dict) and entry.get("eligibility") == "published"
            }
            if summary_live_ids != manifest_ids:
                errors.append("summary-opportunity-mismatch")
            if stats.get("published") != len(live_ids):
                errors.append("summary-published-count-mismatch")
            if stats.get("filtered") != len(opportunities) - len(live_ids):
                errors.append("summary-filtered-count-mismatch")
        except (EvaluationError, OSError, ValueError, TypeError):
            errors.append("completed-artifact-schema-invalid")
    elif status in {"failed", "budget_exhausted"}:
        error_path = run_dir / "error.json"
        if not error_path.is_file():
            errors.append("missing-error.json")
        else:
            try:
                error = _load_object(error_path)
                StageFailure.model_validate(error)
                if error.get("status") != status:
                    errors.append("error-status-mismatch")
            except (EvaluationError, ValueError, TypeError):
                errors.append("error-artifact-invalid")
    else:
        errors.append("run-not-terminal")

    usage = manifest_raw.get("usage", {}) if manifest_raw else {}
    return {
        "run_id": str(manifest_raw.get("run_id", run_dir.name)),
        "status": status,
        "publication_status": publication_status,
        "source": _source_descriptor(manifest_raw),
        "models": dict(manifest_raw.get("models", {}))
        if isinstance(manifest_raw.get("models", {}), dict)
        else {},
        "budget": dict(manifest_raw.get("budget", {}))
        if isinstance(manifest_raw.get("budget", {}), dict)
        else {},
        "usage": dict(usage) if isinstance(usage, dict) else {},
        "input_quality": manifest_raw.get("input_quality", {}),
        "retained_quality": manifest_raw.get("retained_quality", {}),
        "stats": summary_raw.get("stats", {}),
        "artifact_validation": "pass" if not errors else "fail",
        "validation_errors": errors,
    }


def _smoke(args: argparse.Namespace) -> int:
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
    commit = _git_commit()
    model = MinerModel(config, dry_run=False)
    run_dir: Path | None = None
    try:
        try:
            result = run_mine(
                workspace_path=workspace,
                idea=args.idea,
                file=args.file,
                kb=args.kb,
                constraints=args.constraints,
                max_iterations=args.iterations,
                profile=args.profile,
                dry_run=False,
                mode=args.mode,
                model=model,
            )
            run_dir = Path(str(result["summary_path"])).parent
        except Exception as exc:
            raw_run_dir = getattr(exc, "run_dir", "")
            if raw_run_dir:
                run_dir = Path(str(raw_run_dir))
            else:
                raise EvaluationError("live run failed before a run directory was created") from exc
    finally:
        model.close()

    if run_dir is None:
        raise EvaluationError("live run did not return a run directory")
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
    return 0 if run_record["status"] == "completed" and run_record["artifact_validation"] == "pass" else 1


def _load_corpus(path: Path) -> tuple[str, list[dict[str, Any]]]:
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
    cases: list[dict[str, Any]] = []
    ids: set[str] = set()
    for raw in raw_cases:
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
        cases.append(case)
    return version, cases


def gate_metrics(outcomes: Sequence[Mapping[str, Any]]) -> dict[str, int | float]:
    """Compute confusion metrics; ``None`` predictions are abstentions."""
    true_positive = true_negative = false_positive = false_negative = abstentions = 0
    for outcome in outcomes:
        expected = bool(outcome["expected_pass"])
        predicted = outcome.get("predicted_pass")
        if predicted is None:
            abstentions += 1
        elif bool(predicted) and expected:
            true_positive += 1
        elif not bool(predicted) and not expected:
            true_negative += 1
        elif bool(predicted):
            false_positive += 1
        else:
            false_negative += 1
    decided = true_positive + true_negative + false_positive + false_negative
    positive_predictions = true_positive + false_positive
    actual_positives = true_positive + false_negative
    return {
        "cases": len(outcomes),
        "decided": decided,
        "true_positives": true_positive,
        "true_negatives": true_negative,
        "false_positives": false_positive,
        "false_negatives": false_negative,
        "abstentions": abstentions,
        "precision": round(true_positive / positive_predictions, 4)
        if positive_predictions
        else 0.0,
        "recall": round(true_positive / actual_positives, 4) if actual_positives else 0.0,
        "abstention_rate": round(abstentions / len(outcomes), 4) if outcomes else 0.0,
    }


def _run_critic_set(
    config: MinerConfig,
    profile: str,
    cases: Sequence[Mapping[str, Any]],
    execution: RunExecutionContext,
) -> dict[str, Any]:
    _guard_critic_config(config)
    routes = _require_api_keys(config, ("critic",))
    provider, model_name = routes["critic"]
    model = MinerModel(config, dry_run=False)
    tracker = UsageTracker()
    started = execution.snapshot()
    outcomes: list[dict[str, Any]] = []
    status = "completed"
    try:
        for case in cases:
            case_id = str(case["id"])
            outcome: dict[str, Any] = {
                "id": case_id,
                "expected_pass": bool(case["expected_pass"]),
                "predicted_pass": None,
                "abstained": True,
            }
            try:
                critique = model.call_json(
                    "critic",
                    CRITIC_SYSTEM,
                    critique_prompt(
                        str(case["draft_json"]),
                        [],
                        _fence_evaluation_evidence(str(case["evidence"])),
                        str(case.get("constraints", "")),
                    ),
                    Critique,
                    usage=tracker,
                    execution=execution,
                )
            except BudgetExceeded:
                status = "budget_exhausted"
                outcome["error_type"] = "BudgetExceeded"
                outcomes.append(outcome)
                for remaining in cases[len(outcomes) :]:
                    outcomes.append(
                        {
                            "id": str(remaining["id"]),
                            "expected_pass": bool(remaining["expected_pass"]),
                            "predicted_pass": None,
                            "abstained": True,
                            "error_type": "BudgetExceeded",
                        }
                    )
                break
            except Exception as exc:
                outcome["error_type"] = type(exc).__name__
            else:
                outcome["predicted_pass"] = critique.passed
                outcome["abstained"] = False
            outcomes.append(outcome)
    finally:
        model.close()
    snapshot = execution.snapshot()
    return {
        "profile": profile,
        "provider": provider,
        "model": model_name,
        "status": status,
        "budget": execution.budget.model_dump(mode="json"),
        "usage": tracker.snapshot().model_dump(mode="json"),
        "admission": {
            "attempts": snapshot.attempts - started.attempts,
            "tokens": snapshot.tokens - started.tokens,
            "elapsed_seconds": round(snapshot.elapsed_seconds - started.elapsed_seconds, 3),
        },
        "metrics": gate_metrics(outcomes),
        "outcomes": outcomes,
    }


def _critic_gate(args: argparse.Namespace) -> int:
    _require_live(args)
    workspace = _require_external_path(args.workspace, "workspace")
    result_path = _require_external_path(args.result, "result")
    if args.profile == args.strong_profile:
        raise EvaluationError("--profile and --strong-profile must select different profiles")
    version, cases = _load_corpus(args.corpus)
    commit = _git_commit()
    flash_config = load_config(workspace, args.profile)
    strong_config = load_config(workspace, args.strong_profile)
    flash_budget = _guard_critic_config(flash_config)
    strong_budget = _guard_critic_config(strong_config)
    if flash_budget != PILOT_BUDGET or strong_budget != PILOT_BUDGET:
        raise EvaluationError("critic-gate profiles must use the exact pilot budget")
    execution = RunExecutionContext("critic-gate", PILOT_BUDGET)
    evaluations = {
        args.profile: _run_critic_set(flash_config, args.profile, cases, execution),
        args.strong_profile: _run_critic_set(strong_config, args.strong_profile, cases, execution),
    }
    aggregate = execution.snapshot()
    payload = {
        "kind": "critic_gate",
        "version": "critic-gate-v1",
        "generated_at": _now(),
        "commit": commit,
        "corpus": {"version": version, "cases": len(cases), "raw_inputs_saved": False},
        "privacy": {"operator_approved_redacted_input": True},
        "aggregate_admission": {
            "attempts": aggregate.attempts,
            "tokens": aggregate.tokens,
            "elapsed_seconds": aggregate.elapsed_seconds,
            "budget": PILOT_BUDGET.model_dump(mode="json"),
        },
        "evaluations": evaluations,
    }
    _write_result(result_path, payload, args.force)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if all(item["status"] == "completed" and item["metrics"]["abstentions"] == 0 for item in evaluations.values()) else 1


def _rating_value(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10:
        raise EvaluationError(f"{label} must be an integer from 0 through 10")
    return value


def _is_placeholder(value: str) -> bool:
    stripped = value.strip().casefold()
    return stripped.startswith("<") and stripped.endswith(">")


def _contains_identity_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            any(part in str(key).casefold() for part in IDENTITY_KEY_PARTS) for key in value
        ) or any(
            _contains_identity_key(child) for child in value.values()
        )
    if isinstance(value, list):
        return any(_contains_identity_key(child) for child in value)
    return False


def weighted_cohens_kappa(first: Sequence[int], second: Sequence[int]) -> float:
    """Return quadratic-weighted Cohen's kappa for the 0–10 rating scale."""
    if len(first) != len(second) or not first:
        raise EvaluationError("kappa requires paired, non-empty ratings")
    size = 11
    observed = [[0.0] * size for _ in range(size)]
    for left, right in zip(first, second):
        observed[left][right] += 1.0 / len(first)
    left_hist = [sum(row) for row in observed]
    right_hist = [sum(observed[row][column] for row in range(size)) for column in range(size)]
    expected = [[left_hist[row] * right_hist[column] for column in range(size)] for row in range(size)]
    denominator = 0.0
    numerator = 0.0
    for row in range(size):
        for column in range(size):
            weight = ((row - column) / 10) ** 2
            numerator += weight * observed[row][column]
            denominator += weight * expected[row][column]
    return round(1.0 - numerator / denominator, 4) if denominator else 1.0


def summarize_ratings(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate two blinded raters and calculate the predeclared score card."""
    if payload.get("blinded") is not True:
        raise EvaluationError("ratings must declare blinded=true")
    commit = payload.get("commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-fA-F]{7,40}", commit):
        raise EvaluationError("ratings must include the evaluated commit")
    if _contains_identity_key(payload):
        raise EvaluationError("ratings must not contain provider or model identity fields")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or len(raw_items) < 10:
        raise EvaluationError("ratings require at least 10 reviewable opportunities")
    scores: dict[str, list[tuple[int, int]]] = {dimension: [] for dimension in RATING_DIMENSIONS}
    disagreements: list[str] = []
    publication_disagreements: list[str] = []
    critical_claims: list[str] = []
    domains: set[str] = set()
    abstentions: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        item = _mapping(raw, "rating item")
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id or item_id in seen:
            raise EvaluationError("rating item ids must be unique non-empty strings")
        seen.add(item_id)
        domain = item.get("domain")
        if not isinstance(domain, str) or not domain.strip():
            raise EvaluationError(f"{item_id}.domain is required")
        domains.add(domain.strip())
        first = _mapping(item.get("rater_a"), f"{item_id}.rater_a")
        second = _mapping(item.get("rater_b"), f"{item_id}.rater_b")
        max_difference = 0
        for dimension in RATING_DIMENSIONS:
            left = _rating_value(first.get(dimension), f"{item_id}.rater_a.{dimension}")
            right = _rating_value(second.get(dimension), f"{item_id}.rater_b.{dimension}")
            scores[dimension].append((left, right))
            max_difference = max(max_difference, abs(left - right))
        if max_difference > 2:
            disagreements.append(item_id)
        for label, rater in (("rater_a", first), ("rater_b", second)):
            if rater.get("publication_decision") not in {"publish", "filter", "abstain"}:
                raise EvaluationError(f"{item_id}.{label}.publication_decision is invalid")
            if not isinstance(rater.get("critical_unsupported_current_state_claim"), bool):
                raise EvaluationError(
                    f"{item_id}.{label}.critical_unsupported_current_state_claim must be boolean"
                )
            assessments = rater.get("claim_assessments")
            if not isinstance(assessments, list) or not assessments:
                raise EvaluationError(f"{item_id}.{label}.claim_assessments is required")
            for assessment in assessments:
                claim = _mapping(assessment, f"{item_id}.{label}.claim_assessment")
                if (
                    not isinstance(claim.get("claim_id"), str)
                    or not claim["claim_id"]
                    or _is_placeholder(claim["claim_id"])
                ):
                    raise EvaluationError(f"{item_id}.{label}.claim_id is required")
                refs = claim.get("evidence_refs")
                if not isinstance(refs, list) or not refs or any(
                    not isinstance(ref, str) or not ref or _is_placeholder(ref) for ref in refs
                ):
                    raise EvaluationError(f"{item_id}.{label}.evidence_refs is required")
                if claim.get("epistemic_status") not in EPISTEMIC_STATUSES:
                    raise EvaluationError(f"{item_id}.{label}.epistemic_status is invalid")
        if first["publication_decision"] != second["publication_decision"]:
            publication_disagreements.append(item_id)
        if "abstain" in {first["publication_decision"], second["publication_decision"]}:
            abstentions.append(item_id)
        if first.get("critical_unsupported_current_state_claim") is True or second.get(
            "critical_unsupported_current_state_claim"
        ) is True:
            critical_claims.append(item_id)

    if not 2 <= len(domains) <= 3:
        raise EvaluationError("ratings must cover two or three domains")

    per_dimension: dict[str, dict[str, Any]] = {}
    all_scores: list[int] = []
    for dimension, pairs in scores.items():
        left = [pair[0] for pair in pairs]
        right = [pair[1] for pair in pairs]
        all_scores.extend(left + right)
        per_dimension[dimension] = {
            "mean": round(sum(left + right) / (2 * len(pairs)), 3),
            "weighted_cohens_kappa": weighted_cohens_kappa(left, right),
        }
    means = {dimension: item["mean"] for dimension, item in per_dimension.items()}
    overall = round(sum(all_scores) / len(all_scores), 3)
    adjudication_required = sorted(
        set(disagreements + publication_disagreements + abstentions)
    )
    agreement_pass = all(
        item["weighted_cohens_kappa"] >= MIN_WEIGHTED_KAPPA for item in per_dimension.values()
    )
    threshold_pass = (
        means["groundedness"] >= 7.0
        and means["honesty"] >= 7.0
        and means["actionability"] >= 6.0
        and means["specificity"] >= 6.0
        and overall >= 6.0
        and not critical_claims
        and agreement_pass
        and not adjudication_required
    )
    return {
        "items": len(raw_items),
        "domains": sorted(domains),
        "per_dimension": per_dimension,
        "minimum_weighted_kappa": MIN_WEIGHTED_KAPPA,
        "agreement_pass": agreement_pass,
        "overall_mean": overall,
        "disagreements_over_2": disagreements,
        "publication_decision_disagreements": publication_disagreements,
        "critical_unsupported_current_state_claims": critical_claims,
        "adjudication_required": adjudication_required,
        "thresholds_pass": threshold_pass,
    }


def _score(args: argparse.Namespace) -> int:
    ratings_path = _require_external_path(args.ratings, "ratings")
    result_path = _require_external_path(args.result, "result")
    payload = _load_object(ratings_path)
    record = {
        "kind": "human_rating_summary",
        "version": "human-rating-summary-v1",
        "generated_at": _now(),
        "commit": str(payload.get("commit", "")),
        "ratings_version": str(payload.get("version", "")),
        "privacy": {"raw_ratings_saved": False},
        "summary": summarize_ratings(payload),
    }
    _write_result(result_path, record, args.force)
    print(json.dumps(record, indent=2, ensure_ascii=False))
    return 0 if record["summary"]["thresholds_pass"] else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Guarded real-provider evaluation harness.")
    commands = parser.add_subparsers(dest="command", required=True)

    smoke = commands.add_parser("smoke", help="Run one bounded live mining invocation.")
    smoke_input = smoke.add_mutually_exclusive_group(required=True)
    smoke_input.add_argument("--idea")
    smoke_input.add_argument("--file", type=Path)
    smoke_input.add_argument("--kb", type=Path)
    smoke.add_argument("--workspace", type=Path, required=True)
    smoke.add_argument("--profile", default="live_flash")
    smoke.add_argument("--constraints", default="")
    smoke.add_argument("--iterations", type=int, default=1)
    smoke.add_argument("--mode", choices=("auto", "operational", "strategy"), default="auto")
    smoke.add_argument("--result", type=Path, required=True)
    smoke.add_argument("--live", action="store_true")
    smoke.add_argument("--privacy-approved", action="store_true")
    smoke.add_argument("--force", action="store_true")

    gate = commands.add_parser("critic-gate", help="Evaluate the labelled critic corpus twice.")
    gate.add_argument("--workspace", type=Path, required=True)
    gate.add_argument("--profile", default="live_flash")
    gate.add_argument("--strong-profile", required=True)
    gate.add_argument("--corpus", type=Path, required=True)
    gate.add_argument("--result", type=Path, required=True)
    gate.add_argument("--live", action="store_true")
    gate.add_argument("--privacy-approved", action="store_true")
    gate.add_argument("--force", action="store_true")

    score = commands.add_parser("score", help="Summarize two blinded human rating sheets.")
    score.add_argument("--ratings", type=Path, required=True)
    score.add_argument("--result", type=Path, required=True)
    score.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "smoke":
            return _smoke(args)
        if args.command == "critic-gate":
            return _critic_gate(args)
        return _score(args)
    except EvaluationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
