"""Mark a run's consumer-facing artifacts as failed without losing their content."""

from __future__ import annotations

from datetime import datetime


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


def _empty_stats(filtered: int) -> dict[str, object]:
    """Publication-derived statistics a failed run must not keep (fresh each call)."""
    return {
        "published": 0, "filtered": filtered, "avg_ice": 0.0, "median_ice": 0.0,
        "top_ice": 0, "top_id": "", "by_layer": {}, "by_tier": {}, "filters": {},
    }


def _unpublish(entry: dict[str, object]) -> None:
    entry["brief_path"] = ""
    if entry.get("eligibility") == "published":
        entry["eligibility"] = "filtered"
        reasons = entry.get("exclusion_reasons", [])
        entry["exclusion_reasons"] = [
            *(reasons if isinstance(reasons, list) else []),
            "publication interrupted before completion",
        ]


def mark_summary_failed(summary: dict[str, object], status: str) -> None:
    """Clear publication-derived summary fields for a failed run."""
    summary.update({"status": status, "publication_status": "pending"})
    opportunities = summary.get("opportunities", [])
    if not isinstance(opportunities, list):
        opportunities = []
        summary["opportunities"] = opportunities
    for entry in opportunities:
        if isinstance(entry, dict):
            _unpublish(entry)
    stats = summary.get("stats")
    if isinstance(stats, dict):
        stats.update(_empty_stats(len(opportunities)))


def mark_portfolio_failed(portfolio: dict[str, object], status: str) -> None:
    """Clear publication-derived portfolio statistics for a failed run."""
    portfolio.update(
        {"status": status, "publication_status": "pending", "published_opportunities": []}
    )
    stats = portfolio.get("stats")
    if isinstance(stats, dict):
        total = stats.get("total", 0)
        stats.update(_empty_stats(total if isinstance(total, int) else 0))
