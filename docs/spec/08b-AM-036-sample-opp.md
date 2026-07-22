---
am-id: "AM-036"
title: "Unified Barrel ID & Digital Cellar Map"
domain: "Wine Cellar Inventory & Maturation Tracking"
layer: "document"
status: "identified"
ice-score: 100
impact: 5
confidence: 5
ease: 4
created: "2026-05-02"
updated: "2026-05-02"
source: "2026-05-02_wine-cellar-inventory"
tags: [automation, wine, cellar, inventory, barrel, viticulture, document, qr-code, rfid, cellar-map, mobile-app, data-integration, traceability, german-wine, kellerbuch]
---

# AM-036: Unified Barrel ID & Digital Cellar Map

## Problem Statement

Every small-to-medium German wine cellar (500-5000 barrels) suffers from the same core inventory problem: **there is no single source of truth for what is in which barrel, where that barrel is, and what its current status is.**

The current state is a patchwork:
- Barrels are identified with chalk markings on the barrel head (weathered, illegible, washed off during cleaning)
- Barrel positions are tracked on paper maps or in the cellar master's head ("the 2021 Riesling Trocken is in the third row, second tier, about halfway down, next to the big foudre")
- Fill level is estimated by knocking on barrels and listening to the sound, or peering through the bung hole with a flashlight
- Topping history is recorded in paper notebooks (or not recorded at all)
- SO₂ additions are logged separately (lab report + cellar master's notes)
- Tasting notes live in the winemaker's notebook or a separate digital file
- The cellar book (mandatory regulatory traceability per Weingesetz §13-15) is maintained in a separate system and often incomplete because it depends on data that isn't captured systematically

**Concrete impacts:**
- Cellar workers waste 15-30 minutes per shift locating specific barrels for tasting, topping, or racking. At 2-5 workers × 1 shift/day × 300 days/year = 150-750 hours/year lost to barrel hunting (€4,500-22,500/year in labor cost).
- Data entry is duplicated 2-3× per event (topping → notebook + cellar book + potentially spreadsheet). Prone to transcription errors.
- Misidentified barrels happen 5-10× per year — topping the wrong barrel, missing a barrel for tasting, or worst case, blending the wrong barrel into a lot.
- When the cellar master is unavailable (sick, vacation, retired), nobody else knows where anything is. Institutional knowledge walks out the door with every shift change.
- Annual compliance audits require tracing every barrel's history — currently a multi-day manual exercise involving cross-referencing paper notes, spreadsheets, and cellar book software.

## Proposed Automation

A digital barrel registry with a companion mobile app that gives every barrel a unique, durable identifier (RFID tag + UV-resistant QR barcode on barrel head or stave) — mapped to a precise 3D position in the cellar. Workers scan a barrel to see its full history, log events in real-time, and navigate the cellar with an interactive map. The system becomes the single source of truth for all barrel-level data, which feeds every other automation (SO₂ management, topping dispatch, blending, cellar book generation).

### Core capabilities:
- **Barrel registration**: Each barrel gets a unique ID linked to RFID tag and/or QR barcode. Tags must withstand barrel washing (high-pressure water, SO₂ cleaning), cellar humidity (60-90% RH), and temperature (8-18°C).
- **3D cellar mapping**: Cellar layout is digitized as a map with rows, tiers, and blocks. Barrel position is recorded and updated when barrels move. Searchable by wine, vintage, variety, vineyard, toast level, barrel age, fill level, and position.
- **Mobile scanning**: A mobile app (iOS/Android) lets cellar workers scan a barrel's QR/RFID to view current status, log topping events, record SO₂ additions, enter tasting notes, and note observations. Works offline in deep cellars with no connectivity; syncs when signal returns.
- **Fill level tracking**: Workers log fill level as a percentage (or exact volume) when scanning. Historical trend line shows ullage rate per barrel over time — identifies barrels with excessive evaporation (possible stave damage) or suspiciously low evaporation (possible leak).
- **Event log**: Every interaction with a barrel is timestamped and attributed to the worker. Creates a complete audit trail: when was it topped, by whom, how much SO₂ added, when was it tasted, what was the score.
- **Search & navigation**: "Show me all 2021 Riesling Spätlese barrels in Row C" with an on-map overlay. "Navigate to barrel C-3-12" with visual guidance (row number, tier).
- **Bulk operations**: Select barrels by filter (e.g., "all 2020 Chardonnay barrels with fill <85%") and batch-update status or schedule topping.
- **Barrel lifecycle management**: Track barrel age (vintage of barrel itself — new, 1-year, 2-year, neutral), toast level (light, medium, medium-plus, heavy), barrel type (barrique, tonneau, foudre, demi-muid), and cooper.
- **Integration hooks**: API for every other automation system — SO₂ advisor (AM-038) reads SO₂ history per barrel, blend optimizer (AM-041) reads inventory and allocation status, cellar book automator (AM-042) reads all events for compliance reporting.

## Process Details

### Inputs
- Barrel inventory data (existing spreadsheets, cellar book software exports, or manual entry during setup)
- Cellar map/layout (can be drawn from floor plan, or built incrementally as barrels are tagged)
- Worker interactions via mobile app (scans, tap events, form entries)
- Fill level readings (manual entries during topping/sampling rounds)
- Tasting notes and scores (structured forms + free text)
- SO₂ additions (amount, method, date)
- Barrel movements (from position A to position B, with date and reason)

### Steps
1. **Setup phase**: 
   - Purchase RFID tags + QR labels (weatherproof, UV-resistant, < €2/barrel in bulk)
   - Print and attach to each barrel (staves on the visible end, not the bung end)
   - Walk through cellar with a mobile device, scan each barrel's tag, record position + initial data (wine, vintage, variety, vineyard, toast level, barrel age, cooper, fill level)
   - Import historical data from existing spreadsheets/notebooks (1-3 days of work for 1000-barrel cellar)
2. **Daily operations**:
   - Worker scans barrel before topping → app shows last topping date, amount, current fill level
   - Worker enters new fill level, topping volume, any observations
   - Worker scans barrel before SO₂ addition → app shows last free SO₂ level, recommended addition from AM-038
   - Worker scans barrel before tasting → app shows last tasting note, score trend, needs-assessment label
3. **Search & navigation**:
   - Worker types "2021 GG Spätburgunder" → map highlights barrels, shows fill levels and last topping date
   - Worker taps barrel → full history including all events
4. **Reporting**:
   - Daily: "Barrels needing topping today" (sorted by position for efficient route)
   - Weekly: "Barrels below 70% fill" (urgent topping needed)
   - Monthly: "Barrel fill rate trends" (ullage by row, by barrel type, by age)
   - On demand: "Traceability report for Barrel X" (complete event history)

### Outputs
- Per-barrel: full digital profile with event history, fill level trend, SO₂ trend, tasting score trend
- Cellar map: searchable, filterable, navigable visual layout
- Daily/weekly worklists: topping rounds sorted by urgency and route efficiency
- Inventory reports: wine-by-vintage summaries, barrel utilization, empty barrels ready for next harvest
- Audit trail: complete traceability from harvest to bottling for every barrel, regulatory-compliant

### Human-in-the-Loop Points
- **Data entry**: Workers must scan barrels and enter data — this is a behavior change. The app must be fast enough (<10 seconds per event) that it saves time rather than adds friction.
- **Barrel movement**: When a barrel is moved (racking, reorganisation), position must be updated in the system.
- **Fill level estimation**: Fill level is manually estimated (or measured with a measuring stick through the bung hole). Automated fill level sensors are a future enhancement.
- **Data validation**: A cellar master reviews bulk operations before they're finalized (e.g., "transfer all allocated barrels to blending tank").
- **Offline mode**: Cellars often have poor connectivity. The app must work fully offline and sync later. Workers must understand that synced data is the "true" record.

## Feasibility Assessment

### Technical Requirements
- **Mobile app**: Cross-platform (iOS/Android) with offline support, camera for QR scanning, optional NFC/RFID reader. Use Flutter or React Native.
- **Backend**: Cloud or on-premise database (PostgreSQL, TimescaleDB for time-series barrel events). Consider on-premise for wineries with data sovereignty concerns.
- **RFID infrastructure**: For RFID approach, workers need NFC-enabled phones or dedicated RFID readers. QR-only is simpler but requires direct line-of-sight (barrels in tight rows may be hard to scan).
- **Tag durability**: UV-stable polyester labels with permanent adhesive (Avery Dennison or similar withstands barrel washing). RFID tags need to be IP68 rated for wet cellar environments. Budget €1.50-3.00 per barrel for labels/installation.
- **Map input**: Cellar floor plan as SVG/GeoJSON or defined through a web interface where you click to place barrel positions.
- **API layer**: REST/GraphQL API for integration with other systems (SO₂ advisor, blending tool, cellar book).

### Dependencies
- Barrel inventory data must exist in some structured form (even a basic spreadsheet) to make setup feasible — manually entering 500+ barrels from scratch is impractical
- Mobile devices for cellar workers (dedicated rugged tablets or workers' personal phones with a dedicated app)
- Willingness to adopt scanning workflow (behavior change from "chalk and memory" to "scan and tap")

### Constraints
- Cellar environment is wet, dark, cold (8-18°C), and high humidity (60-90% RH). QR codes on dirty/weathered barrels may not scan reliably — RFID is more robust for this environment.
- Deep cellars have limited to no mobile connectivity. The app MUST work fully offline with reliable sync.
- Barrel washing with high-pressure hose and SO₂ solutions will degrade labels over time. Expect 12-24 month label replacement cycle.
- Some wineries have 200+ year old cellars where attaching tags to historic barrels is culturally inappropriate. A visual-only workflow (no tags, navigate by position-on-map) needs to be an option.
- EU data sovereignty: some wineries will want on-premise hosting for their cellar data.

## Impact Analysis

| Dimension | Current State | Automated State | Improvement |
|-----------|--------------|----------------|-------------|
| Barrel location time | 15-30 min/shift per worker | 30 seconds/barrel scan | 95%+ reduction |
| Data duplication | 2-3× per event | 1× per event (scan + tap) | 60-70% reduction |
| Lost barrels (not found for topping) | 3-5% of barrels/month | <0.5% | 80-90% reduction |
| Compliance audit preparation | 2-3 days of cross-referencing | 15 min automated report | 90%+ reduction |
| Cellar worker onboarding time | 3-6 months to learn cellar layout | 1-2 weeks with digital map | 80% reduction |
| Fill level tracking accuracy | Visual estimate ±10% | Documented ±2% (measuring stick) | 5× accuracy improvement |
| Labor cost (hunting barrels) | €4,500-22,500/year | <€500/year (residual) | €4,000-22,000 saved/year |

## Implementation Path

### Phase 1: MVP (1-2 weeks)
- Choose a target cellar section (50-100 barrels, e.g., a single row of premium barrels)
- Print QR labels, attach to barrel heads
- Build a minimal mobile app: scan QR → show barrel profile (wine, vintage, fill level, last topping date) → allow topping and fill level entry
- Basic search by wine name
- Manual map overlay (photos of the row with barrel IDs annotated)
- Test for 2 weeks with lead cellar worker to validate the workflow

### Phase 2: Expansion (3-4 weeks)
- Roll out tags to all barrels in the cellar (500-5000)
- Build the full 3D cellar map interface (rows, tiers, blocks)
- Add bulk operations (filter, batch-update)
- Add search by all attributes (variety, vintage, vineyard, toast level, fill level threshold)
- Add event history view per barrel
- Build offline-first sync (PouchDB/CouchDB or WatermelonDB)
- Add API for integration (starts feeding other automation systems)
- Daily topping round generation (sorted by route efficiency)

### Phase 3: Autonomy (4-8 weeks)
- Add RFID support (NFC phones or dedicated readers) for faster scanning in low-light conditions
- Add smart bung integration (optional, partner with barrel sensor manufacturers for automatic fill level + temperature)
- Predictive fill level estimation: "Barrel C-3-12 will reach 75% fill in approximately 3 weeks based on its evaporation rate. Schedule topping for week of 23 May."
- Historical data mining: "This row of new barrels evaporates 15% faster than Row D of 3-year-old barrels" (benchmarking for barrel purchase decisions)
- Advanced barrel lifecycle decision support: "These 5 barrels are at end of useful life (6+ years old). Recommend retiring before next vintage."
- Integration with CRM/sales system: "Barrel B-7-3 contains the 2021 Riesling that is allocated to Export Order #42"

## Risk & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Cellar workers resist scanning workflow | High | Medium (system unused) | Gamification + show time saved. Initial pilot with motivated worker. Phase: scan-for-topping first, expand. Must save time, not add friction. |
| QR code degradation (washing, humidity) | High | Medium (re-tagging cost) | Use polyester UV-resistant labels, test durability before full rollout. Plan 12-month replacement cycle. RFID as backup for frequently washed barrels. |
| Cellular connectivity in deep cellar | High | High (data loss, sync issues) | Offline-first architecture mandatory. Sync when worker returns to surface. Conflict resolution strategy for concurrent offline edits. |
| Barrel history migration takes too long | Medium | Medium (setup friction) | Phased rollout: tag and map rows gradually. Use existing spreadsheet data as starting point. Accept incomplete history for barrels in later phases. |
| RFID tags interfere with metal barrels/foudre bands | Low-Medium | Medium (inconsistent reads) | Test RFID on representative barrels. QR as fallback for hard-to-read metal-adjacent positions. |
| Workers forget to update fill level after topping | Medium | Low (data staleness) | Default to "topping completed" auto-update of fill level based on typical topping volume. Workers can override. Training + nudge reminders. |
| Cost/barrel too high for small cellars | Medium | High (no adoption) | Free-tier: QR-only with manual position entry. $0.50/barrel label investment. Paid upgrade for RFID + automatic fill sensors. Price sensitivity drives phased feature access. |

---

## Self-Improvement

- [x] **Identified** — opportunity brief created
- [ ] **Validated** — domain expert confirmed problem/relevance
- [ ] **Designed** — implementation plan complete
- [ ] **Built** — prototype or MVP shipped
- [ ] **Measured** — actual impact vs. projected impact
- [ ] **Lessons learned** — what did the miner get right/wrong?

Validation criteria:
- Time spent locating barrels (target: <5 min/barrel vs. current 15-30 min)
- Data entry duplication reduction (target: single entry per event)
- Compliance audit time (target: <1 hour vs. current 2-3 days)
- Worker adoption rate (target: >80% of topping/tasting events logged through system after 1 month)
