"""Validate a terminal live run's artifacts and return only redacted metadata."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from automation_miner.artifacts.layout import RunLayout
from automation_miner.artifacts.workspace import read_json
from automation_miner.evaluation.live.common import EvaluationError, _load_object, _mapping
from automation_miner.schemas import (
    ContextPacket,
    Opportunity,
    RunManifest,
    RunSummary,
    StageFailure,
)

_INVALID = (EvaluationError, OSError, ValueError, TypeError)


def _source_descriptor(manifest: Mapping[str, Any]) -> dict[str, str]:
    kind = str(manifest.get("source_kind", "unknown"))
    if kind == "idea":
        name = "<redacted-idea>"
    else:
        name = "<redacted-source>"
    return {"kind": kind, "name": name}


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


def _check_summary_header(
    summary: Mapping[str, Any], manifest: Mapping[str, Any], publication_status: str,
    errors: list[str],
) -> None:
    expected = {
        "status": "completed",
        "publication_status": publication_status,
        **{key: manifest.get(key) for key in ("domain", "domain_slug", "usage", "budget")},
    }
    for key, value in expected.items():
        if summary.get(key) != value:
            errors.append(f"summary-{key.replace('_', '-')}-mismatch")


def _load_opportunities(run_dir: Path) -> list[Opportunity]:
    raw = _load_object(run_dir / "opportunities.json").get("opportunities", [])
    if not isinstance(raw, list):
        raise EvaluationError("opportunities is not a list")
    return [Opportunity.model_validate(item) for item in raw]


def _check_published_ids(
    opportunities: list[Opportunity], manifest: Mapping[str, Any], known_ids: set[str],
    errors: list[str],
) -> tuple[set[str], set[str]]:
    """Published ids must match the manifest, be unique, and cite known evidence."""
    published = [opportunity.am_id for opportunity in opportunities if opportunity.published]
    values = manifest.get("opportunities", [])
    if not isinstance(values, list):
        raise EvaluationError("manifest opportunities is not a list")
    live_ids, manifest_ids = set(published), set(values)
    if len(manifest_ids) != len(values):
        errors.append("duplicate-manifest-opportunity-ids")
    if len(live_ids) != len(published):
        errors.append("duplicate-published-opportunity-ids")
    if live_ids != manifest_ids:
        errors.append("manifest-opportunity-mismatch")
    for opportunity in opportunities:
        unknown = set(opportunity.draft.evidence_refs) - known_ids
        if opportunity.published and (unknown or opportunity.unresolved_refs):
            errors.append(f"unresolved-published-refs-{opportunity.am_id}")
    return live_ids, manifest_ids


def _check_summary_entries(
    summary: Mapping[str, Any], opportunities: list[Opportunity], live_ids: set[str],
    manifest_ids: set[str], errors: list[str],
) -> None:
    """The summary lists every ranked opportunity once, with matching counts."""
    stats = _mapping(summary.get("stats", {}), "summary stats")
    if stats.get("total") != len(opportunities):
        errors.append("summary-total-mismatch")
    entries = summary.get("opportunities", [])
    if not isinstance(entries, list):
        raise EvaluationError("summary opportunities is not a list")
    tables = [entry for entry in entries if isinstance(entry, dict)]
    summary_ids = {str(entry.get("am_id")) for entry in tables}
    opportunity_ids = {opportunity.am_id for opportunity in opportunities}
    published = {str(e.get("am_id")) for e in tables if e.get("eligibility") == "published"}
    checks = (
        ("duplicate-summary-opportunity-ids", len(summary_ids) != len(entries)),
        ("duplicate-ranked-opportunity-ids", len(opportunity_ids) != len(opportunities)),
        ("summary-opportunity-set-mismatch", summary_ids != opportunity_ids),
        ("summary-opportunity-mismatch", published != manifest_ids),
        ("summary-published-count-mismatch", stats.get("published") != len(live_ids)),
        ("summary-filtered-count-mismatch",
         stats.get("filtered") != len(opportunities) - len(live_ids)),
    )
    errors.extend(code for code, failed in checks if failed)


def _check_consistency(
    run_dir: Path, summary: Mapping[str, Any], manifest: Mapping[str, Any],
    publication_status: str, errors: list[str],
) -> None:
    RunSummary.model_validate(summary)
    _check_summary_header(summary, manifest, publication_status, errors)
    context = ContextPacket.model_validate(read_json(RunLayout(run_dir).context))
    opportunities = _load_opportunities(run_dir)
    live_ids, manifest_ids = _check_published_ids(
        opportunities, manifest, context.chunk_ids(), errors
    )
    _check_summary_entries(summary, opportunities, live_ids, manifest_ids, errors)


def _check_completed(
    run_dir: Path, manifest: Mapping[str, Any], publication_status: str, errors: list[str]
) -> Mapping[str, Any]:
    """Validate a completed run's results and return its summary (empty if unreadable)."""
    if publication_status != "complete":
        errors.append("publication-not-complete")
    layout = RunLayout(run_dir)
    for path in (layout.summary, layout.report, layout.opportunities, layout.context):
        if not path.is_file():
            errors.append(f"missing-{path.name}")
    summary: Mapping[str, Any] = {}
    try:
        summary = _load_object(run_dir / "summary.json")
        _check_consistency(run_dir, summary, manifest, publication_status, errors)
    except _INVALID:
        errors.append("completed-artifact-schema-invalid")
    return summary


def _check_failed(run_dir: Path, status: str, errors: list[str]) -> None:
    error_path = run_dir / "error.json"
    if not error_path.is_file():
        errors.append("missing-error.json")
        return
    try:
        error = _load_object(error_path)
        StageFailure.model_validate(error)
        if error.get("status") != status:
            errors.append("error-status-mismatch")
    except (EvaluationError, ValueError, TypeError):
        errors.append("error-artifact-invalid")


def _as_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _redacted_record(
    run_dir: Path, manifest: Mapping[str, Any], summary: Mapping[str, Any], errors: list[str]
) -> dict[str, Any]:
    return {
        "run_id": str(manifest.get("run_id", run_dir.name)),
        "status": str(manifest.get("status", "unknown")),
        "publication_status": str(manifest.get("publication_status", "unknown")),
        "source": _source_descriptor(manifest),
        "models": _as_dict(manifest.get("models")),
        "budget": _as_dict(manifest.get("budget")),
        "usage": _as_dict(manifest.get("usage")),
        "input_quality": manifest.get("input_quality", {}),
        "retained_quality": manifest.get("retained_quality", {}),
        "stats": summary.get("stats", {}),
        "artifact_validation": "pass" if not errors else "fail",
        "validation_errors": errors,
    }


def validate_run_artifacts(run_dir: Path) -> dict[str, Any]:
    """Validate terminal run invariants and return only redacted metadata."""
    errors: list[str] = []
    manifest: Mapping[str, Any]
    try:
        manifest = _load_object(run_dir / "run.json")
        RunManifest.model_validate(manifest)
    except (EvaluationError, ValueError):
        manifest = {}
        errors.append("manifest-invalid-or-missing")
    status = str(manifest.get("status", "unknown"))
    errors.extend(_usage_budget_errors(manifest) if manifest else [])
    summary: Mapping[str, Any] = {}
    if status == "completed":
        publication_status = str(manifest.get("publication_status", "unknown"))
        summary = _check_completed(run_dir, manifest, publication_status, errors)
    elif status in {"failed", "budget_exhausted"}:
        _check_failed(run_dir, status, errors)
    else:
        errors.append("run-not-terminal")
    return _redacted_record(run_dir, manifest, summary, errors)
