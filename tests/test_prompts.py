"""Prompt composition tests for cross-stage evidence and constraints."""

from automation_miner.prompts import (
    CRITIC_SYSTEM,
    DOMAIN_MAP_SYSTEM,
    INPUT_ASSESSMENT_SYSTEM,
    LAYER_ANALYST_SYSTEM,
    PORTFOLIO_PLANNER_SYSTEM,
    candidate_draft_prompt,
    domain_map_prompt,
    draft_prompt,
    layer_analysis_prompt,
    portfolio_plan_prompt,
)


def test_domain_map_prompt_includes_complete_strict_output_contract() -> None:
    prompt = domain_map_prompt("claims", "budget:low", "[S1] SOP\nClaims arrive by fax.")

    for field in (
        "core_function: string",
        "stakeholders: array of strings (names only)",
        'stakeholder_processes: array of objects, each exactly {"stakeholder": string, "processes": array of strings, "evidence_refs": array of strings}',
        "information_flow: string (a prose paragraph, not an array)",
        "decision_density: string",
        "compliance_surface: string",
        "technology_maturity: string",
        "scale_indicators: string (a prose paragraph, not an array)",
        "manual_friction: array of strings",
        "workflow_patterns: string (a prose paragraph, not an array)",
    ):
        assert field in prompt
    for field in (
        "analysis_mode",
        "verified_current_state",
        "stated_gaps",
        "proposed_initiatives",
        "benchmarks",
        "unknowns",
    ):
        assert field in prompt
    assert "Do not include pain_points or any other fields." in prompt
    assert "Classify claims by epistemic status" in DOMAIN_MAP_SYSTEM


def test_generation_and_critic_prompts_treat_source_silence_as_unknown() -> None:
    rule = "Absence of evidence is not evidence of absence."
    assert rule in DOMAIN_MAP_SYSTEM
    assert rule in LAYER_ANALYST_SYSTEM
    assert rule in CRITIC_SYSTEM
    assert "Do not claim it is missing" in LAYER_ANALYST_SYSTEM

    layer_prompt = layer_analysis_prompt("knowledge", "claims", "", "[S1] Evidence")
    assert "Omit a candidate" in layer_prompt
    assert "finding or pain point" in layer_prompt
    assert "even if you label that claim \"inferred\"" in layer_prompt


def test_drafter_receives_domain_map_evidence_and_constraints() -> None:
    prompt = draft_prompt(
        "document",
        '{"findings":["manual entry"]}',
        "100 invoices/day",
        constraints="budget:low",
        domain_map_json='{"stakeholders":["Finance"]}',
    )
    assert "budget:low" in prompt
    assert "Finance" in prompt
    assert "100 invoices/day" in prompt


def test_strategy_prompts_do_not_turn_recommendations_into_current_state() -> None:
    assert "roadmaps" in INPUT_ASSESSMENT_SYSTEM
    layer = layer_analysis_prompt("decision", "portfolio", "", "[S1] roadmap", "strategy")
    draft = draft_prompt(
        "decision",
        '{"findings":["pilot proposed"]}',
        "[S1] roadmap",
        mode="strategy",
    )
    assert "explicit gaps" in layer
    assert "Frame drafts as hypotheses" in draft
    assert "Do not invent an as-is workflow" in draft


def test_critic_requires_structured_grounding_violations() -> None:
    assert "grounding_violations" in CRITIC_SYSTEM
    assert "prevents publication regardless" in CRITIC_SYSTEM


def test_portfolio_planner_optimizes_value_and_diversity_before_drafting() -> None:
    prompt = portfolio_plan_prompt(
        '{"core_function":"EAM"}',
        '[{"layer":"knowledge"},{"layer":"decision"}]',
        "[S1] portfolio evidence",
        "Constraint parameters:\n- agent = openclaw",
        '[{"title":"Existing Documentation Copilot"}]',
    )
    assert "rigid layer quotas" in PORTFOLIO_PLANNER_SYSTEM
    assert "several variants of documentation" in PORTFOLIO_PLANNER_SYSTEM
    assert "every other candidate" in PORTFOLIO_PLANNER_SYSTEM
    assert "agent=openclaw" in PORTFOLIO_PLANNER_SYSTEM
    assert "Existing Documentation Copilot" in prompt
    assert "- agent = openclaw" in prompt

    draft = candidate_draft_prompt(
        '{"title":"Predictive Failure Triage"}',
        '{"candidates":[{"title":"Predictive Failure Triage"},{"title":"Renewal Risk"}]}',
        "[S1] evidence",
        "Constraint parameters:\n- agent = openclaw",
        mode="strategy",
    )
    assert "Complete planned portfolio" in draft
    assert "Every dynamic constraint parameter is binding" in draft
    assert "generic documentation or search idea" in draft
