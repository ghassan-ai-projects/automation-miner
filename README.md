# automation-miner

> **Author:** [Ghassan Alhamoud](https://ghassan-alhamoud.com)

Structured domain analysis and automation discovery engine. Give it any industry
vertical, business process, or operational domain — a one-liner, a brief file, or a
whole knowledge-base folder — and it produces a ranked portfolio of **AM-XXX
automation opportunity briefs**, each ICE-scored and filtered into action tiers.

The pipeline (LangGraph):

```
ingest → input_assessment → domain_map → layer_analysis (×5 parallel)
       → portfolio_plan (value + diversity + prior ideas) → draft_candidates (parallel)
       → critique ⇄ refine (threshold 7.5, max N rounds, parallel over opportunities)
       → score (LLM proposes, code validates) → rank + strategic filters → publish
```

The 7.5 critic target drives refinement; this is an inspiration engine, so a
clean draft remains publishable down to the 6.0 inspiration floor. Hard
grounding or constraint violations still block publication and remain visible.

- **Any document format** — md, txt, pdf, docx, xlsx, pptx, csv, json, yaml, html —
  through a plugin reader registry you can extend without touching this package.
- **Citable evidence** — every input becomes numbered chunks (`[S12] claims.pdf p.4`);
  each stage draws only the slice relevant to its own question, within its own budget.
- **Structured outputs everywhere** — every role returns pydantic-validated JSON;
  parse/validation failures retry with the error fed back (max 3 attempts).
- **Deterministic scoring** — ICE math, coherence validation, constraint overrides,
  tie-breaking, and the three strategic filters run in code, never in the LLM.
- **Nothing silently dropped** — unreadable files, filtered opportunities, and score
  adjustments are all recorded and reported.
- **Artifacts as source of truth** — every node writes JSON into the run directory.
- **MCP-first**, with an equivalent CLI. No UI.

## Quickstart

```bash
uv sync
```

```bash
uv run automation-miner mine "German healthcare back office" --dry-run
```

That's a zero-cost deterministic run against the mock model — no API key needed.
For a real run:

```bash
export OPENROUTER_API_KEY=...
uv run automation-miner mine "German healthcare back office" --constraints "budget:low, team:3, compliance:heavy"
```

Inputs can also be a single file or a whole folder:

```bash
uv run automation-miner mine --kb ./kb/ --constraints "compliance:heavy"
```

Constraints may also be passed as open-ended parameters. The engine does not
need a code change for every new behavior:

```bash
uv run automation-miner mine --file ./research.md \
  --constraint agent=openclaw \
  --constraint deployment=local-only \
  --constraint max_agents=1
```

Every parameter is passed to portfolio planning, drafting, criticism, refinement,
and scoring as a binding run contract. The Python API accepts the same shape as
`constraint_params={"agent": "openclaw"}`, and the MCP tool exposes it as an object.

The default `--mode auto` runs an evidence preflight. It chooses `operational`
for current workflows and `strategy` for roadmaps, market research, and proposed
initiatives. Override it when operator intent is known:

```bash
uv run automation-miner mine --file ./roadmap.md --mode strategy
uv run automation-miner mine --kb ./process-evidence/ --mode operational
```

Strategy mode produces hypotheses with explicit assumptions and validation
questions. It does not treat recommendations or benchmarks as observed current
processes. Operational mode expects evidence such as owners, systems, handoffs,
volumes, durations, errors, and controls.

Other commands:

```bash
uv run automation-miner readers                 # formats handled + missing deps
uv run automation-miner list --tier high --min-ice 60
uv run automation-miner show AM-001
uv run automation-miner summary 2026-07-22_my-domain
```

## Document formats

```bash
uv sync --extra readers
```

| Format | Reader | Extra needed |
|--------|--------|--------------|
| md, markdown, txt, rst, adoc, org, log, tex | text | — |
| json, jsonl, ndjson | json | — |
| yaml, yml | yaml | — |
| csv, tsv, psv | csv | — |
| html, htm, xhtml | html | — |
| pdf | pdf | `--extra pdf` |
| docx | docx | `--extra docx` |
| xlsx, xlsm | xlsx | `--extra xlsx` |
| pptx | pptx | `--extra pptx` |

Run `automation-miner readers` to see what is registered and whether each is usable.
Files that cannot be read — a corrupt PDF, a scanned page needing OCR, an unsupported
binary — are skipped individually with a reason and listed in the run report, never
silently dropped. Spreadsheets are profiled (row counts, column types, value
distributions, a bounded row sample) rather than dumped, so a 5,000-row CSV costs a few
hundred tokens instead of megabytes.

PDFs with broken character maps also fail before mining when extraction produces
systematic corruption such as `operaDng` or `por;olio`. OCR or re-export the source;
`[readers.pdf] allow_low_quality = true` is an explicit unsafe override.

### Adding a format

No change to this package is needed. Either ship an entry point from your own
distribution:

```toml
[project.entry-points."automation_miner.readers"]
vtt = "my_pkg.readers:VttReader"
```

…or name a factory in `miner.toml`:

```toml
[[readers.custom]]
suffixes = [".rtf"]
factory = "my_pkg.readers:RtfReader"
```

A reader is a small class — declare `name`, `suffixes`, and implement `parse`:

```python
from automation_miner.readers import BaseReader, MediaType, Segment

class RtfReader(BaseReader):
    name = "rtf"
    suffixes = (".rtf",)
    media_type = MediaType.DOCUMENT

    def parse(self, path, data):
        return [Segment(text=strip_rtf(self.decode(data)), locator="body")]
```

Custom readers outrank built-ins for the same suffix, so you can replace one too.

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
`query_registry`, `get_run_report`, `get_run_summary`, `list_readers`, `reindex`,
`server_info`.

`mine_domain` returns the run summary inline — per-opportunity ICE, tier, strategic
filters, eligibility, and token usage — so a driving agent does not have to parse
markdown or load every full draft to decide what to act on.

## Workspace layout

```
<workspace>/                       # ./mining-workspace or $MINER_WORKSPACE
├── .am-counter                    # monotonic AM-ID allocation watermark
├── .cache/digests/                # content-hashed KB digests (re-runs are free)
├── registry.json                  # machine index (rebuilt by reindex)
├── runs/
│   └── YYYY-MM-DD_<domain-slug>/
│       ├── run.json               # manifest: input, config, models, usage, timings
│       ├── run.md                 # human run log
│       ├── summary.json           # compact agent-facing view
│       ├── context.json           # evidence index, skipped files, context stats
│       ├── domain_map.json
│       ├── layers/<layer>.json    # 5 layer analyses
│       ├── candidate_portfolio.json  # value/diversity plan + prior-idea comparison
│       ├── drafts/candidate-*.json   # one raw draft per planned candidate
│       ├── drafts/AM-XXX.v<n>.json   # every draft + critique iteration
│       ├── scores.json            # validated scores before portfolio policy
│       ├── ranked.json            # ranked portfolio with eligibility + stats
│       ├── opportunities.json     # final scored portfolio
│       ├── report.md              # ranked table, tiers, exclusions, cost
│       └── error.json             # only on failure: stage + diagnosis
└── opps/
    └── <domain-slug>/
        └── AM-XXX-<slug>.md       # self-contained brief, YAML frontmatter
```

AM-XXX numbering is global and sequential, continuing from the workspace max.

## Scoring

ICE = Impact × Confidence × Ease (each 1–5, so 1–125), bucketed into tiers:
`vision` ≥ 80, `high` 60–79, `medium` 40–59, `low` < 40.

The LLM proposes each factor **with its own rationale**; code then validates.
Proposed factors are cross-checked against the draft's own effort, impact and risk
estimates — High effort cannot also be Ease 5, a Low impact estimate cannot also be
Impact 5, a draft citing no evidence cannot claim high confidence. Adjustments only
ever lower a score, and each one is recorded in the brief.

Constraint policy is enforced in code after scoring. Low-budget and no-code runs
require Ease ≥ 4; compliance-heavy runs exclude unresolved high-risk items;
infrastructure maturity limits eligible layers; agent limits cap topology;
urgent/tight-timeline runs publish the top three by Ease then ICE.

Opportunities excluded by that policy are **kept**, not deleted — they were drafted,
critiqued, refined and scored, so each one carries its exclusion reason and appears in
`summary.json` and in the report's "Excluded by Constraint Policy" section.

## Context budget

Large inputs are chunked into a citable evidence index, and each stage selects the
chunks most relevant to its question via deterministic BM25 over that layer's signal
vocabulary. Defaults (all configurable under `[context]` in `miner.toml`):

| budget | tokens | used by |
|--------|-------:|---------|
| `evidence_tokens` | 60,000 | whole-index ceiling |
| `map_tokens` | 24,000 | domain mapping |
| `layer_tokens` | 16,000 | each layer analyst |
| `draft_tokens` | 16,000 | each drafter |
| `critique_tokens` | 10,000 | critique/refine |
| `score_tokens` | 3,000 | scorer |

Over-budget inputs are digested toward a target size (preserving source and locator),
in parallel, cached by content hash. If still over budget, whole chunks are dropped —
evidence is lost as complete attributed units, never as a severed sentence.

## Model routing

Roles (`mapper`, `layer_analyst`, `drafter`, `critic`, `refiner`, `scorer`) map to
provider/model via `miner.toml` in the workspace or `~/.config/automation-miner/`:

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

[retry]
attempts = 4

[concurrency]
critique = 4
score = 4
```

Any provider with a `base_url` speaks the OpenAI chat-completions protocol, so
custom OpenAI-compatible endpoints work too. Env overrides: `MINER_PROVIDER`
(all roles), `MINER_MODEL` (all roles), `MINER_MODEL_<ROLE>` (one role).
`--dry-run` forces the deterministic mock provider for everything.

Transient provider failures (429, 5xx, timeouts) retry with exponential backoff and
honour `Retry-After`, so a rate limit does not discard a run's already-paid work.
Token usage is tracked per role and reported in `run.json`, `summary.json`, the report,
and the CLI.

## Development

```bash
make sync      # uv sync --all-extras
make test      # uv run pytest (fully offline, mock model)
make lint      # uv run ruff check src tests
make dry-run   # end-to-end smoke run
```

Domain logic reference lives in `docs/spec/` (4 phases, 5 layers, ICE scoring,
constraint rules); the implementation contract is `docs/DESIGN.md`, and
`docs/IMPROVEMENT-PLAN.md` records the review the current version answers.

Runs currently restart from their original input after a failure. Stage artifacts plus
`error.json` are durable and sufficient for diagnosis, but a public resume command and
checkpoint compatibility policy are not yet implemented.
