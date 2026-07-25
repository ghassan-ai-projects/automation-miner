"""Opportunity brief serialization tests."""

from __future__ import annotations

from factories import make_opportunity

from automation_miner.artifacts.briefs import render_brief
from automation_miner.artifacts.registry import parse_frontmatter
from automation_miner.schemas import Eligibility, Level, OpportunityDraft


def test_frontmatter_round_trips_special_characters(sample_draft: OpportunityDraft) -> None:
    title = 'Windows path C:\\temp | "quoted"\nsecond line'
    impact_rows = list(sample_draft.impact_analysis)
    impact_rows[0] = impact_rows[0].model_copy(update={"dimension": "Time | Cost"})
    draft = sample_draft.model_copy(update={"title": title, "impact_analysis": impact_rows})
    opportunity = make_opportunity("AM-001", 4, 4, 4, draft=draft).model_copy(
        update={"domain": 'Domain "A"', "domain_slug": "domain-a"}
    )
    text = render_brief(opportunity, "2026-07-22_domain-a")
    metadata = parse_frontmatter(text)
    assert metadata["title"] == title
    assert metadata["domain"] == 'Domain "A"'
    assert "Time \\| Cost" in text


def test_brief_shows_per_factor_scoring_rationale() -> None:
    """The quality signal was computed and persisted, then never rendered."""
    opportunity = make_opportunity("AM-002", 4, 3, 5, critique=8.4)
    text = render_brief(opportunity, "2026-07-22_domain-a")

    assert "## Scoring & Confidence" in text
    assert "**ICE 60**" in text
    assert "High (ICE 60-79)" in text
    assert "**Impact 4** — department-level transformation" in text
    assert "**Confidence 3** — adjacent domain proven" in text
    assert "**Ease 5** — config plus API wiring" in text
    assert "Critic score **8.4/10** after 1 iteration." in text
    assert 'tier: "high"' in text
    assert "critique: 8.4" in text


def test_brief_renders_calibration_and_overrides() -> None:
    opportunity = make_opportunity("AM-003").model_copy(
        update={
            "calibration": ["ease 5 -> 4: incompatible with medium effort"],
            "overrides_applied": ["compliance: risk cap active"],
        }
    )
    text = render_brief(opportunity, "run")
    assert "Automated calibration" in text
    assert "incompatible with medium effort" in text
    assert "Constraint overrides applied" in text


def test_brief_shows_evidence_and_flags_unresolved_citations() -> None:
    opportunity = make_opportunity("AM-004", evidence_refs=["S1", "S7"]).model_copy(
        update={"unresolved_refs": ["S7"]}
    )
    text = render_brief(opportunity, "run")
    assert "## Evidence" in text
    assert "`S1`" in text
    assert "Unverified citations" in text and "`S7`" in text


def test_brief_without_evidence_says_so() -> None:
    opportunity = make_opportunity("AM-005", evidence_refs=[])
    text = render_brief(opportunity, "run")
    assert "No evidence ids were cited" in text


def test_brief_marks_a_filtered_opportunity() -> None:
    opportunity = make_opportunity("AM-006").model_copy(
        update={
            "eligibility": Eligibility.FILTERED,
            "exclusion_reasons": ["budget low/zero requires Ease >= 4 (has 3)"],
        }
    )
    text = render_brief(opportunity, "run")
    assert "Excluded from the published portfolio" in text
    assert 'eligibility: "filtered"' in text


def test_brief_reports_agent_topology() -> None:
    opportunity = make_opportunity(
        "AM-007", agent_count=3, agent_topology="supervisor with two workers"
    )
    text = render_brief(opportunity, "run")
    assert "**Agent topology:** 3 agents — supervisor with two workers" in text
    assert "agent-count: 3" in text


def test_brief_frontmatter_carries_effort_and_risk() -> None:
    opportunity = make_opportunity("AM-008", risk=Level.HIGH, effort="low")
    metadata = parse_frontmatter(render_brief(opportunity, "run"))
    assert metadata["risk"] == "high"
    assert metadata["effort"] == "low"
