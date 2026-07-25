# Automation Miner — Improvement Plan (v4)

> Review of the v3 LangGraph implementation at `341290e`, with measured findings and a
> phased implementation plan. Focus areas: **context management**, **scoring**,
> **output format**, plus the reliability/cost work that makes the first three usable
> on real (non-mock) runs.

---

## 1. Measured findings

All numbers below were reproduced against the current code on this branch.

### 1.1 Context management — the weakest area

| # | Finding | Evidence |
|---|---------|----------|
| C1 | **KB digest has no size target.** A 49k-char / 8-file KB collapses to **1,894 chars** — 96% of the evidence is gone, and 95% of the 40k budget is left unused. `digest_prompt` never states a target length, so compression ratio is whatever the model feels like. | 8 files × ~6.1k chars → `context.content` = 1,894 chars |
| C2 | **`--file` input has no digest path at all.** A 220k-char brief is hard-cut to 40k (18% kept), mid-sentence, mid-section. Only a boolean `truncated: true` records the loss. | tail of kept content: `"...process 558 with"` |
| C3 | **Budget is char-based, not token-based**, and named `TOKEN_BUDGET_CHARS`. 40k chars ≈ 10k tokens — a tiny fraction of the 200k–1M windows the routed models actually have. Large KBs are destroyed for no reason. | `ingest/__init__.py:22` |
| C4 | **JSON/YAML sources are re-serialized with `indent=2`**, nearly doubling their char cost. A 14.3k-char JSON file consumes 27.9k of budget as whitespace. | 14,303 → 27,911 chars |
| C5 | **Fixed-offset chunking with no overlap and no structure awareness.** `DIGEST_CHUNK_CHARS = 12_000` slices mid-sentence and mid-table; facts straddling a boundary are mangled. | `ingest/__init__.py:127-130` |
| C6 | **Every downstream stage gets the same undifferentiated blob.** The `document` layer analyst receives identical context to `knowledge`. No per-layer relevance selection, so budget is spent on irrelevant evidence and signal is diluted. | `build.py:103, 138, 167` |
| C7 | **Evidence is re-sent unbounded, per opportunity, per round.** `critique_refine_node` rebuilds `ctx.content + domain_map` for *every* critique and *every* refine call. Measured: **29 model calls / 163,523 prompt chars (~41k tokens)** for one 8-file KB dry run. With 10 opportunities × 2 rounds on real models this is the dominant cost line. | `build.py:167` |
| C8 | **Digests lose provenance.** File labels survive the map step but are replaced by `digest reduction 1.1` in reduce rounds. `groundedness` is the highest-weighted rubric dimension (25%) yet the critic has no way to trace a claim to a source. | `ingest/__init__.py:141-143` |
| C9 | **No digest caching.** Re-running the same KB re-pays every map call (8 of the 29 calls above). | — |
| C10 | Unsupported files (`.pdf`, `.docx`, `.csv`) are silently skipped — no count, no warning. No per-file size cap, so one huge file can exhaust memory. | `ingest/__init__.py:99-102` |
| C11 | `context.json` records only `digested`/`truncated` booleans — no input size, output size, compression ratio, or per-file accounting. | `schemas/__init__.py:65-76` |

### 1.2 Scoring

| # | Finding | Evidence |
|---|---------|----------|
| S1 | **The deterministic validation layer is dead code.** `calibrate()` clamps to 1–5, but `ICEScore` already declares `Field(ge=1, le=5)`, so pydantic rejects out-of-range values before `calibrate()` ever sees them. The documented "LLM proposes, code validates" contract currently validates **nothing**. | `ICEScore(impact=9, ...)` → `ValidationError` |
| S2 | **Two divergent constraint parsers.** `rank()` uses `parse_constraint_policy()` (regex); `apply_constraint_overrides()` uses its own substring checks. Result: `budget: zero`, `no budget`, `agent_limit: 3`, `team:3`, and `timeline: tight` all silently reshape the published portfolio while producing **zero** entries in `overrides_applied` — so `run.md`'s "Notes & Observations" never mentions them. `agent limit: 3` and `agent_limit: 3` behave differently. | see table in §1.4 |
| S3 | **`rank()` silently destroys paid-for work.** Hard filters drop opportunities that were fully drafted, critiqued, refined *and* scored. Measured on a 6-opportunity pool: `urgent` → 3 survive, `budget: low` → 2 survive. The other 4 never reach `opportunities.json`, briefs, or the registry, and nothing tells the operator they existed. | `scoring/__init__.py:135-162` |
| S4 | **Tie ordering is arbitrary.** Equal ICE resolves by upstream insertion order — a 3-way tie ranked `AM-009, AM-007, AM-008`. Ties are the common case, not the exception: the mock smoke run produces five opportunities all at ICE 64. | `rank()` single-key sort |
| S5 | **No score explainability.** One `rationale` paragraph covers all three factors, so you cannot audit *why* Ease = 4. No cross-check that the factors agree with the draft's own `effort` / `impact_estimate` / `risk_level` (High effort + Ease 5 is incoherent and currently accepted). | `schemas/__init__.py:195-205` |
| S6 | **`agents_required` is free text parsed by regex.** `_agent_count()` takes the first integer it finds: `"agent with 2 sub-agents"` → 2 (actually 3); `"2-3 agents"` → 2. This heuristic gates the `agent_limit` portfolio filter. | `scoring/__init__.py:166-168` |
| S7 | ICE tiers exist in `registry.json` (`vision_80plus` … `low_under_40`) but are never surfaced in any human-facing output. | `registry.py:19` |

### 1.3 Output format

| # | Finding |
|---|---------|
| O1 | **`report.md` is a bare table plus three lists.** No domain, date, run id, constraints, opportunity count, tier labels, excluded items, portfolio shape, or recommended starting sequence. |
| O2 | **No compact machine-readable summary.** MCP `mine_domain` returns am-ids and paths; a driving agent must then either parse markdown or load the full `opportunities.json` (every draft, every table). There is no middle artifact. |
| O3 | **Briefs hide the quality signal.** `critique_overall`, `iterations`, `overrides_applied`, and the score rationale are all computed and persisted, then never rendered. The published brief cannot justify its own ICE score. |
| O4 | **No cost or token telemetry anywhere.** `run.json` records duration but not calls, tokens, or estimated spend — for a pipeline that makes ~30–60 LLM calls per run. |
| O5 | CLI `mine` prints id/ICE/layer/title only: no tier, no critique score, no cost, no note of what was filtered out. `list` has no `--json`; there is no `--version`. |

### 1.4 Constraint-parser divergence (S2), measured

| constraints string | affects `rank()` | recorded in `overrides_applied` |
|---|---|---|
| `budget: low` | yes (Ease ≥ 4) | — |
| `budget: zero` | yes (Ease ≥ 4) | **no** |
| `no budget` | yes (Ease ≥ 4) | **no** |
| `agent limit: 3` | yes (cap 3) | yes |
| `agent_limit: 3` | yes (cap 3) | **no** |
| `team:3` | yes (cap 2) | **no** |
| `timeline: tight` | yes (top-3, Ease-first) | **no** |
| `urgent` | yes (top-3, Ease-first) | yes |

### 1.5 Reliability and cost

| # | Finding |
|---|---------|
| R1 | **`critique_refine_node` and `score_node` are fully sequential.** 10 opportunities × 2 rounds ≈ 40 serial HTTP calls; at 10–30 s each that is 7–20 minutes of wall clock per run. |
| R2 | **No retry or backoff on HTTP.** Any `httpx.HTTPError` — including a single 429 or 503 — aborts the run immediately, after potentially 25 already-paid calls. |
| R3 | `temperature=0.3` and `max_tokens=8192` are hardcoded for every role. The drafter emits a full `OpportunityDraft` with two tables; a truncated completion becomes unparseable JSON, burns 3 retries, then hard-fails. |
| R4 | `response_format: {"type":"json_object"}` is never requested, although every `call_json` wants exactly that and OpenAI-compatible endpoints support it. |
| R5 | **A failed stage leaves no failure artifact.** If `domain_map` raises, the run directory holds `context.json` and nothing explaining the failure — contradicting "artifacts as the source of truth". |

---

## 2. Implementation plan

### Phase 1 — Context management

New module `src/automation_miner/context.py` owning all budget and evidence logic.

1. **Token-aware budget model.** `ContextBudget` with a calibrated token estimator
   (chars/4 with CJK correction), per-stage budgets (`map`, `layer`, `draft`,
   `critique`, `score`), and model-aware defaults raised well above today's 40k chars.
   Configurable via `[context]` in `miner.toml`. *(C3)*
2. **Structure-aware chunking with stable source ids.** Split on markdown headings and
   paragraph boundaries with a configurable overlap; assign every chunk a stable
   `[S<n>]` id carrying its origin file and heading path. *(C5, C8)*
3. **Digest with an explicit size target.** `digest_prompt` states a target character
   budget per chunk and the reduce loop digests *toward* the budget instead of as small
   as possible, with a floor so a digest can never silently discard 96% of the input.
   Source ids are preserved through every reduce round. *(C1, C8)*
4. **Oversize `file` and `idea` inputs route through the same digest path**; when a hard
   truncation is genuinely unavoidable it happens at a section boundary, never
   mid-sentence. *(C2)*
5. **`EvidencePack` builder — per-layer relevance selection.** A deterministic lexical
   scorer (BM25-lite over the layer's signal vocabulary, pure code, no embeddings
   dependency) ranks chunks per layer and per draft, so each stage receives its
   most-relevant excerpts within its own budget instead of one shared blob. *(C6, C7)*
6. **Bounded evidence for the critique/refine/score stages** — the largest single cost
   line — built once per opportunity and reused across rounds. *(C7)*
7. **Content-hash digest cache** under `<workspace>/.cache/digests/`. *(C9)*
8. **Compact JSON/YAML serialization**, per-file size cap, and skipped-file reporting. *(C4, C10)*
9. **`ContextStats`** on the packet: source chars, packet chars, estimated tokens,
   compression ratio, files included/skipped/digested, budget utilization — persisted in
   `context.json` and surfaced in `run.md`. *(C11)*

### Phase 2 — Scoring

10. **One constraint parser.** `apply_constraint_overrides()` consumes `ConstraintPolicy`;
    every policy that changes the portfolio records a human-readable entry. *(S2)*
11. **Real deterministic validation** replacing the no-op `calibrate()`: coherence checks
    between the LLM's ICE factors and the draft's own `effort`, `impact_estimate`, and
    `risk_level`, with each adjustment recorded and rendered. *(S1, S5)*
12. **Per-factor rationale** on `ICEScore` (`impact_rationale`, `confidence_rationale`,
    `ease_rationale`). *(S5)*
13. **Structured agent topology** — `agent_count: int` + `topology: str` on the draft,
    replacing regex-over-prose. *(S6)*
14. **Deterministic tiebreak ranking**: ICE → impact → ease → confidence →
    critique_overall → am_id, so equal-ICE ordering is stable and reproducible. *(S4)*
15. **`Tier` enum** (`vision` ≥ 80, `high` 60–79, `medium` 40–59, `low` < 40) applied
    consistently across brief frontmatter, report, summary, and registry. *(S7)*
16. **Eligibility instead of silent deletion.** Every scored opportunity is retained with
    `eligibility` (`published` / `filtered`) and `exclusion_reasons`. Filtered items stay
    in `scores.json` and `summary.json` and are listed with their reason in the report;
    only eligible ones become briefs. *(S3)*
17. **Portfolio statistics** — per-layer counts, ICE distribution, tier counts, filter
    membership — computed in code.

### Phase 3 — Output format

18. **`report.md` v2**: metadata header (domain, run id, date, constraints, models),
    executive summary, tiered ranking table, portfolio shape, strategic filters,
    excluded-with-reasons section, recommended first-three sequence, and context notes. *(O1)*
19. **Brief v2**: a "Scoring & Confidence" section (per-factor rationale, ICE, tier,
    critique score, iterations, applied overrides) and an "Evidence" section listing the
    `[S<n>]` sources the opportunity draws on. *(O3)*
20. **`summary.json`** — compact agent-facing artifact (id, title, layer, ICE, factors,
    tier, filters, eligibility, one-line problem), returned inline by MCP `mine_domain`
    and exposed via a new `get_run_summary` tool. *(O2)*
21. **Usage and cost telemetry.** `UsageTracker` on `MinerModel` accumulating calls,
    retries, prompt/completion tokens (provider `usage` when returned, estimate
    otherwise) per role → `run.json` + CLI + `summary.json`. *(O4)*
22. **CLI polish**: richer `mine` summary (tier, critique, filtered count, cost),
    `--json` on `mine`/`list`, `--version`. *(O5)*

### Phase 4 — Reliability and cost control

23. **Parallel critique/refine and scoring** via a bounded thread pool with
    deterministic result re-ordering (AM-ids are reserved before fan-out, so ids stay
    stable). Concurrency configurable, default conservative. *(R1)*
24. **Retry with exponential backoff and jitter** on 429/5xx/timeouts, honouring
    `Retry-After`. *(R2)*
25. **Per-role `temperature` / `max_tokens` in `miner.toml`**, with drafter/refiner
    defaults raised. *(R3)*
26. **Opt-in JSON mode** per provider (`supports_json_mode`). *(R4)*
27. **`error.json` on stage failure** — stage, exception, partial artifact list. *(R5)*

---

## 3. Compatibility

- Brief frontmatter changes are **additive** (`tier`, `critique`, `iterations`), so the
  existing corpus (ends at AM-377) still reindexes; `registry.json` stays at `v2` shape
  with new optional keys.
- Per-run JSON artifacts (`scores.json`, `ranked.json`, `opportunities.json`) change
  shape. They are per-run and not read back by any command, so this is safe. `summary.json`
  is new.
- `ICEScore` and `OpportunityDraft` gain required fields, so the mock provider and prompt
  templates move together; `PROMPT_VERSION` bumps to `2.0`.
- No CLI or MCP tool is removed; `get_run_summary` is added.
