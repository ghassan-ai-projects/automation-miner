"""Build the compact registry index from published opportunity briefs.

Scans ``opps/<domain-slug>/AM-*.md``, parses YAML frontmatter (pyyaml instead
of a regex parser), and builds the compact cross-indexed registry.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from automation_miner.schemas import OppStatus, Tier

LAYERS = ("document", "communication", "decision", "monitoring", "knowledge")
ICE_RANGES = ("vision_80plus", "high_60_79", "medium_40_59", "low_under_40")
STATUSES = tuple(status.value for status in OppStatus)
STATUS_ALIASES = {"validating": OppStatus.EVALUATING.value, "building": OppStatus.IMPLEMENTING.value}
_BRIEF_ID_RE = re.compile(r"^(AM-\d+)-")
_AM_ID_RE = re.compile(r"AM-\d+")
_RUN_ID_RE = re.compile(r"\d{4}-\d{2}-\d{2}_[a-z0-9]+(?:-[a-z0-9]+)*")


def parse_frontmatter(text: str) -> dict[str, Any]:
    """Extract YAML frontmatter from a brief; empty dict if absent/invalid."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    try:
        data = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_registry(base: Path) -> dict[str, Any]:
    """Build the registry dict from a workspace root."""
    opps_dir = base / "opps"
    entries: list[dict[str, Any]] = []
    domains: dict[str, dict[str, Any]] = {}
    warnings: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    if opps_dir.exists():
        for domain_dir in sorted(p for p in opps_dir.iterdir() if p.is_dir()):
            slug = domain_dir.name
            domain_entries: list[dict[str, Any]] = []
            for f in sorted(domain_dir.glob("AM-*.md")):
                meta = parse_frontmatter(f.read_text(encoding="utf-8"))
                filename_match = _BRIEF_ID_RE.match(f.name)
                filename_id = filename_match.group(1) if filename_match else ""
                am_id = str(meta.get("am-id", "")).upper()
                if not _AM_ID_RE.fullmatch(am_id) or am_id != filename_id:
                    warnings.append(
                        {"file": str(f), "reason": "frontmatter am-id is missing or mismatched"}
                    )
                    continue
                source_value = meta.get("source")
                if not isinstance(source_value, str) or not _RUN_ID_RE.fullmatch(source_value):
                    warnings.append({"file": str(f), "reason": "missing or invalid source run"})
                    continue
                source_run = source_value
                manifest_path = base / "runs" / source_run / "run.json"
                try:
                    run_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    run_manifest = None
                run_status = (
                    run_manifest.get("status") if isinstance(run_manifest, dict) else None
                )
                publication_status = (
                    run_manifest.get("publication_status")
                    if isinstance(run_manifest, dict)
                    else None
                )
                opportunities = (
                    run_manifest.get("opportunities", [])
                    if isinstance(run_manifest, dict)
                    else []
                )
                if (
                    run_status != "completed"
                    or publication_status != "complete"
                    or not isinstance(opportunities, list)
                    or am_id not in opportunities
                ):
                    warnings.append(
                        {
                            "file": str(f),
                            "reason": (
                                f"source run {source_run} is {run_status or 'unreadable'}"
                                + (
                                    f" / publication {publication_status or 'unreadable'}"
                                    if run_status == "completed"
                                    else ""
                                )
                            ),
                        }
                    )
                    continue
                if am_id in seen_ids:
                    warnings.append({"file": str(f), "reason": f"duplicate opportunity id {am_id}"})
                    continue
                seen_ids.add(am_id)
                ice = _int(meta.get("ice-score")) or 0
                entry: dict[str, Any] = {
                    "i": am_id,
                    "t": str(meta.get("title", f.stem)),
                    "l": str(meta.get("layer", "unknown")),
                    "ice": ice,
                    # Derived rather than trusted: a brief edited by hand can carry a
                    # tier that no longer matches its score.
                    "tr": Tier.for_ice(ice).value,
                    "d": slug,
                    "s": _status(meta.get("status")),
                    "f": str(f),
                }
                for key, short in (("impact", "im"), ("confidence", "co"), ("ease", "ea")):
                    v = _int(meta.get(key))
                    if v is not None:
                        entry[short] = v
                entries.append(entry)
                domain_entries.append(entry)

            if domain_entries:
                top = max(domain_entries, key=lambda e: e["ice"])
                domains[slug] = {
                    "id": slug,
                    "title": slug.replace("-", " ").title(),
                    "slug": slug,
                    "total": len(domain_entries),
                    "top_ice": top["ice"],
                    "top_opp": top["i"],
                }

    by_layer: dict[str, list[str]] = {layer: [] for layer in LAYERS}
    by_ice_range: dict[str, list[str]] = {r: [] for r in ICE_RANGES}
    by_status: dict[str, list[str]] = {s: [] for s in STATUSES}

    for e in entries:
        if e["l"] in by_layer:
            by_layer[e["l"]].append(e["i"])
        ice = e["ice"]
        if ice >= 80:
            by_ice_range["vision_80plus"].append(e["i"])
        elif ice >= 60:
            by_ice_range["high_60_79"].append(e["i"])
        elif ice >= 40:
            by_ice_range["medium_40_59"].append(e["i"])
        else:
            by_ice_range["low_under_40"].append(e["i"])
        by_status[e["s"] if e["s"] in by_status else "identified"].append(e["i"])

    ices = [e["ice"] for e in entries]
    top = max(entries, key=lambda e: e["ice"]) if entries else {}
    bottom = min(entries, key=lambda e: e["ice"]) if entries else {}

    runs_dir = base / "runs"
    run_count = (
        sum(1 for path in runs_dir.iterdir() if path.is_dir()) if runs_dir.is_dir() else 0
    )

    return {
        "v": 2,
        "ts": f"{datetime.now():%Y-%m-%dT%H:%M:%S}",
        "stats": {
            "runs": run_count,
            "domains": len(domains),
            "opps": len(entries),
            "avg_ice": round(sum(ices) / len(ices), 1) if ices else 0,
            "top_ice": top.get("ice", 0),
            "top_id": top.get("i", ""),
            "top_title": top.get("t", ""),
            "bot_ice": bottom.get("ice", 0),
            "layers": {k: len(v) for k, v in by_layer.items()},
            "statuses": {k: len(v) for k, v in by_status.items()},
        },
        "domains": sorted(domains.values(), key=lambda d: d["id"]),
        "by_layer": by_layer,
        "by_ice_range": by_ice_range,
        "by_status": by_status,
        "entries": sorted(entries, key=lambda e: e["ice"], reverse=True),
        "warnings": warnings,
    }


def reindex(base: Path) -> dict[str, Any]:
    """Build the registry and write registry.json."""
    from automation_miner.artifacts.workspace import write_json

    registry = build_registry(base)
    write_json(base / "registry.json", registry)
    return registry


def _status(value: Any) -> str:
    status = str(value or OppStatus.IDENTIFIED.value).casefold()
    status = STATUS_ALIASES.get(status, status)
    return status if status in STATUSES else OppStatus.IDENTIFIED.value
