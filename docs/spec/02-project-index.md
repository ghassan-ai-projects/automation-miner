# ⛏️ Automation Mining — Project Overview

> **Purpose:** Systematically identify and document automation opportunities within any industry,
> business process, or organizational domain. Each run produces 7 scored AM-XXX opportunity briefs.
>
> **Callsign:** AM-XXX
> **Skill:** [Automation Miner](../skills/automation-miner/SKILL.md)
> **Status:** Active
> **Created:** 2026-05-02
> **Manager:** Orchestrator

---

## Architecture (v2 — Partitioned)

```
obsidian/automation-mining/
├── _index.md                     ← This file — project overview
├── registry.json                 ← Machine-readable registry with cross-indices
├── _architecture-plan-v2.md      ← Full design doc for the v2 storage architecture
├── runs/                         ← One run log per domain
│   ├── YYYY-MM-DD_<slug>.md
│   └── ...
└── opps/                         ← Partitioned by domain run
    ├── <domain-slug>/
    │   ├── AM-XXX-<name>.md      ← Self-contained opportunity brief
    │   └── ...
    └── ...
```

### Registry Query Examples

```python
# Load registry
import json
r = json.load(open("obsidian/automation-mining/registry.json"))

# Find monitoring-layer opportunities across all agriculture domains
r["by_layer"]["monitoring"]

# Find all vision-grade opportunities (ICE >= 80)
r["by_ice_range"]["vision_80plus"]

# Find opportunities by status
r["by_status"]["identified"]
```

### CLI Quick Query

```bash
# Top 10 by ICE score
cat obsidian/automation-mining/registry.json | python3 -c "
import json,sys;r=json.load(sys.stdin)
for e in r['entries'][:10]: print(f\"  {e['i']}: {e['t']} [{e['ice']}] ({e['l']}, {e['d']})\")
"

# Count by domain
cat obsidian/automation-mining/registry.json | python3 -c "
import json,sys;r=json.load(sys.stdin)
for d in r['domains']: print(f\"  {d['title']}: {d['total']} opps — top={d['top_opp']} ({d['top_ice']})\")
"
# Output:
# German Healthcare System: 7 opps — top=AM-004 (75)
# Real Estate + Smart Building Management: 7 opps — top=AM-008 (75)
# Carrier Bidding & Negotiation (eShop Perspective): 7 opps — top=AM-015 (80)
# Precision Irrigation (Agriculture Sensors & Weather): 7 opps — top=AM-022 (80)
# Greenhouse Climate Control & Automation: 7 opps — top=AM-029 (80)
# Wine Cellar Inventory & Maturation Tracking: 7 opps — top=AM-036 (100)
# Gastronomy, Tourism, and Hospitality: 21 opps — top=AM-176 (84)
```

---

## Run History

| Date | Domain | Opportunities | Top Score | Status |
|------|--------|---------------|-----------|--------|
| 2026-05-02 | German Healthcare System | 7 (AM-001 → AM-007) | 75 (AM-004) | Complete |
| 2026-05-02 | Real Estate + Smart Building Management | 7 (AM-008 → AM-014) | 75 (AM-008) | Complete |
| 2026-05-02 | Carrier Bidding & Negotiation (eShop) | 7 (AM-015 → AM-021) | 80 (AM-015) | Complete |
| 2026-05-02 | Precision Irrigation (Agriculture Sensors & Weather) | 7 (AM-022 → AM-028) | 80 (AM-022) | Complete |
| 2026-05-02 | Greenhouse Climate Control & Automation | 7 (AM-029 → AM-035) | 80 (AM-029) | Complete |
| 2026-05-02 | Wine Cellar Inventory & Maturation Tracking | 7 (AM-036 → AM-042) | 100 (AM-036) | Complete |
| 2026-05-02 | Hazardous Waste Tracking & Management | 7 (AM-043 → AM-049) | 100 (AM-043) | Complete |
| 2026-05-02 | Legal, Tax, and Financial Professional Services | 7 (AM-050 → AM-056) | 100 (AM-050) | Complete |
| 2026-05-02 | Gastronomy, Tourism, and Hospitality | 7 (AM-057 → AM-063) | 80 (AM-057, AM-059) | Complete |
| 2026-05-02 | ESG, Sustainability, and Green Manufacturing | 7 (AM-064 → AM-070) | 100 (AM-064) | Complete |
| 2026-05-02 | Public Sector & Administrative Automation | 7 (AM-071 → AM-077) | 100 (AM-074) | Complete |
| 2026-05-02 | Consumer Productivity and AI Ecosystem Tools | 7 (AM-078 → AM-084) | 100 (AM-078) | Complete |
| 2026-05-02 | Industrial Engineering and Manufacturing 4.0 | 7 (AM-085 → AM-091) | 64 (AM-086, AM-091) | Complete |
| 2026-05-02 | Logistics, E-commerce, and Cross-Border Compliance | 7 (AM-092 → AM-098) | 100 (AM-092) | Complete |
| 2026-05-02 | Agriculture, Handwerk, and Specialized Labor | 7 (AM-099 → AM-105) | 100 (AM-099) | Complete |
| 2026-05-03 | German Healthcare System — P2 | 7 (AM-106 → AM-112) | 80 (AM-106, AM-109) | Complete |
| 2026-05-03 | German Healthcare System — P3 (Final Pass) | 7 (AM-127 → AM-133) | 75 (AM-128) | Complete |
| 2026-05-03 | Legal, Tax, and Financial Professional Services — P2 | 7 (AM-141 → AM-147) | 96 (AM-141) | Complete |
| 2026-05-03 | Legal, Tax, and Financial Professional Services — P3 (Final Pass) | 7 (AM-148 → AM-154) | 75 (AM-153) | Complete |
| 2026-05-03 | Industrial Engineering & Manufacturing 4.0 — P2 | 7 (AM-155 → AM-161) | 80 (AM-161) | Complete |
| 2026-05-03 | Industrial Engineering & Manufacturing 4.0 — P3 (Final Pass) | 7 (AM-162 → AM-168) | 80 (AM-162) | Complete |
| 2026-05-03 | Gastronomy, Tourism & Hospitality — P2 | 7 (AM-176 → AM-182) | 84 (AM-176) | Complete |
| 2026-05-03 | ESG, Sustainability & Green Manufacturing — P2 | 7 (AM-190 → AM-196) | 84 (AM-190) | Complete |
| 2026-05-03 | ESG, Sustainability & Green Manufacturing — P3 (Final Pass) | 7 (AM-197 → AM-203) | 75 (AM-197, AM-199) | Complete |
| 2026-05-03 | Public Sector & Administrative Automation — P3 (Final Pass) | 7 (AM-211 → AM-217) | 81 (AM-211, AM-217) | Complete |
| 2026-05-03 | Consumer Productivity and AI Ecosystem Tools — P2 | 7 (AM-218 → AM-224) | 96 (AM-224) | Complete |
| 2026-05-03 | Consumer Productivity and AI Ecosystem Tools — P3 | 7 (AM-225 → AM-231) | 84 (AM-226, AM-230) | Complete |
| 2026-05-03 | Consumer Productivity and AI Ecosystem Tools — P4 | 7 (AM-232 → AM-238) | 84 (AM-235) | Complete |
| 2026-05-03 | Consumer Productivity and AI Ecosystem Tools — P5 (Final Batch) | 7 (AM-239 → AM-245) | 96 (AM-241) | Complete |
| 2026-05-03 | Final Grab Bag — Best Remaining Ideas (250+ Milestone) | 7 (AM-246 → AM-252) | 90 (AM-252) | Complete |
| 2026-05-04 | IS-016 / Dynamic Pricing Matrix Monitor | 5 (AM-253 → AM-257) | — | Complete |
| 2026-05-04 | IS-017 / Legacy Software Pain Miner | 5 (AM-258 → AM-262) | — | Complete |
| 2026-05-04 | IS-018 / App Store Review Arbitrage | 5 (AM-263 → AM-267) | — | Complete |
| 2026-05-04 | IS-019 / Patent Pivot Tracker | 5 (AM-268 → AM-272) | — | Complete |
| 2026-05-04 | IS-020 / Ghost Job Market Mapper | 5 (AM-273 → AM-277) | — | Complete |
| 2026-05-04 | IS-021 / Trigger-Event Lead Miner | 5 (AM-278 → AM-282) | — | Complete |
| 2026-05-04 | IS-022 / Tech Stack Vulnerability Scanner | 5 (AM-283 → AM-287) | — | Complete |
| 2026-05-04 | IS-023 / Grant & Subsidy Matchmaker | 5 (AM-288 → AM-292) | — | Complete |
| 2026-05-04 | IS-024 / Conference Speaker Synthesis | 5 (AM-293 → AM-297) | — | Complete |
| 2026-05-04 | IS-025 / Mittelstand Succession Spotter | 5 (AM-298 → AM-302) | — | Complete |
| 2026-05-04 | IS-026 / Municipal Zoning Arbitrage | 5 (AM-303 → AM-307) | — | Complete |
| 2026-05-04 | IS-027 / Energy Rate Arbitrage | 5 (AM-308 → AM-312) | — | Complete |
| 2026-05-04 | IS-028 / Supply Chain Bottleneck | 5 (AM-313 → AM-317) | — | Complete |
| 2026-05-04 | IS-029 / ESG Compliance Auditor | 5 (AM-318 → AM-322) | — | Complete |
| 2026-05-04 | IS-030 / Vergabemarktplatz Tender Sniper | 5 (AM-323 → AM-327) | — | Complete |
| 2026-05-04 | IS-031 / Programmatic SEO Gap Analyzer | 5 (AM-328 → AM-332) | — | Complete |
| 2026-05-04 | IS-032 / Academic Paper Commercializer | 5 (AM-333 → AM-337) | — | Complete |
| 2026-05-04 | IS-033 / Video Transcript → B2B Insights | 5 (AM-338 → AM-342) | — | Complete |
| 2026-05-04 | IS-034 / Dark Social Link Miner | 5 (AM-343 → AM-347) | — | Complete |
| 2026-05-04 | IS-035 / Automated Newsletter Engine | 5 (AM-348 → AM-352) | — | Complete |
| 2026-05-04 | IS-036 / Cloud API Cost Auditor | 5 (AM-353 → AM-357) | — | Complete |
| 2026-05-04 | IS-037 / SaaS Bloat Detector | 5 (AM-358 → AM-362) | — | Complete |
| 2026-05-04 | IS-038 / Automated Procurement Negotiator | 5 (AM-363 → AM-367) | — | Complete |
| 2026-05-04 | IS-039 / EU Funding & Tax Strategist | 5 (AM-368 → AM-372) | — | Complete |
| 2026-05-04 | IS-040 / Niche Marketplace Arbitrage | 5 (AM-373 → AM-377) | — | Complete |

---

## Pipeline Metrics

| Metric | Value |
|--------|-------|
| Runs completed | 61 |
| Opportunities identified | 382 |
| Opportunities validated | 0 |
| Opportunities designed | 0 |
| Opportunities built | 0 |
| Conversion rate (identified → built) | — |
| New domains from Idea Pipeline | 25 |
| Average ICE score | ~60 |
| Top opportunity | AM-099 (ICE 100) |
| Total domains covered | 43 |

---

## Registry

The machine-readable registry at `registry.json` provides:

| Index | Purpose |
|-------|---------|
| `entries` | All 42 opps ranked by ICE score descending |
| `domains` | 6 domain summaries with totals and top opps |
| `by_layer` | Opps grouped by process layer (document/communication/decision/monitoring/knowledge) |
| `by_ice_range` | Opps grouped by score range (vision_80plus/high_60_79/medium_40_59/low_under_40) |
| `by_status` | Opps grouped by lifecycle status |

Rebuild with: `python3 scripts/miner-index.py`

---

## Activity Log

| Date | Action | Domain | Details |
|------|--------|--------|---------|
| 2026-05-02 | Project created | — | Automation Miner skill created. Project initialized. |
| 2026-05-02 | v2 storage upgrade | — | Partitioned directory structure + registry.json + miner-index.py. Updated workspace-indexer for subdirectory scan. |
| 2026-05-02 | First run | German Healthcare | 7 AM opportunities generated. Top-scoring: AM-004 (ICE=75). |
| 2026-05-02 | Second run | Real Estate + Smart Building | 7 AM opportunities generated (AM-008→AM-014). Top-scoring: AM-008 (ICE=75). |
| 2026-05-02 | Third run | Carrier Bidding & Negotiation (eShop) | 7 AM opportunities generated (AM-015→AM-021). Top-scoring: AM-015 (ICE=80). |
| 2026-05-02 | Fourth run | Precision Irrigation | 7 AM opportunities generated (AM-022→AM-028). Top-scoring: AM-022 (ICE=80). |
| 2026-05-02 | Fifth run | Greenhouse Climate Control | 7 AM opportunities generated (AM-029→AM-035). Top-scoring: AM-029 (ICE=80). |
| 2026-05-02 | Sixth run | Wine Cellar Inventory | 7 AM opportunities generated (AM-036→AM-042). Top-scoring: AM-036 (ICE=100). |
| 2026-05-02 | Seventh run | Hazardous Waste Tracking & Management | 7 AM opportunities generated (AM-043→AM-049). Top-scoring: AM-043 (ICE=100). |
| 2026-05-02 | Eighth run | Legal, Tax, and Financial Professional Services | 7 AM opportunities generated (AM-050→AM-056). Top-scoring: AM-050 (ICE=100). |
| 2026-05-02 | Ninth run | Gastronomy, Tourism, and Hospitality | 7 AM opportunities generated (AM-057→AM-063). Top-scoring: AM-057/059 (ICE=80). |
| 2026-05-02 | Tenth run | ESG, Sustainability, and Green Manufacturing | 7 AM opportunities generated (AM-064→AM-070). Top-scoring: AM-064 (ICE=100). |
| 2026-05-02 | Eleventh run | Public Sector & Administrative Automation | 7 AM opportunities generated (AM-071→AM-077). Top-scoring: AM-074 (ICE=100). Layer coverage: monitoring(2), document(2), communication(1), decision(1), knowledge(1). |
| 2026-05-03 | Thirtieth run | Public Sector & Administrative Automation — P2 | 7 AM opportunities generated (AM-204→AM-210). Top-scoring: AM-205/206 (ICE=100). Layer coverage: knowledge(1), communication(1), document(1), monitoring(2), decision(2). |
| 2026-05-02 | Twelfth run | Consumer Productivity and AI Ecosystem Tools | 7 AM opportunities generated (AM-078→AM-084). Top-scoring: AM-078 (ICE=100). Layer coverage: decision(2), document(1), communication(1), monitoring(2), knowledge(1). |
| 2026-05-02 | Thirteenth run | Industrial Engineering and Manufacturing 4.0 | 7 AM opportunities generated (AM-085→AM-091). Top-scoring: AM-086/091 (ICE=64). Layer coverage: document(2), communication(1), decision(1), monitoring(2), knowledge(1). |
| 2026-05-02 | Fifteenth run | Agriculture, Handwerk, and Specialized Labor | 7 AM opportunities generated (AM-099→AM-105). Top-scoring: AM-099 (ICE=100). Layer coverage: document(2), communication(1), decision(1), monitoring(2), knowledge(1). |
| 2026-05-03 | Sixteenth run | German Healthcare System — P2 | 7 AM opportunities generated (AM-106→AM-112). Top-scoring: AM-106/109 (ICE=80). Layer coverage: document(2), communication(3), decision(1), monitoring(1). |
| 2026-05-03 | Seventeenth run | Real Estate + Smart Building — P2 | 7 AM opportunities generated (AM-113→AM-119). Top-scoring: AM-113 (ICE=64). Layer coverage: document(2), communication(2), decision(2), monitoring(1). |
| 2026-05-03 | Eighteenth run | Real Estate + Smart Building — P3 (Final Pass) | 7 AM opportunities generated (AM-120→AM-126). Top-scoring: AM-122 (ICE=60). Layer coverage: document(1), communication(2), decision(1), monitoring(2), knowledge(1). |
| 2026-05-03 | Nineteenth run | German Healthcare System — P3 (Final Pass) | 7 AM opportunities generated (AM-127→AM-133). Top-scoring: AM-128 (ICE=75). Layer coverage: document(1), communication(2), decision(1), monitoring(2), knowledge(1). |
| 2026-05-03 | **Twentieth run** | Real Estate + Smart Building — P4 (Final Coverage Pass) | 7 AM opportunities generated (AM-134→AM-140). Top-scoring: AM-138/139 (ICE=54). Layer coverage: document(1), communication(1), decision(1), monitoring(2), knowledge(2). |
| 2026-05-03 | **Twenty-first run** | Legal, Tax, and Financial Professional Services — P2 | 7 AM opportunities generated (AM-141→AM-147). Top-scoring: AM-141 (ICE=96). Layer coverage: document(2), communication(2), decision(2), monitoring(1). |
| 2026-05-03 | **Twenty-second run** | Legal, Tax, and Financial Professional Services — P3 (Final Pass) | 7 AM opportunities generated (AM-148→AM-154). Top-scoring: AM-153 (ICE=75). Layer coverage: document(2), communication(1), decision(2), monitoring(1), knowledge(1). |
| 2026-05-03 | **Twenty-third run** | Industrial Engineering & Manufacturing 4.0 — P2 | 7 AM opportunities generated (AM-155→AM-161). Top-scoring: AM-161 (ICE=80). Layer coverage: document(2), communication(1), decision(1), monitoring(1), knowledge(2). |
| 2026-05-03 | **Twenty-fourth run** | Industrial Engineering & Manufacturing 4.0 — P3 (Final Pass) | 7 AM opportunities generated (AM-162→AM-168). Top-scoring: AM-162 (ICE=80). Layer coverage: document(2), communication(1), decision(2), monitoring(1), knowledge(1). |
| 2026-05-03 | **Twenty-fifth run** | Logistics, E-commerce & Cross-Border Compliance — P2 | 7 AM opportunities generated (AM-169→AM-175). Top-scoring: AM-175 (ICE=80). Layer coverage: document(1), monitoring(2), communication(1), decision(2), knowledge(1). |
| 2026-05-03 | **Twenty-sixth run** | Gastronomy, Tourism & Hospitality — P2 | 7 AM opportunities generated (AM-176→AM-182). Top-scoring: AM-176 (ICE=84). Layer coverage: document(2), communication(1), decision(2), monitoring(1), knowledge(1). |
| 2026-05-03 | **Twenty-seventh run** | Gastronomy, Tourism & Hospitality — P3 (Final Pass) | 7 AM opportunities generated (AM-183→AM-189). Top-scoring: AM-183/184/186/187 (ICE=48). Layer coverage: document(1), communication(2), decision(1), monitoring(2), knowledge(1). |
| 2026-05-03 | **Twenty-eighth run** | ESG, Sustainability & Green Manufacturing — P2 | 7 AM opportunities generated (AM-190→AM-196). Top-scoring: AM-190 (ICE=84). Layer coverage: document(2), communication(1), decision(2), monitoring(1), knowledge(1). |
| 2026-05-03 | **Twenty-ninth run** | ESG, Sustainability & Green Manufacturing — P3 (Final Pass) | 7 AM opportunities generated (AM-197→AM-203). Top-scoring: AM-197/199 (ICE=75). Layer coverage: document(1), communication(1), decision(2), monitoring(2), knowledge(1). |
| 2026-05-03 | **Thirtieth run** | Public Sector & Administrative Automation — P2 | 7 AM opportunities generated (AM-204→AM-210). Top-scoring: AM-205/206 (ICE=100). Layer coverage: knowledge(1), communication(1), document(1), monitoring(2), decision(2). |
| 2026-05-03 | **Thirty-first run** | Public Sector & Administrative Automation — P3 (Final Pass) | 7 AM opportunities generated (AM-211→AM-217). Top-scoring: AM-211/217 (ICE=81). Layer coverage: document(1), communication(0), decision(1), monitoring(3), knowledge(2). |
| 2026-05-03 | **Thirty-second run** | Consumer Productivity and AI Ecosystem Tools — P2 | 7 AM opportunities generated (AM-218→AM-224). Top-scoring: AM-224 (ICE=96). Layer coverage: document(1), communication(2), decision(2), monitoring(1), knowledge(1). |
| 2026-05-03 | **Thirty-third run** | Consumer Productivity and AI Ecosystem Tools — P3 | 7 AM opportunities generated (AM-225→AM-231). Top-scoring: AM-226, AM-230 (ICE=84). Layer coverage: document(2), communication(2), decision(1), monitoring(1), knowledge(1). |
| 2026-05-03 | **Thirty-fourth run** | Consumer Productivity and AI Ecosystem Tools — P4 | 7 AM opportunities generated (AM-232→AM-238). Top-scoring: AM-235 (ICE=84). |
| 2026-05-03 | **Thirty-fifth run** | Consumer Productivity and AI Ecosystem Tools — P5 (Final Batch) | 7 AM opportunities generated (AM-239→AM-245). Top-scoring: AM-241 (ICE=96). |
| 2026-05-03 | **Thirty-sixth run** | Final Grab Bag — Best Remaining Ideas (250+ Milestone) | 7 AM opportunities generated (AM-246→AM-252). Top-scoring: AM-252 (ICE=90). Layer coverage: document(1), communication(1), decision(2), monitoring(2), knowledge(1). |

---

## Public Sector & Administrative Automation — Total Coverage

| Run | Opportunities |
|-----|---------------|
| P1 (AM-071→AM-077) | eVergabeAggregator/KfwGrantMatcher/WohngeldAssistant/BürgeramtMonitor/BAföGCopilot/DocRetentionTracker/EnergySubsidyZoll |
| P2 (AM-204→AM-210) | ImmigrationTracker/SocialBenefitNavigator/ParkingDisputeBot/FloodRiskCommunicator/SCMCalculator/PedestrianHotspot/ParkSpaceForecast |
| P3 (AM-211→AM-217) | WasteCollectionOptimizer/CensusQueryBot/EVChargerPlanner/VotingAccessibilityChecker/GovChatbotQA/PoolOccupancyBot/PensionEligibilityChecker |

**Total:** 21 AM briefs covering all primary, secondary, and tertiary passes across G1–G25 ideas.

---

## Consumer Productivity & AI Ecosystem Tools — Total Coverage

| Run | Opportunities |
|-----|---------------|
| P1 (AM-078→AM-084) | SubscriptionCancellator / PersonalFinanceTriage / WhatsAppSignalContext / HomeSecurity / SoulDesigner / SmartAudio / GroceryAutopilot |
| P2 (AM-218→AM-224) | ReceiptDigitizer / GermanIdiomCoach / PersonalInsuranceAudit / SeniorSafetyCheckIn / KleinanzeigenAutoResponder / EnergyContractOptimizer / ChangeOfAddressHub |
| P3 (AM-225→AM-231) | NutritionLabelScanner / SchoolCommunicationTranslator / GermanTaxAssistant / MentalWellnessTracker / SeniorTechTutor / EmergencyWalletDigitalAusweis / MovingCostPlanner |

| P4 (AM-232→AM-238) | German CV Optimizer / Lost Document Reporter / WG Expense Splitter / Smart Meter Reminder / Berliner Testament Builder / Solar Feed-In Monitor / German Payroll Calculator |
| P5 (AM-239→AM-245) | E-Rezept Availability Monitor / Hausrat Inventory Builder / Behörde Queue Skipper / Personal Cloud GDPR Auditor / Mietpreisbremse Calculator / Nebenkostenabrechnung Auditor / KfW Grant Finder |

**Total:** 35 AM briefs covering C1–C25 ideas plus bonus high-value consumer automation opportunities.

---

## Gastronomy, Tourism & Hospitality — Total Coverage

| Run | Opportunities | 
|-----|---------------|
| P1 (AM-057→AM-063) | MenuMargin/BookingRecovery/DynamicPricing/InvoiceFolio/EnergySentinel/ReviewSentinel/LaborLawShift |
| P2 (AM-176→AM-182) | KitchenWaste/InvoiceTaxBot/ReviewResponder/CrowdFlow/MenuLocalization/PayAsYouWaste/HygieneCalendar |
| P3 (AM-183→AM-189) | EventSpaceBooker/LoyaltyAutomator/ChurnPredictor/SupplierScorecard/PourCostMonitor/CoWorkingCafeMonitor/SeasonalMenuGen |

**Total:** 21 AM briefs covering all primary, secondary, and tertiary passes across T1–T25 ideas.

---

## Real Estate + Smart Building — Total Coverage

| Run | Opportunities | 
|-----|---------------|
| P1 (AM-008→AM-014) | Lease/EPC/Maintenance/Renovation/Anomaly/Compliance/GEG |
| P2 (AM-113→AM-119) | Listing/Rental/Tax/Tenders/SiteSelection/HVAC/Logbook |
| P3 (AM-120→AM-126) | VirtualTour/Thermal+Facility/Lighting/CarbonTax/Neighborhood/Leads/Solar+SmartMeter |
| P4 (AM-134→AM-140) | ConstructionLogistics/Sentiment/EPBDPassport/SiteSelect-v2/ThermalLeak/SmartMeterBroker/CarbonPortfolioRisk |

**Total:** 28 AM briefs covering all R1–R25 ideas.

---

## Industrial Engineering & Manufacturing — Total Coverage

| Run | Opportunities | 
|-----|---------------|
| P1 (AM-085→AM-091) | HazWaste/Predictive/ISO/LiDAR/Shift/PLC/Cyber/EnergyArb |
| P2 (AM-155→AM-161) | SupplyChain/OEE/PCB/VR/Supplier/Mängelmelder/Nesting |
| P3 (AM-162→AM-168) | EnergyAudit/WaterRecovery/LostProduction/Noise/Coating/Safety/SubcontractPay |

**Total:** 21 AM briefs covering all M1–M25 ideas.

## Logistics, E-commerce & Cross-Border Compliance — Total Coverage

| Run | Opportunities | 
|-----|---------------|
| P1 (AM-092→AM-098) | XRechnung/LkSG/Returns/HSTriage/HS Code/StrikeRisk/Fraud |
| P2 (AM-169→AM-175) | DangerousGoodsDocs/CO₂Route/LockerLobbyist/LaneMargin/POD/CargoDamage/VATCalc |

**Total:** 14 AM briefs covering both primary and secondary passes across L1–L25.

## ESG, Sustainability & Green Manufacturing — Total Coverage

| Run | Opportunities |
|-----|---------------|
| P1 (AM-064→AM-070) | CSRDReport/SupplierAudit/DualMateriality/DNKReport/CarbonTax/EUTaxonomy/ESGKnowledge |
| P2 (AM-190→AM-196) | ProductPassport/CSDDDScreening/ESGRatingImprover/PlasticsBalanceSheet/WaterMonitor/BuildingRoadmap/CarbonCreditMatch |
| P3 (AM-197→AM-203) | TNFDBiodiversity/BatteryRecycling/ESGProcurement/EWaste/LCAfromBOM/EVFleet/CarbonRemovalCRCF |

**Total:** 21 AM briefs covering all E1–E25 ideas across three complete passes.

---

## Architecture Notes

### Relationship to Other Systems

| System | Relationship |
|--------|-------------|
| **Idea Engine** | Idea Engine generates *products and startups*. Automation Miner finds *internal process automations*. AM outputs can feed IS pipeline when an automation morphs into a product opportunity. |
| **Product Planner** | When an AM opportunity is validated, it can feed into the Product Planner as discovery input for PP-XXX briefs. |
| **Research Pipeline** | Use researcher skill to deep-dive an AM opportunity's feasibility, market size, or technical approach. |
| **Issue Management** | Issues discovered during automation analysis (e.g., systemic manual friction) may feed into ISSUE-XXX items. |

### Lifecycle Tags

| Tag | Meaning |
|-----|---------|
| `identified` | Brief written, not yet validated |
| `validating` | Domain expert confirmed the problem |
| `designing` | Implementation plan in progress |
| `building` | Prototype/MVP in development |
| `live` | Automation deployed and operational |
| `deprecated` | No longer relevant or replaced |

---

## Upcoming

- **🎉 250+ MILESTONE ACHIEVED** — 252 automation opportunities identified across 35 runs
- Transition to **validation phase**: domain expert confirmation of top-scoring opportunities
- Consider **design pipeline**: convert top 10-20 AM briefs into PP (Product Planner) briefs
- Frontmatter `domain:` field auto-populated by Miner output protocol
