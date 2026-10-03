"""Versioned prompt templates per pipeline role.

``fragments`` holds the shared protocols, framework, ladders, and rubric;
``systems`` the role system prompts; ``tasks`` the per-call task contracts.

Version 2.0 adds the evidence protocol. Every stage receives numbered evidence
blocks and is asked to cite the ids it relied on, which turns the critic's
highest-weighted dimension (``groundedness``, 25%) from an unverifiable judgement
into something code can check: cited ids either exist in the run's evidence index
or they do not.

Version 2.1 adds the exact Pydantic JSON Schema to every structured model call,
so role descriptions and the contracts enforced by code cannot drift apart.

Version 2.2 makes absence handling explicit and gives the critic the same
evidence protocol as generation roles. Source silence is unknown, not proof
that a control, document, system, metric, or process does not exist.

Version 2.3 repeats that rule at each task boundary and makes unsupported
negative-existence claims a mandatory critic failure, after testing showed that
a general system-level instruction alone was too easy for models to overlook.

Version 3.1 adds an input preflight, explicit operational/strategy modes,
epistemic claim categories, structured quality-gate violations, and
assumption-backed impact estimates. A portfolio planner now selects a diverse,
high-value candidate set before parallel drafting, with dynamic constraint
parameters treated as binding behavior rather than a fixed keyword list.

Version 4.0 re-anchors on the product vision: expert, concrete briefs that
stay honest. Statements are observed facts, domain knowledge, or assumptions,
and epistemic status lives in structured fields rather than in prose. The 3.x
rule "say 'inferred: ...' in the text" produced briefs with dozens of
provenance hedges, and the critic blocked correct public domain knowledge
(statutory limits) as ungrounded. Blocking grounding violations are now
narrowly defined; readability defects are reported separately and repaired.

Version 4.1 adds the discovery and verification loop the first real runs
asked for: layer analysts size each pain (volume x minutes), code ranks them
into a pain ledger the planner must cover, the critic quotes each blocking
defect verbatim so a repair role can fix exactly that text, a verifier checks
the repair, and the scorer grades the whole portfolio side by side on
value-anchored ladders. A precision rule stops numbers, causes, and system
capabilities from being stretched beyond what the evidence states.

Version 4.2 reads free-text run constraints with a policy-reader role into
typed flags, each backed by a verbatim quote that code verifies, instead of
deciding binding filters with keyword patterns alone.

Version 4.3 makes arithmetic code's job. Drafts record every derived number
with its formula; code checks it, and the critic and verifier are told which
derivations are verified, so they dispute inputs, not sums. A real run lost
its best email-triage brief to a critic that computed a share of the wrong
base and a repair that adopted the wrong number.
"""

from __future__ import annotations

from automation_miner.prompts.fragments import (
    AGENT_TOPOLOGY_RULES,
    CONSTRAINT_RULES,
    CRITIC_RUBRIC,
    DOMAIN_MAP_EVIDENCE_PROTOCOL,
    EVIDENCE_PROTOCOL,
    FIVE_LAYER_FRAMEWORK,
    ICE_LADDERS,
    PAIN_QUANTIFICATION,
    SOURCE_SILENCE_GATE,
    WRITING_STANDARD,
    untrusted,
)
from automation_miner.prompts.systems import (
    CRITIC_SYSTEM,
    DOMAIN_MAP_SYSTEM,
    DRAFTER_SYSTEM,
    INPUT_ASSESSMENT_SYSTEM,
    LAYER_ANALYST_SYSTEM,
    MAPPER_SYSTEM,
    POLICY_READER_SYSTEM,
    PORTFOLIO_PLANNER_SYSTEM,
    REFINER_SYSTEM,
    REPAIR_SYSTEM,
    SCORER_SYSTEM,
    VERIFIER_SYSTEM,
)
from automation_miner.prompts.tasks import (
    DOMAIN_MAP_OUTPUT_CONTRACT,
    PRECISION_RULE,
    candidate_draft_prompt,
    coverage_revision_prompt,
    critique_prompt,
    digest_prompt,
    domain_map_prompt,
    input_assessment_prompt,
    layer_analysis_prompt,
    policy_reading_prompt,
    portfolio_plan_prompt,
    portfolio_score_prompt,
    refine_prompt,
    repair_prompt,
    score_prompt,
    verify_prompt,
)

PROMPT_VERSION = "4.3"

__all__ = [
    "PROMPT_VERSION",
    "AGENT_TOPOLOGY_RULES",
    "CONSTRAINT_RULES",
    "CRITIC_RUBRIC",
    "CRITIC_SYSTEM",
    "DOMAIN_MAP_EVIDENCE_PROTOCOL",
    "DOMAIN_MAP_OUTPUT_CONTRACT",
    "DOMAIN_MAP_SYSTEM",
    "DRAFTER_SYSTEM",
    "EVIDENCE_PROTOCOL",
    "FIVE_LAYER_FRAMEWORK",
    "ICE_LADDERS",
    "INPUT_ASSESSMENT_SYSTEM",
    "LAYER_ANALYST_SYSTEM",
    "MAPPER_SYSTEM",
    "PAIN_QUANTIFICATION",
    "POLICY_READER_SYSTEM",
    "PORTFOLIO_PLANNER_SYSTEM",
    "PRECISION_RULE",
    "REFINER_SYSTEM",
    "REPAIR_SYSTEM",
    "SCORER_SYSTEM",
    "SOURCE_SILENCE_GATE",
    "VERIFIER_SYSTEM",
    "WRITING_STANDARD",
    "candidate_draft_prompt",
    "coverage_revision_prompt",
    "critique_prompt",
    "digest_prompt",
    "domain_map_prompt",
    "input_assessment_prompt",
    "layer_analysis_prompt",
    "policy_reading_prompt",
    "portfolio_plan_prompt",
    "portfolio_score_prompt",
    "refine_prompt",
    "repair_prompt",
    "score_prompt",
    "untrusted",
    "verify_prompt",
]
