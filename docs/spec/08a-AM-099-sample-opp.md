---
am-id: "AM-099"
title: "Handwerk Quote Generator (30-Second PDF Quoting)"
domain: "Agriculture, Handwerk, and Specialized Labor"
layer: "document"
status: "identified"
ice-score: 100
impact: 5
confidence: 5
ease: 4
created: "2026-05-02"
updated: "2026-05-02"
source: "2026-05-02_agriculture-handwerk"
tags: [automation, agriculture, handwerk, germany, skilled-trades, farming, document, quoting, pdf-generation, electricians, painters, plumbers, werkfix, mittelstand]
---

# AM-099: Handwerk Quote Generator (30-Second PDF Quoting)

## Problem Statement

The #1 operational bottleneck for German skilled trades — electricians, plumbers, painters, carpenters, HVAC technicians — is **quoting**. A standard quote for a residential or small commercial job takes 2-4 hours to produce manually: the tradesperson measures the site, returns to the office, types up materials from memory, calculates labor based on gut feel, formats a PDF in Word/Excel, prints or emails it, and follows up by phone. WerkFix, a German startup, demonstrated that AI-powered quoting can reduce this from 3 hours to under 30 seconds. Yet 95%+ of the ~750,000 Handwerk businesses in Germany still quote manually. The consequences: (1) tradespeople spend 15-25 hours/week on quoting instead of billable work, (2) customers wait 2-7 days for a quote and often accept 3+ quotes before deciding, creating long sales cycles, (3) quotes are frequently inaccurate — materials are forgotten, labor hours are guessed — leading to profit erosion or client disputes, (4) many trades simply don't respond to small jobs (<€2,000) because the quoting overhead makes them unprofitable, creating a massive underserved market. For the average electrician or painter, bad quoting costs €30K-€60K/year in lost revenue.

## Proposed Automation

A quoting agent that takes natural-language descriptions + optional photos of the job site — submitted via WhatsApp, Signal, voice memo, or web form — and produces a professionally formatted, DIN-compliant PDF quote within 30 seconds. The agent knows current German material prices (Baumarkt catalogs, online suppliers, regional wholesaler price lists), standard labor rates per trade (tarifliche Löhne per Bundesland), and typical work scopes (e.g., "install 5 outlets in a 60m² apartment" → knows it requires 40m of cable, 5 Unterputzdosen, 1 FI-Schalter if new circuit, 3-4 hours labor). It outputs a quote in a format that satisfies the Preisangabenverordnung (PAngV) and VOB standards, and can export directly to DATEV or Lexoffice for invoicing.

## Process Details

### Inputs
- Job description: natural language text, voice memo, or structured form (address, trade type, room count, specific requests)
- Photos: 1-5 photos of the job site (wall to be painted, electrical panel, pipe layout) for visual material estimation
- Customer info: name, address, contact, billing details
- Trade profile: the tradesperson's hourly rate, markup percentage, preferred suppliers, local VAT rate
- Geolocation: to pull regional material prices and labor norms

### Steps
1. **Parse Input:** LLM extracts job parameters from unstructured text/voice/photo. For photos, vision model identifies room dimensions, wall area, electrical panel type, pipe materials. Confidence scores on each extracted parameter.
2. **Material Estimate:** Agent queries current material prices from integrated catalogs (Hornbach, Obi, Selgros C+C, or regional Fachgroßhandel via API). Calculates exact quantities: paint liters per m² of wall area, cable meters per outlet count, pipe meters per radiator.
3. **Labor Estimate:** Matches job scope to standard POS (Positionen) from the Gewerke-Katalog (e.g., VOB/C standard positions for electrical/painting/plumbing work). Applies the tradesperson's registered hourly rate and adds travel time, disposal fees, scaffolding if needed.
4. **Quote Generation:** Formats a proper German offer — with Briefkopf, Leistungsbeschreibung, position-by-position breakdown (number of units × unit price), net total, VAT (19% or 7%), gross total, Zahlungsziel (14 days common), validity period, and acceptance field. Outputs as PDF/A-3 for legal archiving.
5. **Customer Delivery:** Sends to customer via preferred channel (WhatsApp, email, post). Optionally embeds an "Accept & Book" button that triggers a dunning/scheduling workflow.
6. **Post-Acceptance Handoff:** If accepted, quote data flows to scheduling agent (AM-102) for appointment booking, and to invoicing system (DATEV/Lexoffice API) for automatic bill creation upon job completion.

### Outputs
- DIN-compliant PDF quote with individual positions, net/gross totals, VAT breakdown, payment terms
- Machine-readable JSON: same data for integration with invoice software
- Optional: material shopping list sorted by supplier, labor hour breakdown by phase
- Acceptance tracking: did the customer open, sign, and return?

### Human-in-the-Loop Points
- Photo-to-quantity conversion: vision model estimates are flagged with confidence scores; the tradesperson reviews and adjusts (e.g., "that wall was actually 12m² not 10m²")
- Non-standard work: if the prompt describes work outside the agent's know scope (e.g., "install a smart home system with KNX bus"), agent flags as partial-automation — tradespersons fills gaps
- Material substitutions: if the tradesperson prefers a specific brand not in the default catalog, they can set preferences once per profile
- Price validation: agent flags if material costs exceed 20% of the estimate (e.g., copper cable price spike) for manual override

## Feasibility Assessment

### Technical Requirements
- LLM with tool-calling + vision: for parsing images (room photos, panel photos) and reasoning about job scope
- Material price database: live API feeds from German wholesalers (Hornbach B2B, Obi Pro, Selgros, or regional metal/electric suppliers)
- PDF generation engine: wkhtmltopdf or WeasyPrint + German quote templates
- WhatsApp Business API / Signal bot / Telegram bot for multimodal input
- DATEV/Lexoffice API: for invoice handoff
- Storage: S3 or local for quote PDFs, customer data

### Dependencies
- Material price APIs: some regional wholesalers lack public APIs; may need web scraping or manual price catalog import
- Trade-specific knowledge base: standard POS positions vary by Gewerk (craft category) — need to encode VOB/C standards for electrical (DIN VDE 0100), plumbing (DIN 1988), painting (DIN 18363), etc.
- Customer data privacy: GDPR-compliant storage of customer names, addresses, job photos

### Constraints
- Handwerk requires the _Unterschrift_ on physical quotes for some customer segments (older homeowners, commercial clients). Agent must support both digital signature and print+sign.
- Some German states have specific quote formatting requirements (e.g., Bauleistungsangebot must include Gewährleistung text per BGB §634a). Agent must be state-aware.
- Material prices change weekly; agent needs regular catalog sync (cron job every Monday morning)

## Impact Analysis

| Dimension | Current State | Automated State | Improvement |
|-----------|--------------|----------------|-------------|
| Quote production time | 2-4 hours per quote | 30 seconds | **99% reduction** |
| Quotes sent per tradesperson/week | 3-5 (limited by time) | 15-25+ (limited by demand) | **300-500% increase** |
| Response to small jobs (<€2K) | Often ignored | Profitable at any size | **New market access** |
| Quote accuracy (materials+labor) | Variable, often 10-20% off | Consistent, <5% variance | **3-4x accuracy** |
| Sales cycle (quote → acceptance) | 2-7 days | Same-day (with instant delivery) | **50-80% faster** |
| Revenue per tradesperson/year | €80-150K | €120-200K (more quotes → more wins) | **30-50% increase** |
| Admin overhead | 15-25h/week quoting | 1-2h/week reviewing | **90% reduction** |

## Implementation Path

### Phase 1: MVP (1-2 weeks)
- Focus on single trade: **painters** (simplest material calculation — paint per m²)
- Manual input form only (no photo parsing yet): room dimensions, paint type, finish, labor hours
- PDF generation with standard quote template
- WhatsApp bot for input and delivery
- Manual material price table (updated weekly via CSV)

### Phase 2: Expansion (2-4 weeks)
- Add **electricians** and **plumbers** — more complex material catalogs, position breakdowns
- Vision model: photo → quantity estimation for rooms and panels
- Live material price feeds from 2-3 wholesalers
- "Accept & Book" button that feeds into scheduling
- Add VOB/DIN compliance for quote sections

### Phase 3: Autonomy (4-8 weeks)
- All major trades: painting, electrical, plumbing, HVAC, carpentry, tiling
- Voice memo input (WhatsApp voice notes → quote)
- DATEV/Lexoffice direct integration
- Quote analytics: which trades get the most acceptances, typical markup optimization
- Multi-language quotes (German + Polish, Russian, Turkish for multilingual workforce communication)

## Risk & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Material data stale → incorrect quotes | High | High | Daily catalog sync cron; flag price confidence; allow manual override per item |
| Vision model misidentifies room dimensions | Medium | Medium | Confidence thresholds; if <80% confident, ask user for manual measurements |
| Customer accepts quote but job scope differs | Medium | High | Include disclaimer "based on provided description; on-site inspection may reveal additions"; tradesperson confirms before start |
| Regional Handwerk chambers require specific quoting formats | Medium | Low | Parameterize by Bundesland; agent checks state-specific requirements |
| Data privacy: customer photos contain sensitive info | Medium | Medium | Auto-delete photos after extraction; store only quote data (GDPR Art. 17 — right to erasure) |

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
- Actual time saved per quote (measured in field test with 5 Handwerk businesses)
- Quote acceptance rate change (before/after)
- Material cost accuracy (audit 50 quotes vs actual expenses)
- User satisfaction: tradesperson willingness to continue using the tool
