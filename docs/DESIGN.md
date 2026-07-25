# Automation Miner — Design (v4)

> Status: implementation contract. Supersedes the cognitive-skill spec in `docs/spec/`
> (which remains the domain logic reference: 4 phases, 5 layers, ICE scoring, filters).
> `docs/IMPROVEMENT-PLAN.md` records the v3 review this version answers, with the
> measurements behind each change.

## What it is

A headless engine that turns **any domain description** into a ranked portfolio of
**automation opportunity briefs** (AM-XXX), each scored with ICE and filtered into
action tiers. MCP-first (driven by the OpenClaw agent), with an equivalent CLI.
No TUI, no UI.

## Core commitments

1. **Structured outputs everywhere** — every agent returns JSON validated by pydantic.
   Parse failures retry with the validation error fed back (self-healing, max 3 tries).
2. **Multi-iteration quality loop** — every opportunity draft passes a critic agent
   scored on a rubric; below-threshold drafts are refined with the critique as input,
   up to N iterations (default 2). The loop record is persisted per opportunity.
3. **Deterministic scoring & filters** — ICE math, coherence validation, constraint
   overrides, ranking, and strategic filters run in code, not in the LLM.
4. **Role-based model routing** — each pipeline role maps to a provider/model, with
   per-role sampling and output limits.
5. **Artifacts as the source of truth** — every node writes JSON to the run directory,
   including `error.json` when a stage fails.
6. **Evidence grounding with provenance** — inputs of any size become a numbered,
   citable evidence index; each stage selects the slice relevant to its own question.
7. **Nothing is silently discarded** — unreadable files, filtered opportunities, and
   score adjustments are all recorded and reported.

## Pipeline (LangGraph)

```
ingest → domain_map → layer_analysis (×5 parallel)
       → draft_opportunities (×5 parallel, 1–2 opps each)
       → critique ⇄ refine (parallel over opportunities, loop until pass or max_iterations)
       → score (parallel; ICE proposal + deterministic validation)
       → rank_filter (deterministic) → publish (files + registry)
```

## Ingestion and context

### Readers (`automation_miner.readers`)

Every input file goes through a **reader**, which emits `Segment`s carrying a
`locator` in the format's own addressing. Built-in coverage:

| reader | formats | locator |
|--------|---------|---------|
| text | md, markdown, mdx, txt, rst, adoc, org, log, tex | heading path (`# A > ## B`) |
| json | json, jsonl, ndjson | key path / `records` |
| yaml | yaml, yml (multi-document) | `file.yaml doc 2` |
| csv | csv, tsv, psv | `rows 1-15`, `(profile)` |
| html | html, htm, xhtml | heading path |
| pdf | pdf | `p.4` |
| docx | docx | heading path, `table 2` |
| xlsx | xlsx, xlsm | `Sheet1!rows 2-13` |
| pptx | pptx | `slide 7` |

`pdf`, `docx`, `xlsx`, and `pptx` need optional extras (`uv sync --extra pdf`, or
`--extra readers` for all four). A reader whose dependency is missing reports that
fact with the install command; it is never silently skipped.

**Adding a format requires no change to this package.** Three routes, in increasing
priority:

1. Built-ins (priority 0).
2. An `automation_miner.readers` entry point from any installed distribution (10).
3. A `[[readers.custom]]` entry in `miner.toml` naming an importable factory (20).

A plugin that fails to import is recorded in `registry.errors` and reported; the run
still starts.

**Robustness rules.** Failures are per-file: a malformed `.json`, an encrypted PDF, an
oversized file, or an unsupported format is recorded in `ContextPacket.skipped` with a
reason, and ingestion continues. Unparseable JSON/YAML falls back to text extraction.
Encoding detection runs only above 1 KB, after strict UTF-8 and cp1252 — statistical
detectors mis-identify short latin-1 samples. Spreadsheets are profiled (row count,
column types, value sets, bounded row sample) rather than dumped. Known-binary
suffixes never reach the text fallback.

### Budget and evidence selection (`automation_miner.context`)

Reader segments become numbered `Chunk`s (`S1`, `S2`, …), split on paragraph and
sentence boundaries with overlap. The chunk list is the run's **evidence index**.

Each stage draws from that index with a deterministic BM25 query built from the
layer's own signal vocabulary, within its own token budget:

| budget | default tokens | used by |
|--------|---------------:|---------|
| `evidence_tokens` | 60,000 | the whole index ceiling |
| `map_tokens` | 24,000 | `overview` for domain mapping |
| `layer_tokens` | 16,000 | each layer analyst |
| `draft_tokens` | 16,000 | each drafter |
| `critique_tokens` | 10,000 | critique/refine, built once per opportunity |
| `score_tokens` | 3,000 | scorer |

All configurable under `[context]` in `miner.toml`. Relevance is lexical and pure
code — no embedding model, no network call, no run-to-run variation.

### Digesting (`automation_miner.digest`)

When the index exceeds `evidence_tokens`, chunks are batched and digested **toward a
stated target size** derived from the remaining budget, preserving source and locator.
Batches run in parallel and are cached by content hash under `<workspace>/.cache/digests`,
so re-mining the same knowledge base costs nothing. If the index is still over budget,
whole chunks are dropped from the tail — evidence is lost as complete, attributed units,
never as a severed sentence.

## Inputs

| Kind | CLI | Handling |
|------|-----|----------|
| Idea / domain string | `mine "German healthcare"` | Used directly as context |
| File | `mine --file brief.md` | Read via the matching reader; digested if over budget |
| Folder knowledge base | `mine --kb ./kb/` | All readable files enumerated; digested into a bounded evidence index |

Optional `--constraints "budget:low, team:3, compliance:heavy"` free-form string,
applied per the constraint rules in `docs/spec/01-SKILL.md`.

## Scoring

The LLM proposes Impact, Confidence, and Ease (1–5) **with one rationale per factor**.
Code then decides everything that affects the portfolio.

**Coherence validation.** Proposed factors are cross-checked against the draft's own
estimates, and adjustments are recorded on the opportunity:

| rule | effect |
|------|--------|
| effort High / Medium | Ease capped at 2 / 4 |
| impact_estimate Low / Medium | Impact capped at 2 / 4 |
| risk_level High | Confidence capped at 4 |
| no quantified impact rows | Confidence capped at 3 |
| no cited evidence | Confidence capped at 3 |
| cited ids absent from the index | flagged in `unresolved_refs` |

Adjustments **only ever lower** a factor. Where the model was more pessimistic than the
draft supports, the inconsistency is flagged and the score left alone, so nothing here
can inflate an ICE score.

**Constraint policy.** One parser (`ConstraintPolicy`) drives both score overrides and
portfolio filtering, so every policy that changes the outcome is also reported.

**Ranking.** Total ordering: ICE → impact → ease → confidence → critique → `am_id`
(Ease first when the timeline is urgent). Ties are the common case, so every one is
broken explicitly and ranking is reproducible.

**Eligibility.** Hard constraints mark opportunities `filtered` with
`exclusion_reasons` instead of deleting them. Filtered opportunities stay in
`scores.json`, `ranked.json`, and `summary.json` and are listed in the report; only
published ones become briefs.

**Tiers.** `vision` ≥ 80, `high` 60–79, `medium` 40–59, `low` < 40 — surfaced in the
brief frontmatter, report, summary, and registry.

## Outputs (workspace layout)

```
<workspace>/
├── .am-counter                    # monotonic AM-ID allocation watermark
├── .cache/digests/                # content-hashed KB digests
├── registry.json                  # machine index, rebuilt by `reindex`
├── runs/
│   └── YYYY-MM-DD_<domain-slug>/
│       ├── run.json               # manifest: input, config, models, usage, stage timings
│       ├── run.md                 # human run log (spec 07 template)
│       ├── summary.json           # compact agent-facing view
│       ├── context.json           # evidence index + skipped files + context stats
│       ├── domain_map.json
│       ├── layers/<layer>.json    # 5 layer analyses
│       ├── drafts/<layer>.batch.json # raw per-layer draft batches
│       ├── drafts/AM-XXX.v{n}.json   # every draft + critique iteration
│       ├── scores.json            # validated pre-policy portfolio
│       ├── ranked.json            # ranked portfolio with eligibility + stats
│       ├── opportunities.json     # final portfolio + filters
│       ├── report.md              # metadata, tiered ranking, exclusions, cost
│       └── error.json             # only on failure: stage, error, artifacts written
└── opps/
    └── <domain-slug>/
        └── AM-XXX-<slug>.md       # self-contained brief, YAML frontmatter
```

AM-XXX numbering is global and sequential, continuing from the current registry max
(existing corpus ends at AM-377). Domain slugs per spec rules.

`summary.json` exists because an agent driving `mine_domain` should not have to choose
between parsing markdown and loading every full draft. It carries portfolio stats,
context stats, token usage, and one row per opportunity, and is returned inline by MCP.

Briefs render a **Scoring & Confidence** section (per-factor rationale, tier, critic
score, iterations, calibrations, overrides) and an **Evidence** section listing cited
chunk ids, flagging any that did not resolve.

## Reliability and cost

- **Retries.** Transient statuses (408, 409, 425, 429, 5xx) and network errors back off
  exponentially with jitter, honouring `Retry-After`. Non-retryable statuses fail fast.
- **Per-role limits.** `temperature` and `max_tokens` per role; the drafter and refiner
  get 16k output because they emit a full draft with two tables.
- **JSON mode** requested where the provider advertises support.
- **Parallel stages.** Critique/refine and scoring fan out over a bounded thread pool.
  AM-ids are reserved before fan-out and results re-ordered deterministically.
- **Telemetry.** Calls, retries, failures, and prompt/completion tokens per role, exact
  when the provider reports `usage` and estimated otherwise, in `run.json`, `summary.json`,
  the report, and the CLI.

## Known limitation

Runs are not automatically resumable. A resume API needs an explicit checkpoint
compatibility policy, stable draft-to-AM-ID allocation, and idempotent publication.
Until that contract is defined, failed runs restart from their original input; their
completed stage artifacts and `error.json` remain available for diagnosis.

## MCP tools (stdio server, `automation-miner-mcp`)

- `mine_domain(input, input_type=auto|idea|file|kb, constraints="", profile="default", max_iterations=2, dry_run=false)` → run summary inline + artifact paths
- `list_runs()` / `list_domains()`
- `get_opportunity(am_id)` → full brief
- `query_registry(layer?, min_ice?, status?, domain?)` → filtered entries
- `get_run_report(run_id)` → report.md content
- `get_run_summary(run_id)` → summary.json
- `list_readers()` → formats handled and dependency availability
- `reindex()` → rebuild registry.json
- `server_info()` → version, active model routing, workspace path

## CLI (`automation-miner`)

- `mine <idea> | --file F | --kb DIR [--constraints S] [--iterations N] [--profile P] [--workspace DIR] [--dry-run] [--json]`
- `reindex [--workspace DIR]`
- `list [--layer L] [--min-ice N] [--tier T] [--status S] [--domain D] [--json]`
- `show AM-XXX`
- `report RUN_ID` / `summary RUN_ID`
- `readers [--json]`
- `--version`

`--dry-run` uses the mock model: zero cost, deterministic, for tests and demos.

## Configuration (`miner.toml` in workspace or `~/.config/automation-miner/`)

```toml
[providers.openrouter]
base_url = "https://openrouter.ai/api/v1"
api_key_env = "OPENROUTER_API_KEY"
supports_json_mode = true

[roles]
mapper        = { provider = "openrouter", model = "anthropic/claude-sonnet-4" }
layer_analyst = { provider = "openrouter", model = "anthropic/claude-sonnet-4" }
drafter       = { provider = "openrouter", model = "anthropic/claude-sonnet-4", max_tokens = 16000 }
critic        = { provider = "openrouter", model = "openai/gpt-4.1" }
refiner       = { provider = "openrouter", model = "anthropic/claude-sonnet-4" }
scorer        = { provider = "openrouter", model = "openai/gpt-4.1", temperature = 0.1 }

[context]
evidence_tokens = 60000
layer_tokens    = 16000

[readers]
max_file_bytes = 20000000
disabled = []

[readers.csv]
sample_rows = 20

[[readers.custom]]
suffixes = [".rtf"]
factory = "my_pkg.readers:RtfReader"

[retry]
attempts = 4
max_seconds = 30

[concurrency]
critique = 4
score = 4
```

Env overrides: `MINER_MODEL_<ROLE>`, `MINER_MODEL` (all roles), `MINER_PROVIDER`.
A `[profiles.<name>]` table may override `roles`, `context`, `readers`, `retry`, and
`concurrency`.

## Quality rubric (critic, 0–10 weighted)

groundedness (25%) — every claim traces to a cited evidence id, or is flagged as inference
specificity (20%) — named systems, actors, volumes; no generic filler
quantified_impact (20%) — time/cost/error numbers with assumptions
feasibility (15%) — realistic effort, dependencies, integration path
hitl_clarity (10%) — explicit human review points and escalation
differentiation (10%) — not a duplicate of another opp in the same run

Pass threshold: 7.5. Below → refine with critique. Persist all iterations.

## Stack

Python ≥3.12, uv, langgraph, pydantic v2, pyyaml, httpx, mcp (optional extra),
pypdf / python-docx / openpyxl / python-pptx (optional reader extras).
Dev: pytest, ruff. Tests run fully offline against the mock model.
