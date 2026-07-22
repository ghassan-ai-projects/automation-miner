"""Registry builder tests (port of spec 05 logic)."""

from __future__ import annotations

from pathlib import Path

from automation_miner.artifacts.registry import build_registry, parse_frontmatter, reindex

BRIEF = """---
am-id: "{am_id}"
title: "{title}"
domain: "Test Domain"
layer: "{layer}"
status: "{status}"
ice-score: {ice}
impact: 4
confidence: 4
ease: 4
created: "2026-07-22"
updated: "2026-07-22"
source: "2026-07-22_test-domain"
tags: [automation, {layer}, test-domain]
---

# {am_id}: {title}
"""


def _write_brief(root: Path, domain: str, am_id: str, title: str, layer: str, ice: int,
                 status: str = "identified") -> None:
    d = root / "opps" / domain
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{am_id}-{title.lower().replace(' ', '-')}.md").write_text(
        BRIEF.format(am_id=am_id, title=title, layer=layer, ice=ice, status=status),
        encoding="utf-8",
    )


def test_parse_frontmatter() -> None:
    meta = parse_frontmatter(BRIEF.format(am_id="AM-001", title="T", layer="document", ice=64, status="identified"))
    assert meta["am-id"] == "AM-001"
    assert meta["ice-score"] == 64
    assert meta["tags"] == ["automation", "document", "test-domain"]
    assert parse_frontmatter("no frontmatter") == {}


def test_build_registry_compact_keys_and_indices(tmp_path: Path) -> None:
    _write_brief(tmp_path, "alpha-domain", "AM-001", "First", "document", 85)
    _write_brief(tmp_path, "alpha-domain", "AM-002", "Second", "decision", 64)
    _write_brief(tmp_path, "beta-domain", "AM-003", "Third", "monitoring", 30, status="live")

    registry = build_registry(tmp_path)

    assert registry["v"] == 2
    entries = {e["i"]: e for e in registry["entries"]}
    assert entries["AM-001"]["t"] == "First"
    assert entries["AM-001"]["l"] == "document"
    assert entries["AM-001"]["d"] == "alpha-domain"
    assert entries["AM-001"]["im"] == 4 and entries["AM-001"]["co"] == 4
    # sorted by ICE desc
    assert [e["i"] for e in registry["entries"]] == ["AM-001", "AM-002", "AM-003"]

    assert registry["by_layer"]["document"] == ["AM-001"]
    assert registry["by_ice_range"]["vision_80plus"] == ["AM-001"]
    assert registry["by_ice_range"]["high_60_79"] == ["AM-002"]
    assert registry["by_ice_range"]["low_under_40"] == ["AM-003"]
    assert registry["by_status"]["live"] == ["AM-003"]

    stats = registry["stats"]
    assert stats["runs"] == 2
    assert stats["opps"] == 3
    assert stats["top_ice"] == 85
    assert stats["top_id"] == "AM-001"
    assert stats["bot_ice"] == 30

    domains = {d["id"]: d for d in registry["domains"]}
    assert domains["alpha-domain"]["total"] == 2
    assert domains["alpha-domain"]["top_opp"] == "AM-001"


def test_reindex_writes_file(tmp_path: Path) -> None:
    _write_brief(tmp_path, "alpha-domain", "AM-010", "Tenth", "knowledge", 50)
    registry = reindex(tmp_path)
    assert (tmp_path / "registry.json").is_file()
    assert registry["by_ice_range"]["medium_40_59"] == ["AM-010"]


def test_empty_workspace(tmp_path: Path) -> None:
    registry = build_registry(tmp_path)
    assert registry["stats"]["opps"] == 0
    assert registry["entries"] == []
