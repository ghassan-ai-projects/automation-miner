"""Canned, schema-valid judge payloads for the deterministic mock provider."""

from __future__ import annotations

from typing import Any


def claim_audit() -> dict[str, Any]:
    return {
        "claims": [
            {"claim": "Mock claim", "verdict": "supported", "note": "Mock audit."},
        ]
    }


def brief_judgement() -> dict[str, Any]:
    return {
        "specificity": 4,
        "insight": 4,
        "actionability": 4,
        "domain_expertise": 4,
        "epistemic_honesty": 4,
        "readability": 4,
        "overall": 4,
        "fabricated_facts": [],
        "strengths": ["Names the workflow and its human checkpoints."],
        "weaknesses": ["Mock judgement: no real review was performed."],
    }


def portfolio_judgement() -> dict[str, Any]:
    return {
        "diversity": 4,
        "coverage": 4,
        "ranking_sanity": 4,
        "missed_opportunities": [],
        "near_duplicates": [],
        "summary": "Mock portfolio judgement.",
    }
