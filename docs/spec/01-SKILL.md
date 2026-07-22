---
name: automation-miner
description: >
  Structured domain analysis and automation discovery engine.
  Given any industry vertical, business process, or organizational domain — with optional constraints
  (budget, tech stack, team size, compliance needs) — systematically identifies the highest-value
  automation opportunities and outputs structured AM-XXX opportunity briefs ready for evaluation.
  Use when asked to "find automations in X", "automate Y industry", or "what can we automate in Z".
  NOT a general idea engine — this is focused on automation/agentification of processes.
# Packager metadata:
provides: ["miner-engine", "automation-mining", "automation-discovery"]
tags: [automation, mining, discovery, domain, analysis, opportunity]
---

# ⛏️ Automation Miner — The Thinking Process

> **This is a domain-to-automation cognitive skill.**
> It takes a topic (industry, business process, department, operational workflow) with optional
> constraints and outputs structured automation opportunity briefs with feasibility scores.
>
> Think of it as walking into a factory/office/manufacturing floor with a map and a highlighter.

---

## When This Triggers

- Told to "find automations in [topic]" or "automate [domain]"
- Asked "what can OpenClaw automate in [industry]?"
- A new industry/domain brief arrives for automation analysis
- Someone says "this process feels manual, what can we do?"

## The Core Framework

```
Input: Domain + Constraints + Optional Context
                │
        ┌───────┴────────┐
        │  Phase 1        │
        │  Domain Mapping  │
        └───────┬────────┘
                │
        ┌───────┴────────┐
        │  Phase 2        │
        │  Process Mining  │
        │  (Layers + Pain) │
        └───────┬────────┘
                │
        ┌───────┴────────┐
        │  Phase 3        │
        │  Automation Spot │
        │  Identification  │
        └───────┬────────┘
                │
        ┌───────┴────────┐
        │  Phase 4        │
        │  Scoring + Rank  │
        └───────┬────────┘
                │
         AM-XXX Opportunity Files +
         Index Update + Discord Report
```

---

## Phase 1: Domain Mapping

**Goal:** Build a structured model of the domain — key actors, workflows, information flows, pain points.

### 1a. Domain Characterization

Read/extract or infer the following about the domain:

| Dimension | Questions |
|-----------|-----------|
| Core function | What is the primary output of this domain? (product, service, decision, coordination) |
| Key stakeholders | Who are the actors? (internal teams, external partners, customers, regulators) |
| Information flow | What data moves through this domain? (documents, approvals, reports, signals) |
| Decision density | How many human decisions per day/week? Are they rule-based or judgment-based? |
| Compliance surface | What regulations or audit requirements apply? |
| Technology maturity | What systems exist? (ERP, CRM, spreadsheets, paper, custom software) |
| Scale indicators | Transaction volume, report count, approval frequency, customer tickets |
| Manual friction | Which tasks are described as "tedious", "repetitive", "error-prone", "bottleneck"? |
| Seasonal/workflow patterns | Are there crunch periods, reporting cycles, batch processing? |

### 1b. Stakeholder-Process Matrix

Map stakeholders to their primary processes:

```
Stakeholder A → Process 1 → Process 2 → Process 3
Stakeholder B → Process 3 → Process 4
Stakeholder C → Process 5
```

Look for:
- **Handoff points** — where work moves between stakeholders (common automation target)
- **Translation points** — where data changes format or medium (high error risk)
- **Approval gates** — human review steps (high latency)
- **Reporting loops** — recurring data aggregation (high boredom)

---

## Phase 2: Process Mining — The Five Layers

Analyze the domain through **five orthogonal layers**. Each layer reveals different automation opportunities.

### Layer 1: Document & Data Processing
*Files, forms, spreadsheets, reports, data entry, extract-transform-load*

**Automation patterns:**
- Template generation (contracts, reports, proposals, invoices)
- Data extraction from structured/unstructured documents
- Cross-system data reconciliation
- Form auto-fill and validation
- Document review workflows (with human-in-the-loop)
- Automated record-keeping and audit trails

**Signal questions:**
- "How many hours does the team spend filling out forms?"
- "Are there recurring reports that follow the same template?"
- "Do people copy-paste data between systems?"
- "Are regulatory filings manual?"

### Layer 2: Communication & Coordination
*Emails, chat, meetings, status updates, escalation, notifications*

**Automation patterns:**
- Intelligent email triage and routing
- Meeting scheduling and follow-up automation
- Status report generation and distribution
- Escalation triggers based on SLA thresholds
- Cross-team notification bridges
- Client/partner communication at scale

**Signal questions:**
- "How many status meetings per week?"
- "Do people get CC'd on emails just 'to stay in the loop'?"
- "Are status reports compiled manually?"
- "Do SLA breaches happen because someone forgot to escalate?"

### Layer 3: Decision & Approval
*Rule-based decisions, approvals, exceptions, routing, delegation*

**Automation patterns:**
- Rule-based decision automation (if-X-then-Y workflows)
- Approval routing with delegation hierarchy
- Exception handling with escalation paths
- Policy compliance checking before approval
- Budget/capacity threshold auto-approval
- Audit-logged decision trails

**Signal questions:**
- "How many approvals per week involve the same criteria?"
- "Do approvers ever ask for the same information repeatedly?"
- "Are decisions delayed because the right person isn't available?"
- "Could 80% of approvals be automated with clear rules?"

### Layer 4: Monitoring & Alerting
*Exception monitoring, threshold alerts, anomaly detection, SLA tracking*

**Automation patterns:**
- Scheduled monitoring across systems
- Anomaly detection with thresholds
- Proactive alerting before threshold breach
- Cross-system correlation (Event A + Event B = Alert)
- Automated mitigation (restart, re-route, scale)
- Dashboard auto-generation

**Signal questions:**
- "Do people manually check dashboards?"
- "Are incidents discovered by customers before the team?"
- "Do monitoring scripts exist but run separately per system?"
- "Is there an unwritten 'feel' for when something is wrong?"

### Layer 5: Knowledge & Training
*Onboarding, SOPs, knowledge base, tribal knowledge, training materials*

**Automation patterns:**
- SOP-as-code (checklist automation)
- Interactive knowledge base (ask-your-docs agent)
- Onboarding playbook automation
- Training loop management (assign → complete → certify)
- Policy change propagation and acknowledgment tracking
- "Ask the expert" routing with fallback to documentation

**Signal questions:**
- "How long does it take to onboard a new team member?"
- "Is critical knowledge in people's heads, not documents?"
- "Do people ask the same questions repeatedly?"
- "Are SOPs out of date or ignored?"

---

## Phase 3: Automation Spot Identification

Spawn a sub-agent for each of the 5 layers. Each layer agent outputs **1-2 concrete automation opportunities** following this structure:

> **Layer:** [Layer name]
> **Opportunity AM-XXX:** [Short name]
> **Problem:** [1-2 sentence problem statement grounded in domain evidence]
> **Proposed automation:** [1-2 sentence description of what the automation does]
> **Inputs needed:** [What data/systems/people does this touch?]
> **Output produced:** [What gets generated, changed, or triggered?]
> **Agents required:** [Number of agents, coordination pattern if multi-agent]
> **HITL points:** [Where does a human need to review/decide?]
> **Effort estimate:** [Low/Medium/High — rough relative to other opportunities]
> **Impact estimate:** [Low/Medium/High — time saved, error reduction, speed improvement]
> **Risk level:** [Low/Medium/High — compliance, accuracy, dependency risks]

### Scoring Definitions

| Score | Effort | Impact | Risk |
|-------|--------|--------|------|
| Low | Config-level work (<1 day) | Marginal improvement (5-10%) | Reversible, no compliance impact |
| Medium | Custom development (1-5 days) | Meaningful improvement (20-40%) | Moderate, some oversight needed |
| High | Complex integration (1-4 weeks) | Transformative change (50%+) | High stakes, regulations, critical accuracy |

---

## Phase 4: Scoring & Ranking

### ICE Score Calculation

```
I = Impact (1-5) — How much time/money/quality does this unlock?
C = Confidence (1-5) — How sure are we this will work as described?
E = Ease (1-5) — How easy is this to implement?

ICE Score = I × C × E
Range: 1 (low) to 125 (high)
```

### ICE Scoring Reference

| Factor | 1 | 2 | 3 | 4 | 5 |
|--------|---|---|---|---|---|
| **Impact** | Minor time save | Team-level efficiency | Department-level transformation | Cross-department shift | Industry-competitive advantage |
| **Confidence** | Pure guess | Informed hunch | Similar pattern validated | Adjacent domain proven | Exact pattern demonstrated |
| **Ease** | Needs new infrastructure | Medium integration effort | Config + API wiring | Configuration only | Already have the tools |

### Ranking Output

Sort all opportunities by ICE score descending. Present as:

| Rank | ID | Name | I | C | E | ICE | Layer | Effort | Risk |
|------|----|------|---|---|---|------|-------|--------|------|
| 1 | AM-001 | ... | 4 | 4 | 5 | 80 | Document | Low | Low |
| 2 | AM-002 | ... | 5 | 3 | 3 | 45 | Decision | High | High |

### Strategic Filtering

After scoring, apply **three strategic filters** in order:

1. **Low-hanging fruit filter:** Any opportunity with Ease ≥ 4 AND Impact ≥ 3 → **Candidate for immediate action**
2. **High-value filter:** Any opportunity with ICE ≥ 40 AND Risk ≤ Medium → **Candidate for prioritized backlog**
3. **Vision filter:** Any opportunity with Impact = 5 AND Ease ≤ 2 → **Strategic moonshot** (note for future)

---

## Output Protocol

### Directory Structure (v2 — Partitioned)

```
obsidian/automation-mining/
├── _index.md                              ← Project overview + registry reference
├── registry.json                          ← Machine-readable cross-index (rebuilt by miner-index.py)
├── runs/
│   └── YYYY-MM-DD_<topic-slug>.md        ← Full run log for this domain analysis
└── opps/
    └── <domain-slug>/                     ← One directory per domain run
        ├── AM-001-<name>.md              ← Self-contained opportunity brief
        ├── AM-002-<name>.md
        └── ...
```

**Domain slug derivation:** Take the domain/topic name, lowercase, replace spaces with hyphens, remove special chars.
Examples: "German Healthcare System" → `german-healthcare`, "Carrier Bidding & Negotiation (eShop)" → `carrier-bidding-eshop`

### Registry Update

After writing the opportunity files, rebuild the registry:

```bash
python3 scripts/miner-index.py
python3 scripts/workspace-indexer.py
```

### Opportunity Brief Format

Each `AM-XXX-<name>.md`:

```markdown
---
am-id: "AM-001"
title: "Opportunity Name"
domain: "Domain/Run"
layer: "document"  # document, communication, decision, monitoring, knowledge
status: "identified"  # identified | evaluating | designing | implementing | live | deprecated
ice-score: 80
impact: 4
confidence: 4
ease: 5
created: "YYYY-MM-DD"
updated: "YYYY-MM-DD"
source: "YYYY-MM-DD_<topic-slug>"
tags: [automation, <layer>, <domain>]
---

# AM-001: Opportunity Name

## Problem Statement

[Detailed problem — what's broken, manual, slow, or error-prone today. Include estimated cost (time/money/quality) when possible.]

## Proposed Automation

[What the automated system would do. Include agent topology if multi-agent.]

## Process Details

### Inputs
- What data or triggers does this need?

### Steps
1. Step 1
2. Step 2
3. ...

### Outputs
- What gets produced?
- Who consumes it?

### Human-in-the-Loop Points
- Where does a human need to review, approve, or intervene?
- What triggers escalation?

## Feasibility Assessment

### Technical Requirements
- Systems needed (APIs, databases, existing tools)
- Integration complexity
- Agent architecture (single agent? swarm? pipeline?)

### Dependencies
- What must exist first before this can work?

### Constraints
- Budget, compliance, timeline, team capability

## Impact Analysis

| Dimension | Current State | Automated State | Improvement |
|-----------|--------------|----------------|-------------|
| Time | X hours/week | Y hours/week | Z% |
| Error rate | X% | Y% | Z% |
| Cost | €X/month | €Y/month | Z% |
| Staff hours freed | 0 | X hours/week | — |
| Risk/Compliance | Manual audits | Automated trails | Full audit trail |

## Implementation Path

### Phase 1: MVP (1-2 weeks)
- Minimal viable automation covering 80% of cases
- Deploy alongside existing manual process

### Phase 2: Expansion (2-4 weeks)
- Cover edge cases, exception handling
- Add monitoring and dashboards

### Phase 3: Autonomy (4-8 weeks)
- Reduce HITL points to minimum
- Self-healing and automatic escalation

## Risk & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| | H/M/L | H/M/L | |
| | | | |

---

## Self-Improvement

This opportunity was generated by the Automation Miner engine. Track its lifecycle through the pipeline:

- [ ] **Identified** — opportunity brief created
- [ ] **Validated** — domain expert confirmed problem/relevance
- [ ] **Designed** — implementation plan complete
- [ ] **Built** — prototype or MVP shipped
- [ ] **Measured** — actual impact vs. projected impact
- [ ] **Lessons learned** — what did the miner get right/wrong?

Validation criteria:
- Actual time saved vs. estimate
- Error rate improvement vs. estimate
- User satisfaction with automation
- What was missed in the analysis?
```

---

## Constraint Processing

When constraints are provided as part of the request, process them during Phase 1 and apply throughout:

| Constraint Type | Effect on Scoring & Ranking |
|------------------|-----------------------------|
| **Budget low/zero** | Prefer Ease ≥ 4 only (existing tools, config work) |
| **Budget medium** | Consider Medium-effort opportunities |
| **Budget high** | Full range available |
| **Tech stack constraint** | Filter opportunities requiring unsupported systems |
| **Team small (1-3 people)** | Prefer opportunities with 1-2 agents, low coordination overhead |
| **Compliance heavy** | Filter out high-risk opportunities, add compliance HITL points |
| **Timeline tight** | Rank by Ease ÷ Impact ratio (quick wins first) |
| **No existing infrastructure** | Focus on Layer 1 (Document) and Layer 5 (Knowledge) opportunities |
| **Existing mature stack** | Focus on Layers 2-4 (Integration, Decision, Monitoring) |
| **Specific domain given** | Ground every analysis in concrete domain examples |

### Constraint Override Rules

```
IF constraints include "urgent" or "1 week" → Skip Phase 3 sub-agents.
   Run all 5 layers inline, output top 3 opportunities ranked by Ease first.

IF constraints include "compliance" or "regulated" → Hard-cap risk = Medium.
   Flag any opportunity with Risk = High for explicit review.

IF constraints include "no coding" or "no custom dev" → Cap Ease at 4 (maximum).
   Only configuration-level opportunities considered.

IF constraints include "agent limit" → Cap concurrent agents per opportunity.
   Reroute multi-agent spots to single-agent with queuing.
```

---

## Self-Improvement

This skill follows the workspace improvement protocol:

- [ ] Track: what % of AM-XXX opportunities proceed past "identified"?
- [ ] Track: which layers produce the highest-scoring opportunities?
- [ ] Tune: adjust ICE scoring if systematic over/under estimation observed
- [ ] Expand: add new layers if gaps identified (e.g., Industry-specific layers)
- [ ] Expand: add domain-specific knowledge bases per industry vertical
- [ ] Report: quarterly automation-miner ROI (opportunities → validated → built)
