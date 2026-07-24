# automation-miner

> **Author:** [Ghassan Alhamoud](https://ghassan-alhamoud.com)

Structured domain analysis and automation discovery engine. Give it any industry
vertical, business process, or operational domain — a one-liner, a brief file, or a
whole knowledge-base folder — and it produces a ranked portfolio of **AM-XXX
automation opportunity briefs**, each ICE-scored and filtered into action tiers.

The pipeline (LangGraph):

```
ingest → domain_map → layer_analysis (×5 parallel) → draft_opportunities (×5)
       → critique ⇄ refine (threshold 7.5, max N rounds)
       → score (LLM proposes, code validates) → rank + strategic filters → publish
```

- **Structured outputs everywhere** — every role returns pydantic-validated JSON;
  parse/validation failures retry with the error fed back (max 3 attempts).
- **Deterministic scoring** — ICE math, bounds, calibration, constraint overrides,
  and the three strategic filters run in code, never in the LLM.
- **Artifacts as source of truth** — every node writes JSON into the run directory.
- **MCP-first**, with an equivalent CLI. No UI.

## Quickstart

```bash
uv sync

# Zero-cost deterministic dry run (mock model, no API key needed):
uv run automation-miner mine "German healthcare back office" --dry-run

# Real run via OpenRouter:
export OPENROUTER_API_KEY=...
uv run automation-miner mine "German healthcare back office" \
    --constraints "budget:low, team:3, compliance:heavy"
```

Inputs can also be a file (`--file brief.md`, md/txt/json/yaml) or a
knowledge-base folder (`--kb ./kb/` — digested map-reduce style if over the
~40k-char context budget).

Other commands:

```bash
uv run automation-miner reindex                 # rebuild registry.json
uv run automation-miner list --layer decision --min-ice 40
uv run automation-miner show AM-001
uv run automation-miner report 2026-07-22_my-domain
```

## MCP server

```bash
uv sync --extra mcp
```

Agent config snippet:

```json
{
  "mcpServers": {
    "automation-miner": {
      "command": "uv",
      "args": ["run", "--extra", "mcp", "automation-miner-mcp"],
      "env": { "MINER_WORKSPACE": "/path/to/mining-workspace" }
    }
  }
}
```

Tools: `mine_domain`, `list_runs`, `list_domains`, `get_opportunity`,
`query_registry`, `get_run_report`, `reindex`, `server_info`.

## Workspace layout

```
<workspace>/                       # ./mining-workspace or $MINER_WORKSPACE
├── .am-counter                    # monotonic AM-ID allocation watermark
├── registry.json                  # machine index (rebuilt by reindex)
├── runs/
│   └── YYYY-MM-DD_<domain-slug>/
│       ├── run.json               # manifest: input, config, models, timing
│       ├── run.md                 # human run log
│       ├── context.json           # normalized context packet
│       ├── domain_map.json
│       ├── layers/<layer>.json    # 5 layer analyses
│       ├── drafts/<layer>.batch.json # raw per-layer draft batches
│       ├── drafts/AM-XXX.v<n>.json   # every draft + critique iteration
│       ├── scores.json             # validated scores before portfolio policy
│       ├── ranked.json             # ranked, constraint-filtered portfolio
│       ├── opportunities.json     # final scored portfolio
│       └── report.md              # ranked table + strategic filters
└── opps/
    └── <domain-slug>/
        └── AM-XXX-<slug>.md       # self-contained brief, YAML frontmatter
```

AM-XXX numbering is global and sequential, continuing from the workspace max.

## Model routing

Roles (`mapper`, `layer_analyst`, `drafter`, `critic`, `refiner`, `scorer`) map to
provider/model via `miner.toml` in the workspace or `~/.config/automation-miner/`:

```toml
[providers.openrouter]
base_url = "https://openrouter.ai/api/v1"
api_key_env = "OPENROUTER_API_KEY"

[providers.gemini]
base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
api_key_env = "GOOGLE_API_KEY"

[roles]
mapper        = { provider = "openrouter", model = "anthropic/claude-sonnet-4" }
layer_analyst = { provider = "openrouter", model = "anthropic/claude-sonnet-4" }
drafter       = { provider = "openrouter", model = "anthropic/claude-sonnet-4" }
critic        = { provider = "openrouter", model = "openai/gpt-4.1" }
refiner       = { provider = "openrouter", model = "anthropic/claude-sonnet-4" }
scorer        = { provider = "openrouter", model = "openai/gpt-4.1" }
```

Any provider with a `base_url` speaks the OpenAI chat-completions protocol, so
custom OpenAI-compatible endpoints work too. Env overrides: `MINER_PROVIDER`
(all roles), `MINER_MODEL` (all roles), `MINER_MODEL_<ROLE>` (one role).
`--dry-run` forces the deterministic mock provider for everything.

Constraint policy is enforced again in code after model scoring. Low-budget and
no-code runs require Ease >= 4; compliance-heavy runs exclude unresolved high-risk
items; infrastructure maturity limits eligible layers; agent limits cap topology;
urgent/tight-timeline runs publish the top three by Ease then ICE.

## Development

```bash
make sync      # uv sync
make test      # uv run pytest (fully offline, mock model)
make lint      # uv run ruff check src tests
make dry-run   # end-to-end smoke run into /tmp/am-smoke
```

Domain logic reference lives in `docs/spec/` (4 phases, 5 layers, ICE scoring,
constraint rules); the implementation contract is `docs/DESIGN.md`.

Runs currently restart from their original input after a failure. Stage artifacts
are durable and sufficient for diagnosis, but a public resume command and checkpoint
compatibility policy are not yet implemented.
