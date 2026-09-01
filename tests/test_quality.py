"""Deterministic evidence-richness and user-facing preflight signals."""

from __future__ import annotations

from automation_miner.quality import profile_input_quality
from automation_miner.schemas import Chunk


def test_short_idea_is_flagged_as_thin_process_evidence() -> None:
    profile = profile_input_quality(
        "idea", [Chunk(id="S1", source="<idea>", text="A healthcare domain", tokens=3)], 19
    )

    assert profile.level == "thin"
    assert profile.score <= 30
    assert "implementation-ready" in profile.warning
    assert "owners" in profile.missing


def test_operational_kb_signals_are_visible_and_can_be_rich() -> None:
    text = (
        "The claims team owns SAP intake and hands off 400 cases/day. "
        "The process takes 4 hours, has duplicate errors, and requires approval "
        "under the audit control."
    )
    profile = profile_input_quality(
        "kb", [Chunk(id="S1", source="sop.md", text=text, tokens=30)], len(text)
    )

    assert profile.level == "rich"
    assert profile.score >= 60
    assert set(profile.signals) == {
        "owners",
        "systems",
        "handoffs",
        "volumes",
        "durations",
        "errors",
        "controls",
    }


def test_rich_large_input_score_is_bounded() -> None:
    text = (
        "The operations team owns SAP and Excel, hands off 400 cases/day, "
        "takes 4 hours, sees duplicate errors, and requires approval under audit. "
    ) * 60
    profile = profile_input_quality(
        "kb", [Chunk(id="S1", source="sop.md", text=text, tokens=30)], len(text)
    )

    assert profile.score == 100
    assert profile.level == "rich"
