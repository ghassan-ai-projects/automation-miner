"""Prompt composition tests for cross-stage evidence and constraints."""

from automation_miner.prompts import draft_prompt


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
