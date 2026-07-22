# Automation Miner — Complete Artifact Packet
Delivered: 2026-07-22 | Target: LangChain Rebuild (orch machine)

## Contents

| # | File | Description |
|---|------|-------------|
| 01 | `01-SKILL.md` | Full miner cognitive skill — 4 phases, 5 layers, ICE scoring, constraints engine |
| 02 | `02-project-index.md` | Project overview with full 62-run history across 43 domains |
| 03 | `03-architecture-plan-v2.md` | v2 partitioned storage design (scales to 1000+ opps) |
| 04 | `04-registry.json` | Machine-readable registry — 386 opps, cross-indices (167KB) |
| 05 | `05-miner-index.py` | Python registry builder script (7KB) |
| 06 | `06-milestone-coverage.md` | 250+ milestone tracker |
| 07 | `07-run-template.md` | Run log template for new domains |
| 08a | `08a-AM-099-sample-opp.md` | Top-scoring opp: Handwerk Quote Generator (ICE=100) |
| 08b | `08b-AM-036-sample-opp.md` | High-scoring opp: Wine Barrel ID Digital Cellar Map (ICE=100) |
| 09 | `09-ART-016-architecture-article.md` | LinkedIn article on the 5-layer pattern discovery |
| 10 | `10-ART-017-discovery-article.md` | LinkedIn article on 42-opps-in-one-day story |

## Stats

- **Runs completed:** 62 | **Domains covered:** 43
- **Opportunities identified:** 386 (AM-001 → AM-377)
- **Avg ICE:** 60.4 | **Top ICE:** 100 (AM-099, AM-036, AM-043, AM-050, etc.)
- **Layers:** document(62), communication(47), decision(62), monitoring(94), knowledge(45)
- **Status:** All 386 = "identified" (validation/design/build pipeline hasn't started)

## Core Algorithm Summary

Phase 1: Domain Mapping (actors, data flows, friction, regulations, scale)
Phase 2: 5-Layer Process Analysis (Document, Communication, Decision, Monitoring, Knowledge)
Phase 3: Opportunity Spot ID (sub-agents per layer → 1-2 concrete opps each)
Phase 4: ICE Scoring (Impact × Confidence × Ease, each 1-5, max 125)

**Key insight:** Best opps follow "data exists + last-mile automation missing" pattern.

## For LangChain Rebuild

The current miner runs entirely as a cognitive process within the Orchestrator — it uses sub-agents and structured prompting but no LangChain/LangGraph framework. To rebuild with LangChain:

1. **Phase 1** → Domain characterization agent (structured extraction)
2. **Phase 2** → 5 parallel layer-analysis agents (LangGraph parallel branch)
3. **Phase 3** → Opportunity generation (structured output per layer)
4. **Phase 4** → ICE scoring + strategic filter

The registry (`registry.json`) and output protocol (opps/<domain>/ + miner-index.py) can stay unchanged.
