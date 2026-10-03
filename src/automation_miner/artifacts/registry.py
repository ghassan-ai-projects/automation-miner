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
STATUS_ALIASES = {
    "validating": OppStatus.EVALUATING.value,
    "building": OppStatus.IMPLEMENTING.value,
}
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


def _brief_id(path: Path, meta: dict[str, Any]) -> str | None:
    """The brief's AM-id when frontmatter and filename agree, else None."""
    match = _BRIEF_ID_RE.match(path.name)
    am_id = str(meta.get("am-id", "")).upper()
    if not _AM_ID_RE.fullmatch(am_id) or am_id != (match.group(1) if match else ""):
        return None
    return am_id


def _publication_problem(base: Path, source: object, am_id: str) -> str:
    """Why the brief's source run does not vouch for it ("" when it does)."""
    if not isinstance(source, str) or not _RUN_ID_RE.fullmatch(source):
        return "missing or invalid source run"
    try:
        manifest = json.loads((base / "runs" / source / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = None
    manifest = manifest if isinstance(manifest, dict) else {}
    status = manifest.get("status")
    publication = manifest.get("publication_status")
    listed = manifest.get("opportunities", [])
    if (
        status == "completed"
        and publication == "complete"
        and isinstance(listed, list)
        and (am_id in listed)
    ):
        return ""
    detail = f" / publication {publication or 'unreadable'}" if status == "completed" else ""
    return f"source run {source} is {status or 'unreadable'}{detail}"


def _entry(path: Path, meta: dict[str, Any], am_id: str, slug: str) -> dict[str, Any]:
    ice = _int(meta.get("ice-score")) or 0
    entry: dict[str, Any] = {
        "i": am_id,
        "t": str(meta.get("title", path.stem)),
        "l": str(meta.get("layer", "unknown")),
        "ice": ice,
        # Derived rather than trusted: a brief edited by hand can carry a tier
        # that no longer matches its score.
        "tr": Tier.for_ice(ice).value,
        "d": slug,
        "s": _status(meta.get("status")),
        "f": str(path),
    }
    for key, short in (("impact", "im"), ("confidence", "co"), ("ease", "ea")):
        value = _int(meta.get(key))
        if value is not None:
            entry[short] = value
    return entry


def _scan(base: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Every published brief whose source run vouches for it, plus warnings."""
    entries: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    seen: set[str] = set()
    opps_dir = base / "opps"
    domain_dirs = sorted(p for p in opps_dir.iterdir() if p.is_dir()) if opps_dir.exists() else []
    for domain_dir in domain_dirs:
        for path in sorted(domain_dir.glob("AM-*.md")):
            meta = parse_frontmatter(path.read_text(encoding="utf-8"))
            am_id = _brief_id(path, meta)
            problem = (
                "frontmatter am-id is missing or mismatched"
                if am_id is None
                else _publication_problem(base, meta.get("source"), am_id)
                or (f"duplicate opportunity id {am_id}" if am_id in seen else "")
            )
            if problem or am_id is None:
                warnings.append({"file": str(path), "reason": problem})
                continue
            seen.add(am_id)
            entries.append(_entry(path, meta, am_id, domain_dir.name))
    return entries, warnings


def _domains(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_slug: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        by_slug.setdefault(entry["d"], []).append(entry)
    domains = []
    for slug, members in sorted(by_slug.items()):
        top = max(members, key=lambda e: e["ice"])
        domains.append(
            {
                "id": slug,
                "title": slug.replace("-", " ").title(),
                "slug": slug,
                "total": len(members),
                "top_ice": top["ice"],
                "top_opp": top["i"],
            }
        )
    return domains


def _ice_range(ice: int) -> str:
    if ice >= 80:
        return "vision_80plus"
    if ice >= 60:
        return "high_60_79"
    return "medium_40_59" if ice >= 40 else "low_under_40"


def _indices(entries: list[dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
    by_layer: dict[str, list[str]] = {layer: [] for layer in LAYERS}
    by_ice_range: dict[str, list[str]] = {r: [] for r in ICE_RANGES}
    by_status: dict[str, list[str]] = {s: [] for s in STATUSES}
    for entry in entries:
        if entry["l"] in by_layer:
            by_layer[entry["l"]].append(entry["i"])
        by_ice_range[_ice_range(entry["ice"])].append(entry["i"])
        by_status[entry["s"] if entry["s"] in by_status else "identified"].append(entry["i"])
    return {"by_layer": by_layer, "by_ice_range": by_ice_range, "by_status": by_status}


def _stats(
    base: Path, entries: list[dict[str, Any]], domains: int, idx: dict[str, Any]
) -> dict[str, Any]:
    ices = [e["ice"] for e in entries]
    top = max(entries, key=lambda e: e["ice"]) if entries else {}
    bottom = min(entries, key=lambda e: e["ice"]) if entries else {}
    runs_dir = base / "runs"
    return {
        "runs": sum(1 for p in runs_dir.iterdir() if p.is_dir()) if runs_dir.is_dir() else 0,
        "domains": domains,
        "opps": len(entries),
        "avg_ice": round(sum(ices) / len(ices), 1) if ices else 0,
        "top_ice": top.get("ice", 0),
        "top_id": top.get("i", ""),
        "top_title": top.get("t", ""),
        "bot_ice": bottom.get("ice", 0),
        "layers": {k: len(v) for k, v in idx["by_layer"].items()},
        "statuses": {k: len(v) for k, v in idx["by_status"].items()},
    }


def build_registry(base: Path) -> dict[str, Any]:
    """Build the registry dict from a workspace root."""
    entries, warnings = _scan(base)
    domains = _domains(entries)
    indices = _indices(entries)
    return {
        "v": 2,
        "ts": f"{datetime.now():%Y-%m-%dT%H:%M:%S}",
        "stats": _stats(base, entries, len(domains), indices),
        "domains": domains,
        **indices,
        "entries": sorted(entries, key=lambda e: e["ice"], reverse=True),
        "warnings": warnings,
    }


def reindex(base: Path) -> dict[str, Any]:
    """Build the registry and write registry.json."""
    from automation_miner.artifacts.workspace import workspace_transaction_lock

    from automation_miner.artifacts.publication import recover_publications

    with workspace_transaction_lock(base):
        recover_publications(base)
        return reindex_locked(base)


def reindex_locked(base: Path) -> dict[str, Any]:
    """Build and persist the registry while the caller owns the workspace lock."""
    from automation_miner.artifacts.workspace import write_json

    registry = build_registry(base)
    write_json(base / "registry.json", registry)
    return registry


def _status(value: Any) -> str:
    status = str(value or OppStatus.IDENTIFIED.value).casefold()
    status = STATUS_ALIASES.get(status, status)
    return status if status in STATUSES else OppStatus.IDENTIFIED.value
