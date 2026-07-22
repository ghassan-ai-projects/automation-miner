"""Opportunity brief serialization tests."""

from __future__ import annotations

from automation_miner.artifacts.briefs import render_brief
from automation_miner.artifacts.registry import parse_frontmatter
from automation_miner.schemas import ICEScore, Opportunity, OpportunityDraft


def test_frontmatter_round_trips_special_characters(sample_draft: OpportunityDraft) -> None:
    title = 'Windows path C:\\temp | "quoted"\nsecond line'
    impact_rows = list(sample_draft.impact_analysis)
    impact_rows[0] = impact_rows[0].model_copy(update={"dimension": "Time | Cost"})
    draft = sample_draft.model_copy(
        update={"title": title, "impact_analysis": impact_rows}
    )
    score = ICEScore(impact=4, confidence=4, ease=4, rationale="r")
    opportunity = Opportunity(
        am_id="AM-001",
        domain='Domain "A"',
        domain_slug="domain-a",
        draft=draft,
        score=score,
        ice=64,
        critique_overall=8,
        iterations=1,
    )
    text = render_brief(opportunity, "2026-07-22_domain-a")
    metadata = parse_frontmatter(text)
    assert metadata["title"] == title
    assert metadata["domain"] == 'Domain "A"'
    assert "Time \\| Cost" in text
