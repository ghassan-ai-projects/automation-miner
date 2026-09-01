"""Crash-safe publication journal and recovery helpers."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from automation_miner.artifacts.workspace import (
    read_json,
    workspace_transaction_lock,
    write_json,
    write_text,
)

ACTIVE_STATES = frozenset({"staged", "promoting", "promoted", "views_written"})


def write_publication_journal(
    run_dir: Path,
    state: str,
    *,
    files: list[dict[str, str]] | None = None,
) -> None:
    """Atomically advance a run's publication journal."""
    path = run_dir / "publication.json"
    current = read_json(path) if path.is_file() else {}
    payload = dict(current) if isinstance(current, dict) else {}
    payload.update(
        {
            "run_id": run_dir.name,
            "state": state,
            "pid": os.getpid(),
            "updated": f"{datetime.now():%Y-%m-%dT%H:%M:%S}",
        }
    )
    if files is not None:
        payload["files"] = files
    write_json(path, payload)


def promote_publication(
    run_dir: Path, workspace_root: Path, files: list[dict[str, str]]
) -> None:
    """Promote staged files idempotently under the workspace mutation lock."""
    write_publication_journal(run_dir, "promoting", files=files)
    with workspace_transaction_lock(workspace_root):
        for item in files:
            staged = run_dir / item["staged"]
            target = workspace_root / item["target"]
            if staged.is_file():
                if target.exists():
                    from automation_miner.artifacts.registry import parse_frontmatter

                    try:
                        existing_source = parse_frontmatter(
                            target.read_text(encoding="utf-8")
                        ).get("source")
                    except OSError:
                        existing_source = None
                    if existing_source != run_dir.name:
                        raise RuntimeError(f"Refusing to overwrite existing brief: {target}")
                    staged.unlink()
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                staged.replace(target)
            elif not target.is_file():
                raise RuntimeError(f"Publication source is missing: {staged}")
        write_publication_journal(run_dir, "promoted", files=files)


def recover_publications(base: Path) -> None:
    """Recover or quarantine interrupted publication transactions.

    A live publisher is left alone. A dead publisher's partial promotion is
    quarantined and marked failed. A run whose manifest reached the terminal
    state is completed idempotently, including its human/agent-facing views.
    """
    runs_dir = base / "runs"
    if not runs_dir.is_dir():
        return
    for run_dir in sorted(path for path in runs_dir.iterdir() if path.is_dir()):
        journal_path = run_dir / "publication.json"
        if not journal_path.is_file():
            continue
        try:
            journal = read_json(journal_path)
        except (OSError, ValueError):
            continue
        if not isinstance(journal, dict):
            continue
        state = journal.get("state")
        if state == "complete" or state == "quarantined":
            continue
        if state == "manifest_complete":
            complete_publication_views(run_dir)
            write_publication_journal(run_dir, "complete")
            continue
        manifest_path = run_dir / "run.json"
        try:
            manifest = read_json(manifest_path) if manifest_path.is_file() else {}
        except (OSError, ValueError):
            manifest = {}
        if (
            state in ACTIVE_STATES
            and isinstance(manifest, dict)
            and manifest.get("status") == "completed"
            and manifest.get("publication_status") == "complete"
        ):
            # The manifest is the commit record when a process died after its
            # final write but before advancing the journal marker.
            complete_publication_views(run_dir)
            write_publication_journal(run_dir, "complete")
            continue
        if state not in ACTIVE_STATES or _pid_alive(journal.get("pid")):
            continue
        _quarantine_interrupted_run(base, run_dir)
        write_publication_journal(run_dir, "quarantined")


def _pid_alive(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return False
    try:
        os.kill(value, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _quarantine_interrupted_run(base: Path, run_dir: Path) -> None:
    moved = quarantine_run_briefs(base, run_dir)

    manifest_path = run_dir / "run.json"
    try:
        raw_manifest = read_json(manifest_path) if manifest_path.is_file() else {}
    except (OSError, ValueError):
        raw_manifest = {}
    manifest = raw_manifest if isinstance(raw_manifest, dict) else {}
    mark_manifest_failed(manifest, "failed")
    write_json(manifest_path, manifest)
    error_path = run_dir / "error.json"
    if not error_path.is_file():
        write_json(
            error_path,
            {
                "run_id": run_dir.name,
                "stage": "publish",
                "error_type": "PublicationRecovery",
                "error": "publisher exited before publication completed",
                "created": f"{datetime.now():%Y-%m-%dT%H:%M:%S}",
                "status": "failed",
                "quarantined_artifacts": moved,
            },
        )
    _mark_views_failed(run_dir, manifest, len(moved))


def quarantine_run_briefs(base: Path, run_dir: Path) -> list[str]:
    """Move all global briefs owned by a run into its quarantine tree."""
    from automation_miner.artifacts.registry import parse_frontmatter

    opps_dir = base / "opps"
    quarantine_root = run_dir / "quarantine" / "opps"
    moved: list[str] = []
    if not opps_dir.is_dir():
        return moved
    for brief in opps_dir.rglob("AM-*.md"):
        try:
            if parse_frontmatter(brief.read_text(encoding="utf-8")).get("source") != run_dir.name:
                continue
            target = quarantine_root / brief.relative_to(opps_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            brief.replace(target)
            moved.append(str(target.relative_to(run_dir)))
        except (OSError, ValueError):
            continue
    return moved


def mark_manifest_failed(manifest: dict[str, object], status: str) -> None:
    """Project a failed run as having no published opportunity IDs."""
    opportunities = manifest.get("opportunities", [])
    filtered = manifest.get("filtered", [])
    ids = [
        *(opportunities if isinstance(opportunities, list) else []),
        *(filtered if isinstance(filtered, list) else []),
    ]
    manifest.update(
        {
            "status": status,
            "publication_status": "pending",
            "finished": f"{datetime.now():%Y-%m-%dT%H:%M:%S}",
            "opportunities": [],
            "filtered": list(dict.fromkeys(str(item) for item in ids)),
        }
    )


def mark_summary_failed(summary: dict[str, object], status: str) -> None:
    """Clear publication-derived summary fields for a failed run."""
    summary.update({"status": status, "publication_status": "pending"})
    opportunities = summary.get("opportunities", [])
    if not isinstance(opportunities, list):
        opportunities = []
        summary["opportunities"] = opportunities
    for entry in opportunities:
        if not isinstance(entry, dict):
            continue
        entry["brief_path"] = ""
        if entry.get("eligibility") == "published":
            entry["eligibility"] = "filtered"
            reasons = entry.get("exclusion_reasons", [])
            entry["exclusion_reasons"] = [
                *(reasons if isinstance(reasons, list) else []),
                "publication interrupted before completion",
            ]
    stats = summary.get("stats")
    if isinstance(stats, dict):
        stats.update(
            {
                "published": 0,
                "filtered": len(opportunities),
                "avg_ice": 0.0,
                "median_ice": 0.0,
                "top_ice": 0,
                "top_id": "",
                "by_layer": {},
                "by_tier": {},
                "filters": {},
            }
        )


def mark_portfolio_failed(portfolio: dict[str, object], status: str) -> None:
    """Clear publication-derived portfolio statistics for a failed run."""
    portfolio.update(
        {"status": status, "publication_status": "pending", "published_opportunities": []}
    )
    stats = portfolio.get("stats")
    if isinstance(stats, dict):
        total = stats.get("total", 0)
        stats.update(
            {
                "published": 0,
                "filtered": total if isinstance(total, int) else 0,
                "avg_ice": 0.0,
                "median_ice": 0.0,
                "top_ice": 0,
                "top_id": "",
                "by_layer": {},
                "by_tier": {},
                "filters": {},
            }
        )


def _recovery_summary(
    run_dir: Path, manifest: dict[str, object], total: int
) -> dict[str, object]:
    """Create the minimum valid summary when recovery precedes normal views."""
    from automation_miner.schemas import RunSummary

    raw_params = manifest.get("constraint_params", {})
    params = (
        {str(key): str(value) for key, value in raw_params.items()}
        if isinstance(raw_params, dict)
        else {}
    )
    raw_duration = manifest.get("duration_seconds", 0.0)
    try:
        duration = (
            float(raw_duration)
            if isinstance(raw_duration, (int, float, str))
            else 0.0
        )
    except ValueError:
        duration = 0.0
    payload = RunSummary(
        run_id=run_dir.name,
        domain=str(manifest.get("domain", run_dir.name)),
        domain_slug=str(manifest.get("domain_slug", "unknown")),
        constraints=str(manifest.get("constraints", "")),
        raw_constraints=str(manifest.get("raw_constraints", "")),
        constraint_params=params,
        created=str(manifest.get("created", "")),
        status="failed",
        publication_status="pending",
        duration_seconds=duration,
        dry_run=bool(manifest.get("dry_run", False)),
        opportunities=[],
        notes=["Publication was interrupted before summary rendering.", "See error.json."],
    )
    data = payload.model_dump(mode="json")
    stats = data["stats"]
    if isinstance(stats, dict):
        stats["total"] = total
        stats["filtered"] = total
    return data


def _mark_views_failed(run_dir: Path, manifest: dict[str, object], moved: int) -> None:
    summary_path = run_dir / "summary.json"
    if summary_path.is_file():
        summary = read_json(summary_path)
        if isinstance(summary, dict):
            mark_summary_failed(summary, "failed")
            write_json(summary_path, summary)
    else:
        ids = manifest.get("filtered", [])
        total = len(ids) if isinstance(ids, list) else moved
        write_json(summary_path, _recovery_summary(run_dir, manifest, total))
    portfolio_path = run_dir / "opportunities.json"
    if portfolio_path.is_file():
        portfolio = read_json(portfolio_path)
        if isinstance(portfolio, dict):
            mark_portfolio_failed(portfolio, "failed")
            write_json(portfolio_path, portfolio)
    report_path = run_dir / "report.md"
    manifest = read_json(run_dir / "run.json") if (run_dir / "run.json").is_file() else {}
    domain = manifest.get("domain", run_dir.name) if isinstance(manifest, dict) else run_dir.name
    write_text(
        report_path,
        f"# Automation Mining Report — {domain}\n\n"
        f"> **Run:** `{run_dir.name}`  \n"
        "> **Status:** failed  \n"
        "> **Publication:** pending  \n"
        "> **Published opportunities:** 0  \n\n"
        "## Failure\n\n"
        "Publication was interrupted and its artifacts were quarantined.\n",
    )


def complete_publication_views(run_dir: Path) -> None:
    summary_path = run_dir / "summary.json"
    if summary_path.is_file():
        summary = read_json(summary_path)
        if isinstance(summary, dict):
            summary.update({"status": "completed", "publication_status": "complete"})
            write_json(summary_path, summary)
    report_path = run_dir / "report.md"
    if report_path.is_file():
        report = report_path.read_text(encoding="utf-8")
        report = report.replace("> **Publication:** pending  ", "> **Publication:** complete  ", 1)
        write_text(report_path, report)
