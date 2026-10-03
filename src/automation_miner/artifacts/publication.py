"""Crash-safe publication journal and recovery helpers."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from automation_miner.artifacts.failure_marks import (
    mark_manifest_failed,
    mark_portfolio_failed,
    mark_summary_failed,
)
from automation_miner.artifacts.layout import RunLayout
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
    path = RunLayout(run_dir).journal
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


def _promote_one(run_dir: Path, workspace_root: Path, item: dict[str, str]) -> None:
    """Move one staged brief into opps/, idempotently and without clobbering."""
    from automation_miner.artifacts.registry import parse_frontmatter

    staged, target = run_dir / item["staged"], workspace_root / item["target"]
    if not staged.is_file():
        if not target.is_file():
            raise RuntimeError(f"Publication source is missing: {staged}")
        return
    if target.exists():
        try:
            owner = parse_frontmatter(target.read_text(encoding="utf-8")).get("source")
        except OSError:
            owner = None
        if owner != run_dir.name:
            raise RuntimeError(f"Refusing to overwrite existing brief: {target}")
        staged.unlink()
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    staged.replace(target)


def promote_publication(
    run_dir: Path, workspace_root: Path, files: list[dict[str, str]]
) -> None:
    """Promote staged files idempotently under the workspace mutation lock."""
    write_publication_journal(run_dir, "promoting", files=files)
    with workspace_transaction_lock(workspace_root):
        for item in files:
            _promote_one(run_dir, workspace_root, item)
        write_publication_journal(run_dir, "promoted", files=files)


def _read_dict(path: Path) -> dict[str, object] | None:
    try:
        value = read_json(path) if path.is_file() else None
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _recover_run(base: Path, run_dir: Path, journal: dict[str, object]) -> None:
    state = journal.get("state")
    if state in {"complete", "quarantined"}:
        return
    manifest = _read_dict(run_dir / "run.json") or {}
    committed = (
        manifest.get("status") == "completed" and manifest.get("publication_status") == "complete"
    )
    # The manifest is the commit record when a process died after its final
    # write but before advancing the journal marker.
    if state == "manifest_complete" or (state in ACTIVE_STATES and committed):
        complete_publication_views(run_dir)
        write_publication_journal(run_dir, "complete")
        return
    if state in ACTIVE_STATES and not _pid_alive(journal.get("pid")):
        _quarantine_interrupted_run(base, run_dir)
        write_publication_journal(run_dir, "quarantined")


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
        journal = _read_dict(RunLayout(run_dir).journal)
        if journal is not None:
            _recover_run(base, run_dir, journal)


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


def _params(manifest: dict[str, object]) -> dict[str, str]:
    raw = manifest.get("constraint_params", {})
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def _duration(manifest: dict[str, object]) -> float:
    raw = manifest.get("duration_seconds", 0.0)
    try:
        return float(raw) if isinstance(raw, (int, float, str)) else 0.0
    except ValueError:
        return 0.0


def _recovery_summary(
    run_dir: Path, manifest: dict[str, object], total: int
) -> dict[str, object]:
    """Create the minimum valid summary when recovery precedes normal views."""
    from automation_miner.schemas import RunSummary

    payload = RunSummary(
        run_id=run_dir.name, domain=str(manifest.get("domain", run_dir.name)),
        domain_slug=str(manifest.get("domain_slug", "unknown")),
        constraints=str(manifest.get("constraints", "")),
        raw_constraints=str(manifest.get("raw_constraints", "")),
        constraint_params=_params(manifest), created=str(manifest.get("created", "")),
        status="failed", publication_status="pending", duration_seconds=_duration(manifest),
        dry_run=bool(manifest.get("dry_run", False)), opportunities=[],
        notes=["Publication was interrupted before summary rendering.", "See error.json."],
    )
    data = payload.model_dump(mode="json")
    stats = data["stats"]
    if isinstance(stats, dict):
        stats.update({"total": total, "filtered": total})
    return data


_RECOVERED_REPORT = (
    "# Automation Mining Report: {domain}\n\n"
    "> **Run:** `{run_id}`  \n"
    "> **Status:** failed  \n"
    "> **Publication:** pending  \n"
    "> **Published opportunities:** 0  \n\n"
    "## Failure\n\n"
    "Publication was interrupted and its artifacts were quarantined.\n"
)


def _mark_views_failed(run_dir: Path, manifest: dict[str, object], moved: int) -> None:
    summary_path = run_dir / "summary.json"
    summary = _read_dict(summary_path)
    if summary is not None:
        mark_summary_failed(summary, "failed")
    else:
        ids = manifest.get("filtered", [])
        summary = _recovery_summary(run_dir, manifest, len(ids) if isinstance(ids, list) else moved)
    write_json(summary_path, summary)
    portfolio = _read_dict(run_dir / "opportunities.json")
    if portfolio is not None:
        mark_portfolio_failed(portfolio, "failed")
        write_json(run_dir / "opportunities.json", portfolio)
    domain = (_read_dict(run_dir / "run.json") or {}).get("domain", run_dir.name)
    write_text(run_dir / "report.md", _RECOVERED_REPORT.format(domain=domain, run_id=run_dir.name))


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


__all__ = [
    "ACTIVE_STATES",
    "complete_publication_views",
    "mark_manifest_failed",
    "mark_portfolio_failed",
    "mark_summary_failed",
    "promote_publication",
    "quarantine_run_briefs",
    "recover_publications",
    "write_publication_journal",
]
