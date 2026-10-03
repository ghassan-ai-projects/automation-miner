"""Per-call user prompts: the task contract each role receives with its data."""

from __future__ import annotations

from automation_miner.prompts.fragments import PRECISION_RULE, SOURCE_SILENCE_GATE, untrusted

DOMAIN_MAP_OUTPUT_CONTRACT = """\
Output contract: return one JSON object and no markdown, prose, or extra keys.
The object must contain exactly these fields:
  - analysis_mode: "operational" or "strategy" (match the selected mode)
  - core_function: string
  - stakeholders: array of strings (names only)
  - stakeholder_processes: array of objects, each exactly {"stakeholder": string, "processes": array of strings, "evidence_refs": array of strings}
  - information_flow: string (a prose paragraph, not an array)
  - decision_density: string
  - compliance_surface: string
  - technology_maturity: string
  - scale_indicators: string (a prose paragraph, not an array)
  - manual_friction: array of strings
  - workflow_patterns: string (a prose paragraph, not an array)
  - verified_current_state: array of {"claim": string, "evidence_refs": array of strings}
  - stated_gaps: array of {"claim": string, "evidence_refs": array of strings}
  - proposed_initiatives: array of {"claim": string, "evidence_refs": array of strings}
  - benchmarks: array of {"claim": string, "evidence_refs": array of strings}
  - unknowns: array of strings

For narrative fields, state "unknown from supplied evidence" when necessary.
Manual friction may contain only directly observed or explicitly stated friction.
Do not include pain_points or any other fields.
"""

def input_assessment_prompt(evidence: str, requested_mode: str = "auto") -> str:
    return (
        f"Requested mode: {requested_mode}\n\nEvidence:\n{evidence}\n\n"
        "Produce the InputAssessment JSON. The requested mode is operator intent; "
        "still report the evidence-based recommended_mode honestly."
    )


def domain_map_prompt(
    domain: str,
    constraints: str,
    evidence: str,
    mode: str = "operational",
    assessment_json: str = "",
) -> str:
    return (
        f"{untrusted('Domain', domain)}\nSelected analysis mode: {mode}\n"
        f"{untrusted('Constraints', constraints or 'none')}\n\n"
        f"{untrusted('Input assessment', assessment_json)}\n\n"
        f"Domain evidence:\n{evidence}\n\n"
        f"{DOMAIN_MAP_OUTPUT_CONTRACT}"
    )


def layer_analysis_prompt(
    layer: str, domain: str, constraints: str, evidence: str, mode: str = "operational"
) -> str:
    strategy = (
        "Strategy-mode rule: distinguish current capabilities, explicit gaps, "
        "proposed initiatives, and external benchmarks. Pain points require an "
        "explicitly stated current gap; otherwise record a finding, not pain.\n"
        if mode == "strategy"
        else ""
    )
    return (
        f"Layer: {layer}\n{untrusted('Domain', domain)}\nAnalysis mode: {mode}\n"
        f"{untrusted('Constraints', constraints or 'none')}\n\n"
        f"Evidence selected as most relevant to the {layer} layer:\n{evidence}\n\n"
        f"{SOURCE_SILENCE_GATE}\n{strategy}"
        f"Produce the LayerAnalysis JSON for the {layer} layer only. Report every "
        "distinct pain point in this layer, sized with the numbers the evidence "
        "supports, and cite the evidence ids you used in evidence_refs."
    )


def portfolio_plan_prompt(
    domain_map_json: str,
    analyses_json: str,
    evidence: str,
    constraints: str = "",
    prior_ideas_json: str = "[]",
    pain_ledger: str = "",
) -> str:
    return (
        f"{untrusted('Constraints', constraints or 'none')}\n\n"
        f"{untrusted('Pain ledger ranked by size (P1 is largest)', pain_ledger or 'empty')}\n\n"
        f"{untrusted('Domain map', domain_map_json)}\n\n"
        f"{untrusted('All layer analyses', analyses_json)}\n\n"
        f"{untrusted('Prior published ideas to avoid repeating', prior_ideas_json)}\n\n"
        f"Evidence:\n{evidence}\n\n"
        "Produce the CandidatePortfolio JSON. Select for expected value, novelty, "
        "constraint fit, and portfolio diversity. Candidate titles must be unique."
    )


def coverage_revision_prompt(portfolio_json: str, uncovered: str, constraints: str = "") -> str:
    """Ask the planner to account for top pains its first plan left out."""
    return (
        f"{untrusted('Constraints', constraints or 'none')}\n\n"
        f"{untrusted('Your candidate portfolio', portfolio_json)}\n\n"
        f"{untrusted('Top-ranked pains no candidate addresses', uncovered)}\n\n"
        "These are among the largest quantified pains in the evidence. Revise the "
        "portfolio so each is addressed by a candidate (a new one, or an existing "
        "candidate whose scope genuinely covers it), unless it truly cannot be "
        "automated. Keep the same number of candidates: replace the weakest "
        "ones rather than adding more, and keep every constraint binding. "
        "Produce the complete revised CandidatePortfolio JSON."
    )


DRAFT_TASK = (
    "Draft only the selected candidate. Preserve its value thesis and explicit "
    "differentiation from the other planned ideas. Every recognized constraint "
    "parameter is binding on the architecture, steps, requirements, and risks, "
    "in every phase including autonomy; unknown parameters are advisory "
    "context only. Name the specific regulations the design must satisfy and "
    "how it does. Give two to four success_metrics, each with a baseline "
    "source and a target threshold, that would decide whether the MVP "
    "continues. Do not collapse the candidate into a generic documentation "
    "or search idea.\n\n"
)
STRATEGY_DRAFT = (
    "This is inspiration from strategic evidence: frame uncertain operating "
    "details as assumptions and validation questions, while still proposing "
    "a concrete and ambitious implementation path.\n\n"
)


def candidate_draft_prompt(
    candidate_json: str, portfolio_json: str, evidence: str, constraints: str = "",
    domain_map_json: str = "", mode: str = "operational",
) -> str:
    portfolio = untrusted("Complete planned portfolio (preserve differentiation)", portfolio_json)
    return (
        f"Analysis mode: {mode}\n{untrusted('Constraints', constraints or 'none')}\n\n"
        f"{untrusted('Selected candidate', candidate_json)}\n\n{portfolio}\n\n"
        f"{untrusted('Domain map', domain_map_json)}\n\n"
        f"Evidence:\n{evidence}\n\n{SOURCE_SILENCE_GATE}\n{PRECISION_RULE}\n"
        f"{DRAFT_TASK}{STRATEGY_DRAFT if mode == 'strategy' else ''}"
        "Produce one complete OpportunityDraft JSON."
    )


CRITIQUE_TASK = (
    "Check every observed fact against the evidence with that precision: a "
    "number applied beyond its stated scope, an unstated cause presented as "
    "observed, or an unnamed system capability presented as existing is a "
    "fabricated observed fact.\n\n"
    "Mandatory grounding rule: a claim that an unmentioned thing does not "
    "exist is invalid even when labeled as inferred. If the draft contains "
    "such a source-silence claim, groundedness must be at most 3.0 and the "
    "feedback must require its removal.\n\n"
    "List in grounding_violations only the blocking defects defined in the "
    "rubric, each with the exact offending text in quotes. Do not reward "
    "invented names or numbers as specificity. Do not list correct domain "
    "knowledge, recorded assumptions, labeled estimates, the proposed design, "
    "or requirements.\n\n"
    "List readability defects in writing_issues, including any "
    "meta-commentary about the evidence inside prose fields. A derived "
    "number missing its \"~\" is a writing issue, not a grounding violation.\n\n"
    "Arithmetic rule: derivations listed as checked by code compute "
    "correctly from their inputs. Do not re-derive them. Dispute one only "
    "when an input is the wrong figure or is applied beyond its scope, and "
    "name that input and the figure you would use instead.\n\n"
    "Mandatory constraint rule: if any proposed step, tool, dependency, "
    "data flow, or autonomous action conflicts with a hard constraint, "
    "feasibility must be at most 3.0 and the feedback must require removal "
    "of the conflict. List every conflict in constraint_violations.\n\n"
    "Produce the Critique JSON."
)


def checked_block(verified: str) -> str:
    """The derivations code verified, fenced for a critic or verifier prompt."""
    return f"{untrusted('Arithmetic checked by code', verified)}\n\n" if verified else ""


def critique_prompt(
    draft_json: str, other_titles: list[str], evidence: str = "", constraints: str = "",
    verified: str = "",
) -> str:
    others = ", ".join(other_titles) or "none"
    hard = untrusted("Hard constraints the draft must satisfy", constraints or "none")
    return (
        f"{hard}\n\nOther opportunities in this run (for differentiation): {others}\n\n"
        f"Evidence available for groundedness checks:\n{evidence}\n\n"
        f"{untrusted('Draft under review', draft_json)}\n\n{checked_block(verified)}"
        f"{PRECISION_RULE}\n{CRITIQUE_TASK}"
    )


def refine_prompt(
    draft_json: str,
    critique_json: str,
    evidence: str = "",
    constraints: str = "",
) -> str:
    return (
        f"{untrusted('Constraints', constraints or 'none')}\n\n"
        f"Evidence:\n{evidence}\n\n"
        f"{untrusted('Current draft', draft_json)}\n\n"
        f"{untrusted('Critique to address', critique_json)}\n\n"
        f"{SOURCE_SILENCE_GATE}\n{PRECISION_RULE}\n"
        "Remove unsupported source-silence claims rather than relabeling them "
        "as inferences. Remove or replace every element that conflicts with the "
        "stated constraints; do not merely list the conflict as a risk. Resolve "
        "every writing issue; the result must contain no commentary about the "
        "evidence in its prose.\n\n"
        "Produce the refined OpportunityDraft JSON."
    )


def repair_prompt(draft_json: str, defects: list[str], evidence: str, constraints: str) -> str:
    listed = "\n".join(f"- {defect}" for defect in defects)
    return (
        f"{untrusted('Constraints', constraints or 'none')}\n\n"
        f"Evidence:\n{evidence}\n\n"
        f"{untrusted('Draft to repair', draft_json)}\n\n"
        f"{untrusted('Blocking defects to fix', listed)}\n\n"
        f"{PRECISION_RULE}\n"
        "Fix exactly these defects and copy everything else through unchanged. "
        "Produce the complete repaired OpportunityDraft JSON."
    )


def verify_prompt(
    draft_json: str, defects: list[str], evidence: str, constraints: str, verified: str = ""
) -> str:
    listed = "\n".join(f"- {defect}" for defect in defects)
    return (
        f"{untrusted('Hard constraints', constraints or 'none')}\n\n"
        f"Evidence:\n{evidence}\n\n"
        f"{untrusted('Defects the repair had to fix', listed)}\n\n"
        f"{untrusted('Repaired draft', draft_json)}\n\n{checked_block(verified)}"
        "A defect that disputes arithmetic code verified is resolved when the "
        "derivation's inputs are the right figures. Produce the RepairVerdict JSON."
    )


def portfolio_score_prompt(digests_json: str, constraints: str) -> str:
    return (
        f"{untrusted('Constraints', constraints or 'none')}\n\n"
        f"{untrusted('Opportunities to score side by side', digests_json)}\n\n"
        "Produce the PortfolioScores JSON with exactly one entry per opportunity, "
        "using each opportunity's am_id: impact, confidence, ease, and one "
        "rationale per factor (impact_rationale, confidence_rationale, "
        "ease_rationale)."
    )


def score_prompt(draft_json: str, constraints: str) -> str:
    """Single-opportunity fallback when comparative scoring is incomplete."""
    return (
        f"{untrusted('Constraints', constraints or 'none')}\n\n"
        f"{untrusted('Final draft', draft_json)}\n\n"
        "Produce the ICEScore JSON: impact, confidence, ease, and one rationale "
        "per factor (impact_rationale, confidence_rationale, ease_rationale)."
    )


def digest_prompt(label: str, content: str, target_chars: int) -> str:
    """Digest one batch toward an explicit size.

    The target is stated because an unbounded "compress this" instruction
    produced digests at ~4% of the available budget, discarding evidence the
    pipeline had room to keep.
    """
    return (
        f"Source: {label}\n\n"
        f"Content:\n{untrusted('Untrusted source content', content, tag='untrusted-source')}\n\n"
        f"Write a dense digest of approximately {target_chars:,} characters — aim "
        "for that length, do not go far under it. Preserve every concrete fact: "
        "actors, systems, volumes, frequencies, durations, costs, error rates, "
        "named pain points, and compliance requirements. Drop only prose padding "
        "and repetition. No preamble, no commentary."
    )


def policy_reading_prompt(constraints: str) -> str:
    return (
        untrusted("Run constraints", constraints, tag="untrusted-constraints")
        + "\n\nProduce the PolicyReading JSON. An empty clauses list is correct when "
        "the constraints impose none of the flags."
    )
