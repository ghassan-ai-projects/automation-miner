"""Prompt composition tests for cross-stage evidence and constraints."""

from automation_miner.prompts import (
    CRITIC_SYSTEM,
    DOMAIN_MAP_SYSTEM,
    LAYER_ANALYST_SYSTEM,
    domain_map_prompt,
    draft_prompt,
    layer_analysis_prompt,
)


def test_domain_map_prompt_includes_complete_strict_output_contract() -> None:
    prompt = domain_map_prompt("claims", "budget:low", "[S1] SOP\nClaims arrive by fax.")

    for field in (
        "core_function: string",
        "stakeholders: array of strings (names only)",
        'stakeholder_processes: array of objects, each exactly {"stakeholder": string, "processes": array of strings}',
        "information_flow: string (a prose paragraph, not an array)",
        "decision_density: string",
        "compliance_surface: string",
        "technology_maturity: string",
        "scale_indicators: string (a prose paragraph, not an array)",
        "manual_friction: array of strings",
        "workflow_patterns: string (a prose paragraph, not an array)",
    ):
        assert field in prompt
    assert "Do not include pain_points, evidence_refs, or any other fields." in prompt
    assert "The DomainMap schema has no evidence_refs field." in DOMAIN_MAP_SYSTEM


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
