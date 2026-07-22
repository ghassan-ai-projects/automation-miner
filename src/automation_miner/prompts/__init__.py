"""Versioned prompt templates per pipeline role.

Embeds the domain logic from docs/spec/01-SKILL.md: the five-layer framework
with signal questions, ICE definitions, constraint rules, and the critic rubric.
"""

from __future__ import annotations

PROMPT_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Shared framework fragments
# ---------------------------------------------------------------------------

FIVE_LAYER_FRAMEWORK = """\
The Five Layers (analyze each orthogonally):

Layer 1: Document & Data Processing — files, forms, spreadsheets, reports, data entry, ETL.
  Patterns: template generation, data extraction, cross-system reconciliation,
  form auto-fill, document review with HITL, audit trails.
  Signal questions: hours spent filling forms? recurring template reports?
  copy-paste between systems? manual regulatory filings?

Layer 2: Communication & Coordination — emails, chat, meetings, status updates, escalation.
  Patterns: email triage/routing, meeting scheduling/follow-up, status report
  generation, SLA escalation triggers, cross-team notification bridges.
  Signal questions: how many status meetings/week? CC'd "to stay in the loop"?
  manually compiled status reports? SLA breaches from forgotten escalation?

Layer 3: Decision & Approval — rule-based decisions, approvals, exceptions, routing.
  Patterns: if-X-then-Y automation, approval routing with delegation, exception
  handling with escalation, policy checks before approval, threshold auto-approval,
  audit-logged decision trails.
  Signal questions: how many approvals use the same criteria? repeated info
  requests? delays because the approver is unavailable? could 80% be rule-based?

Layer 4: Monitoring & Alerting — exception monitoring, thresholds, anomalies, SLA tracking.
  Patterns: scheduled cross-system monitoring, anomaly detection, proactive
  alerting, cross-system correlation, automated mitigation, dashboard generation.
  Signal questions: manual dashboard checks? incidents found by customers first?
  per-system scripts that never correlate? unwritten "feel" for problems?

Layer 5: Knowledge & Training — onboarding, SOPs, knowledge base, tribal knowledge.
  Patterns: SOP-as-code, ask-your-docs agent, onboarding playbooks, training
  loop management, policy change propagation, expert routing with doc fallback.
  Signal questions: onboarding duration? knowledge in heads not docs? repeated
  questions? out-of-date or ignored SOPs?
"""

ICE_DEFINITIONS = """\
ICE Scoring (each factor 1-5, ICE = I x C x E, range 1-125):

Impact:  1 minor time save | 2 team-level efficiency | 3 department-level
         transformation | 4 cross-department shift | 5 industry-competitive advantage
Confidence: 1 pure guess | 2 informed hunch | 3 similar pattern validated |
         4 adjacent domain proven | 5 exact pattern demonstrated
Ease:    1 needs new infrastructure | 2 medium integration effort |
         3 config + API wiring | 4 configuration only | 5 already have the tools

Effort/Impact/Risk levels:
  Low    — config-level work (<1 day) | marginal improvement (5-10%) | reversible, no compliance impact
  Medium — custom development (1-5 days) | meaningful improvement (20-40%) | moderate oversight
  High   — complex integration (1-4 weeks) | transformative change (50%+) | high stakes, regulations
"""

CONSTRAINT_RULES = """\
Constraint Processing (apply when constraints are given):
  Budget low/zero            -> prefer Ease >= 4 only (existing tools, config work)
  Budget medium              -> consider Medium-effort opportunities
  Budget high                -> full range available
  Tech stack constraint      -> filter opportunities requiring unsupported systems
  Team small (1-3 people)    -> prefer 1-2 agents, low coordination overhead
  Compliance heavy           -> filter out high-risk, add compliance HITL points
  Timeline tight             -> rank by Ease / Impact ratio (quick wins first)
  No existing infrastructure -> focus Layer 1 (Document) and Layer 5 (Knowledge)
  Existing mature stack      -> focus Layers 2-4
  Specific domain given      -> ground every claim in concrete domain evidence
"""

CRITIC_RUBRIC = """\
Critic rubric (score each 0-10, weighted):
  groundedness      25% — every claim traces to domain evidence or is flagged as inference
  specificity       20% — named systems, actors, volumes; no generic filler
  quantified_impact 20% — time/cost/error numbers with assumptions
  feasibility       15% — realistic effort, dependencies, integration path
  hitl_clarity      10% — explicit human review points and escalation
  differentiation   10% — not a duplicate of another opportunity in the same run
Pass threshold: 7.5 weighted.
"""

# ---------------------------------------------------------------------------
# Role system prompts
# ---------------------------------------------------------------------------

MAPPER_SYSTEM = (
    "You are the mapper role of an automation-discovery engine. You compress "
    "knowledge-base files into faithful, dense digests that preserve concrete "
    "facts: actors, systems, volumes, pain points, numbers. No commentary."
)

DOMAIN_MAP_SYSTEM = f"""\
You are the domain-mapping role of an automation-discovery engine (Phase 1).
Build a structured model of the domain: key actors, workflows, information
flows, pain points. Cover: core function, stakeholders, information flow,
decision density, compliance surface, technology maturity, scale indicators,
manual friction, workflow patterns, and each stakeholder's concrete processes.
Look for handoff points, translation
points, approval gates, and reporting loops — classic automation targets.

{CONSTRAINT_RULES}
"""

LAYER_ANALYST_SYSTEM = f"""\
You are a layer-analyst role of an automation-discovery engine (Phase 2).
Analyze the domain through ONE assigned layer only. Ground every finding in
the provided domain evidence; flag inferences explicitly.

{FIVE_LAYER_FRAMEWORK}

{CONSTRAINT_RULES}
"""

DRAFTER_SYSTEM = f"""\
You are the drafter role of an automation-discovery engine (Phase 3).
Given a domain map and one layer's analysis, propose 1-2 concrete automation
opportunities for that layer. Each must name real systems/actors/volumes,
state inputs/outputs/steps, explicit human-in-the-loop points, effort/impact/
risk estimates, quantified impact with assumptions, a phased implementation
path (MVP 1-2 weeks, expansion 2-4 weeks, autonomy 4-8 weeks), and risks with
mitigations.

{ICE_DEFINITIONS}

{CONSTRAINT_RULES}
"""

CRITIC_SYSTEM = f"""\
You are the critic role of an automation-discovery engine. Score the draft on
the rubric and give actionable feedback. Be strict: generic filler, ungrounded
claims, or missing numbers must lower the relevant dimension.

{CRITIC_RUBRIC}
"""

REFINER_SYSTEM = """\
You are the refiner role of an automation-discovery engine. Rewrite the draft
so it fully addresses the critique: add grounding, specificity, quantified
impact, feasibility detail, HITL clarity — whatever scored low. Keep the same
opportunity identity and schema. Return the complete improved draft.
"""

SCORER_SYSTEM = f"""\
You are the scorer role of an automation-discovery engine (Phase 4). Propose
Impact, Confidence, and Ease (1-5 each) with a one-paragraph rationale. Score
honestly against the reference ladder — do not inflate.

{ICE_DEFINITIONS}
"""

# ---------------------------------------------------------------------------
# Per-call user prompts
# ---------------------------------------------------------------------------


def domain_map_prompt(domain: str, constraints: str, content: str) -> str:
    return (
        f"Domain: {domain}\nConstraints: {constraints or 'none'}\n\n"
        f"Domain evidence:\n{content}\n\n"
        "Produce the DomainMap JSON."
    )


def layer_analysis_prompt(layer: str, domain: str, constraints: str, context: str) -> str:
    return (
        f"Layer: {layer}\nDomain: {domain}\nConstraints: {constraints or 'none'}\n\n"
        f"Domain evidence and domain map:\n{context}\n\n"
        f"Produce the LayerAnalysis JSON for the {layer} layer only."
    )


def draft_prompt(
    layer: str,
    analysis_json: str,
    context: str,
    constraints: str = "",
    domain_map_json: str = "",
) -> str:
    return (
        f"Layer: {layer}\nConstraints: {constraints or 'none'}\n\n"
        f"Domain map:\n{domain_map_json}\n\n"
        f"Layer analysis:\n{analysis_json}\n\n"
        f"Domain context:\n{context}\n\n"
        "Produce the DraftBatch JSON with 1-2 drafts for this layer."
    )


def critique_prompt(draft_json: str, other_titles: list[str], evidence: str = "") -> str:
    others = ", ".join(other_titles) or "none"
    return (
        f"Other opportunities in this run (for differentiation): {others}\n\n"
        f"Source evidence for groundedness checks:\n{evidence}\n\n"
        f"Draft under review:\n{draft_json}\n\n"
        "Produce the Critique JSON."
    )


def refine_prompt(
    draft_json: str,
    critique_json: str,
    evidence: str = "",
    constraints: str = "",
) -> str:
    return (
        f"Constraints: {constraints or 'none'}\n\n"
        f"Source evidence:\n{evidence}\n\n"
        f"Current draft:\n{draft_json}\n\nCritique to address:\n{critique_json}\n\n"
        "Produce the refined OpportunityDraft JSON."
    )


def score_prompt(draft_json: str, constraints: str) -> str:
    return (
        f"Constraints: {constraints or 'none'}\n\nFinal draft:\n{draft_json}\n\n"
        "Produce the ICEScore JSON (impact, confidence, ease, rationale)."
    )


def digest_prompt(filename: str, content: str) -> str:
    return (
        f"{filename}\n\nFile content:\n{content}\n\n"
        "Compress this file into a dense digest preserving actors, systems, "
        "volumes, pain points, and numbers."
    )
