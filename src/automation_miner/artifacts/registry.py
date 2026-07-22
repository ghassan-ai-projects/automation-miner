"""registry.json builder — proper port of docs/spec/05-miner-index.py.

Scans ``opps/<domain-slug>/AM-*.md``, parses YAML frontmatter (pyyaml instead
of the original regex parser), and builds the compact cross-indexed registry.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

LAYERS = ("document", "communication", "decision", "monitoring", "knowledge")
ICE_RANGES = ("vision_80plus", "high_60_79", "medium_40_59", "low_under_40")
STATUSES = ("identified", "validating", "designing", "building", "live", "deprecated")


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

    if opps_dir.exists():
        for domain_dir in sorted(p for p in opps_dir.iterdir() if p.is_dir()):
            slug = domain_dir.name
            domain_entries: list[dict[str, Any]] = []
            for f in sorted(domain_dir.glob("AM-*.md")):
                meta = parse_frontmatter(f.read_text(encoding="utf-8"))
                entry: dict[str, Any] = {
                    "i": str(meta.get("am-id", "")),
                    "t": str(meta.get("title", f.stem)),
                    "l": str(meta.get("layer", "unknown")),
                    "ice": _int(meta.get("ice-score")) or 0,
                    "d": slug,
                    "s": str(meta.get("status", "identified")),
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

    return {
        "v": 2,
        "ts": f"{datetime.now():%Y-%m-%dT%H:%M:%S}",
        "stats": {
            "runs": len(domains),
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
    }


def reindex(base: Path) -> dict[str, Any]:
    """Build the registry and write registry.json."""
    from automation_miner.artifacts.workspace import write_json

    registry = build_registry(base)
    write_json(base / "registry.json", registry)
    return registry
