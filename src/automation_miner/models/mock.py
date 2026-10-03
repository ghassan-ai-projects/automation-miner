"""Deterministic mock provider — the whole graph runs offline against it.

Every role returns canned, schema-valid JSON. Two things are read out of the
prompt so artifacts look realistic rather than uniform: the active layer, and
the evidence ids on offer (so drafts cite refs that actually resolve).

The digest mock honours the requested target size. That matters: the real
failure it stands in for was a digester that ignored its budget and returned 4%
of it, so a mock that always returned a fixed 200 characters would hide exactly
the regression these tests exist to catch.
"""

from __future__ import annotations

import html
import re
from typing import Any, Callable

from automation_miner.models import mock_payloads as payloads

_LAYER_RE = re.compile(r"^Layer:\s*(\w+)", re.MULTILINE)
_JSON_LAYER_RE = re.compile(r'"layer"\s*:\s*"(\w+)"')
_TARGET_RE = re.compile(r"approximately ([\d,]+) characters")
_CONTENT_RE = re.compile(r"\nContent:\n(.*)\n\nWrite a dense digest", re.DOTALL)
_REF_RE = re.compile(r"\[(S\d+)\]")
_CONSTRAINTS_RE = re.compile(r"<untrusted-constraints>\n(.*)\n</untrusted-constraints>", re.DOTALL)

_LAYERS = payloads.LAYERS


def _layer_from_prompt(prompt: str) -> str:
    match = _LAYER_RE.search(prompt)
    if not match:
        match = _JSON_LAYER_RE.search(prompt)
    if match and match.group(1).lower() in _LAYERS:
        return match.group(1).lower()
    return "document"


def _refs_from_prompt(prompt: str, limit: int = 3) -> list[str]:
    """Cite evidence ids that genuinely appear in the prompt."""
    seen: list[str] = []
    for ref in _REF_RE.findall(prompt):
        if ref not in seen:
            seen.append(ref)
        if len(seen) >= limit:
            break
    return seen


def digest(prompt: str) -> str:
    """Mapper-role digest (plain text). Fills the requested target size."""
    target_match = _TARGET_RE.search(prompt)
    target = int(target_match.group(1).replace(",", "")) if target_match else 800
    content_match = _CONTENT_RE.search(prompt)
    body = content_match.group(1) if content_match else prompt
    source_match = re.search(r"<untrusted-source>\s*(.*?)\s*</untrusted-source>", body, re.DOTALL)
    if source_match:
        body = source_match.group(1)
    condensed = " ".join(body.split())
    if len(condensed) <= target:
        return condensed
    head = condensed[:target]
    cut = head.rfind(". ")
    return head[: cut + 1] if cut > target // 2 else head


Builder = Callable[[str, list[str], str], dict[str, Any]]

# Each builder receives (layer, evidence refs, prompt) read out of the prompt.
_BUILDERS: dict[str, Builder] = {
    "InputAssessment": lambda layer, refs, prompt: payloads.input_assessment(refs),
    "DomainMap": lambda layer, refs, prompt: payloads.domain_map(refs),
    "CandidatePortfolio": lambda layer, refs, prompt: payloads.candidate_portfolio(refs, prompt),
    "LayerAnalysis": lambda layer, refs, prompt: payloads.layer_analysis(layer, refs),
    "OpportunityDraft": lambda layer, refs, prompt: payloads.draft(layer, refs, prompt),
    "Critique": lambda layer, refs, prompt: payloads.critique(),
    "ICEScore": lambda layer, refs, prompt: payloads.ice(),
    "PortfolioScores": lambda layer, refs, prompt: payloads.portfolio_scores(prompt),
    "RepairVerdict": lambda layer, refs, prompt: payloads.repair_verdict(),
    "ClaimAudit": lambda layer, refs, prompt: payloads.claim_audit(),
    "BriefJudgement": lambda layer, refs, prompt: payloads.brief_judgement(),
    "PortfolioJudgement": lambda layer, refs, prompt: payloads.portfolio_judgement(),
    "PolicyReading": lambda layer, refs, prompt: _policy_reading(prompt),
}


def _policy_reading(prompt: str) -> dict[str, Any]:
    """Read constraints with the keyword patterns, quoting the phrase each one matched."""
    from automation_miner.scoring.prose import prose_agent_limit, prose_matches

    match = _CONSTRAINTS_RE.search(prompt)
    text = html.unescape(match.group(1)) if match else ""
    clauses: list[dict[str, Any]] = [
        {"flag": flag, "quote": phrase} for flag, phrase in prose_matches(text).items()
    ]
    limit = prose_agent_limit(text)
    if limit is not None:
        clauses.append({"flag": "agent_limit", "quote": text.strip(), "limit": limit})
    return {"clauses": clauses}


def call_json(role: str, schema_name: str, prompt: str) -> dict[str, Any]:
    """Return canned valid JSON for a role + schema pair."""
    builder = _BUILDERS.get(schema_name)
    if builder is None:
        raise ValueError(f"Mock provider has no canned response for schema {schema_name!r}")
    return builder(_layer_from_prompt(prompt), _refs_from_prompt(prompt), prompt)
