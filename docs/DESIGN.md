# Automation Miner — Design (v3, LangGraph Rebuild)

> Status: implementation contract. Supersedes the cognitive-skill spec in `docs/spec/`
> (which remains the domain logic reference: 4 phases, 5 layers, ICE scoring, filters).

## What it is

A headless engine that turns **any domain description** into a ranked portfolio of
**automation opportunity briefs** (AM-XXX), each scored with ICE and filtered into
action tiers. MCP-first (driven by the OpenClaw agent), with an equivalent CLI.
No TUI, no UI.

## Improvements over the v1 cognitive skill and the film-pipeline learnings

1. **Structured outputs everywhere** — every agent returns JSON validated by pydantic.
   Parse failures retry with the validation error fed back (self-healing, max 3 tries).
2. **Multi-iteration quality loop** — every opportunity draft passes a critic agent
   scored on a rubric; below-threshold drafts are refined with the critique as input,
   up to N iterations (default 2). The loop record is persisted per opportunity.
3. **Deterministic scoring & filters** — ICE math, bound checks, calibration rules,
   constraint overrides, and strategic filters run in code, not in the LLM. The LLM
   proposes scores *with rationale*; code validates and computes.
4. **Role-based model routing** — each pipeline role (mapper, layer_analyst, drafter,
   critic, refiner, scorer) maps to a provider/model via config. Multi-provider:
   OpenRouter, Google Gemini, any OpenAI-compatible endpoint, plus a deterministic
   mock for tests.
5. **Artifacts as the source of truth** — every node writes JSON artifacts to the run
   directory. They provide durable stage output and failure diagnosis without
   LangGraph checkpointer complexity.
6. **Evidence grounding** — inputs of any size (one-liner → full knowledge-base folder)
   are normalized into a context packet with a token budget; large KBs are digested
   map-reduce style so quality does not collapse on big inputs.

## Pipeline (LangGraph)

```
ingest → domain_map → layer_analysis (×5 parallel)
       → draft_opportunities (×5 parallel, 1–2 opps each)
       → critique ⇄ refine (loop until pass or max_iterations)
       → score (ICE proposal + deterministic validation)
       → rank_filter (deterministic) → publish (files + registry)
```

## Inputs

| Kind | CLI | Handling |
|------|-----|----------|
| Idea / domain string | `mine "German healthcare"` | Used directly as context |
| File (md/txt/json/yaml) | `mine --file brief.md` | Read, parsed, used as context |
| Folder knowledge base | `mine --kb ./kb/` | All supported files enumerated; digested into a bounded context packet (map-reduce summaries if over budget) |

Optional `--constraints "budget:low, team:3, compliance:heavy"` free-form string,
applied per the constraint rules in `docs/spec/01-SKILL.md`.

## Outputs (workspace layout, v2 partitioned)

```
<workspace>/
├── .am-counter                    # monotonic AM-ID allocation watermark
├── registry.json                  # machine index, rebuilt by `reindex`
├── runs/
│   └── YYYY-MM-DD_<domain-slug>/
│       ├── run.json               # manifest: input, config, models, iterations, timing
│       ├── run.md                 # human run log (spec 07 template)
│       ├── context.json           # normalized context packet
│       ├── domain_map.json
│       ├── layers/<layer>.json    # 5 layer analyses
│       ├── drafts/<layer>.batch.json # raw per-layer draft batches
│       ├── drafts/AM-XXX.v{n}.json   # every draft + critique iteration
│       ├── scores.json             # validated pre-policy portfolio
│       ├── ranked.json             # ranked, constraint-filtered portfolio
│       ├── opportunities.json     # final scored portfolio
│       └── report.md              # ranked table + strategic filters
└── opps/
    └── <domain-slug>/
        └── AM-XXX-<slug>.md       # self-contained brief (spec format, YAML frontmatter)
```

AM-XXX numbering is global and sequential, continuing from the current registry max
(existing corpus ends at AM-377). Domain slugs per spec rules.

## Known limitation

Runs are not automatically resumable yet. A resume API needs an explicit checkpoint
compatibility policy, stable draft-to-AM-ID allocation, and idempotent publication.
Until that contract is defined, failed runs restart from their original input; their
completed stage artifacts remain available for diagnosis.

## MCP tools (stdio server, `automation-miner-mcp`)

- `mine_domain(input, input_type=auto|idea|file|kb, constraints="", profile="default", max_iterations=2)` → run summary + artifact paths
- `list_runs()` / `list_domains()`
- `get_opportunity(am_id)` → full brief
- `query_registry(layer?, min_ice?, status?, domain?)` → filtered entries
- `get_run_report(run_id)` → report.md content
- `reindex()` → rebuild registry.json
- `server_info()` → version, active model routing, workspace path

## CLI (`automation-miner`)

- `automation-miner mine <idea> | --file F | --kb DIR [--constraints S] [--iterations N] [--profile P] [--workspace DIR] [--dry-run]`
- `automation-miner reindex [--workspace DIR]`
- `automation-miner list [--layer L] [--min-ice N] [--status S]`
- `automation-miner show AM-XXX`
- `automation-miner report RUN_ID`

`--dry-run` uses the mock model: zero cost, deterministic, for tests and demos.

## Model routing config (`miner.toml` in workspace or `~/.config/automation-miner/`)

```toml
[providers.openrouter]
base_url = "https://openrouter.ai/api/v1"
api_key_env = "OPENROUTER_API_KEY"

[providers.gemini]
base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
api_key_env = "GOOGLE_API_KEY"

[roles]
mapper         = { provider = "openrouter", model = "anthropic/claude-sonnet-4" }
layer_analyst  = { provider = "openrouter", model = "anthropic/claude-sonnet-4" }
drafter        = { provider = "openrouter", model = "anthropic/claude-sonnet-4" }
critic         = { provider = "openrouter", model = "openai/gpt-4.1" }
refiner        = { provider = "openrouter", model = "anthropic/claude-sonnet-4" }
scorer         = { provider = "openrouter", model = "openai/gpt-4.1" }
```

Env override: `MINER_MODEL_<ROLE>`, `MINER_MODEL` (all roles), `MINER_PROVIDER`.

## Quality rubric (critic, 0–10 weighted)

groundedness (25%) — every claim traces to domain evidence or is flagged as inference
specificity (20%) — named systems, actors, volumes; no generic filler
quantified_impact (20%) — time/cost/error numbers with assumptions
feasibility (15%) — realistic effort, dependencies, integration path
hitl_clarity (10%) — explicit human review points and escalation
differentiation (10%) — not a duplicate of another opp in the same run

Pass threshold: 7.5. Below → refine with critique. Persist all iterations.

## Stack

Python ≥3.12, uv, langgraph, pydantic v2, pyyaml, httpx, mcp (optional extra).
Dev: pytest, ruff. Tests run fully offline against the mock model.
