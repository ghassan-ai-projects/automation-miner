# automation-miner

> **Author:** [Ghassan Alhamoud](https://ghassan-alhamoud.com)

[![CI](https://github.com/ghassan-ai-projects/automation-miner/actions/workflows/ci.yml/badge.svg)](https://github.com/ghassan-ai-projects/automation-miner/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Structured domain analysis and automation discovery engine. Give it any industry
vertical, business process, or operational domain — a one-liner, a brief file, or a
whole knowledge-base folder — and it produces a ranked portfolio of **AM-XXX
automation opportunity briefs**, each ICE-scored and filtered into action tiers.

The pipeline (LangGraph):

```
ingest → input_assessment → domain_map → layer_analysis (×5 parallel, sized pain points)
       → pain ledger (ranked in code) → portfolio_plan (must cover the top pains)
       → draft_candidates (parallel)
       → critique ⇄ refine (threshold 7.5) → surgical repair + verification if blocked
       → comparative scoring (LLM proposes side by side; code validates and caps)
       → rank + strategic filters → publish
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

Prerequisites: Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/ghassan-ai-projects/automation-miner.git
cd automation-miner
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
uv run automation-miner evaluate 2026-07-22_my-domain   # grade a run (see below)
uv run automation-miner export 2026-07-22_my-domain     # stakeholder one-pager (HTML)
```

`export` writes `one-pager.html` into the run: one self-contained page (no
scripts, no external requests, all text escaped) with the recommended
opportunities, their first step, expected impact, success measures, main
risks, and current lifecycle status, ready to open, print, or forward.

After publication, track what happens to each brief. Status moves through
identified → evaluating → designing → implementing → live (or deprecated), and
each measured result is recorded against one of the brief's numbered success
measures:

```bash
uv run automation-miner status AM-001 evaluating --note "2-week pilot agreed"
uv run automation-miner outcome AM-001 1 "4 min per claim" --baseline "9 min" --verdict met
uv run automation-miner outcomes        # every result next to the ICE it was published at
```

Events are appended to `lifecycle.json`; the brief's frontmatter carries the
current status and latest verdict, and a Lifecycle section shows the history.
`outcomes` groups verdicts by tier, which tells you whether high-ICE ideas
actually deliver more often than low ones.

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
`get_run_manifest`, `get_run_error`, `evaluate_run`, `server_info`, and the
lifecycle tools `export_one_pager`, `set_opportunity_status`,
`record_opportunity_outcome`, `list_outcomes`.

`mine_domain` returns the run summary inline — per-opportunity ICE, tier, strategic
filters, eligibility, and token usage — so a driving agent does not have to parse
markdown or load every full draft to decide what to act on.

## Workspace layout

Each run separates **results** (what you read) from **trace** (how the pipeline
got there). Results are a single source of truth: `opportunities.json`.

```
<workspace>/                       # ./mining-workspace or $MINER_WORKSPACE
├── .am-ids.sqlite3                # transactional AM-ID allocation watermark
├── .cache/digests/                # content-hashed KB digests (re-runs are free)
├── registry.json                  # machine index across runs (rebuilt by reindex)
├── lifecycle.json                 # append-only status changes and measured outcomes
├── runs/
│   └── YYYY-MM-DD_<domain-slug>/
│       ├── run.json               # manifest: status, input, models, budget, usage, timings
│       ├── opportunities.json     # THE result: every opportunity, score, eligibility, reasons
│       ├── summary.json           # compact agent-facing view
│       ├── report.md              # at-a-glance decisions, pain coverage, ranking, exclusions
│       ├── one-pager.html         # optional: `automation-miner export` for stakeholders
│       ├── evaluation.{json,md}   # optional: `automation-miner evaluate`
│       ├── error.json             # only on failure: stage + diagnosis
│       ├── publication/           # staged briefs + crash-recovery journal
│       └── trace/
│           ├── context.json       # evidence index the briefs cite (S-ids)
│           ├── input_assessment.json, domain_map.json
│           ├── layers/<layer>.json        # 5 layer analyses with sized pain points
│           ├── pain_ledger.json           # pains ranked by code + which candidate covers each
│           ├── candidate_portfolio.json   # the planned portfolio
│           ├── drafts/<candidate>.json    # first draft per candidate
│           ├── critique/AM-XXX.v<n>.json  # every critique round (+ .repair.json)
│           └── run-log.md                 # phase-by-phase human run log
└── opps/
    └── <domain-slug>/
        └── AM-XXX-<slug>.md       # self-contained brief, YAML frontmatter
```

Runs written before October 2026 (flat layout, plus duplicate `scores.json` and
`ranked.json`) remain readable.

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

Which of those policies apply is decided once per run and recorded in
`trace/context.json`. Typed parameters (`--constraint budget=low`,
`compliance=true`, `timeline=tight`, `agent_limit=2`) always win. Free-text
`--constraints` are read by a model into the same typed flags, and each flag
must quote the words that impose it: code discards a clause whose quote is not
in the text, so "no budget concerns" never switches on the low-budget filter.
The report's Notes name the source of every active policy, and warn when a
keyword appears that was not read as binding. If the reading call fails, the
run falls back to keyword matching and says so.

Opportunities excluded by that policy are **kept**, not deleted — they were drafted,
critiqued, refined and scored, so each one carries its exclusion reason and appears in
`summary.json` and in the report's "Excluded by Constraint Policy" section.

## What a good brief looks like

Every statement in a brief is one of three kinds:

- **Observed**: a fact about the subject organization. It traces to an evidence
  block, and the ids are listed in the brief's Evidence section with source and
  location.
- **Domain knowledge**: public, general knowledge such as regulation, industry
  practice, or standard tools. Used freely; it is what makes a brief expert.
- **Assumption**: a premise or estimate about the organization that the evidence
  does not establish. Recorded under *Assumptions* or as an impact-row estimate,
  with a validation question.

Epistemic status lives in that structure, not in hedges inside the prose. Code
enforces this: a draft that writes evidence commentary ("inferred from S2…",
"not explicitly stated") into its prose does not pass a critique round. The exact
excerpts go back to the refiner. Only fabricated current-state facts, absence
claims, wrong domain knowledge, and hard-constraint conflicts block publication.

See [docs/VISION.md](docs/VISION.md) for the product intent.

## Evaluating quality

```bash
uv run automation-miner evaluate <run-id> --no-judge   # deterministic lint only, free
uv run automation-miner evaluate <run-id>              # + independent judge model
```

The lint flags reader-facing defects code can prove: evidence commentary in
prose, double numbering, empty required sections, and garbled template text.

The judge is the `judge` role in `miner.toml` (default: the same cheap flash
model). It is built to resist grading its own family leniently. One call audits
every organization-specific claim against the evidence. Code turns the audit
into the honesty grade and caps the overall grade by it. A second call writes
weaknesses before grading specificity, insight, actionability, domain expertise,
and readability, and a third grades the portfolio's diversity and coverage.
Calibrated against a much stronger reference judge, it lands within 0.3 per run.
Results go to `evaluation.json` and `evaluation.md` in the run directory, and
are also available as the `evaluate_run` MCP tool.

`scripts/quality_suite.py` runs three reference cases from `examples/` against a
real provider and grades them against the bar in
[docs/quality/00-QUALITY-BAR.md](docs/quality/00-QUALITY-BAR.md).

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
mapper        = { provider = "openrouter", model = "deepseek/deepseek-v4-flash" }
layer_analyst = { provider = "openrouter", model = "deepseek/deepseek-v4-flash" }
drafter       = { provider = "openrouter", model = "deepseek/deepseek-v4-flash", max_tokens = 24000 }
critic        = { provider = "openrouter", model = "deepseek/deepseek-v4-flash" }
refiner       = { provider = "openrouter", model = "deepseek/deepseek-v4-flash" }
scorer        = { provider = "openrouter", model = "deepseek/deepseek-v4-flash", temperature = 0.1 }
judge         = { provider = "zai",        model = "glm-5.3-flash" }  # evaluate only

[retry]
attempts = 4

[concurrency]
critique = 8
score = 4

[budget]
max_attempts = 200
max_tokens = 1500000
max_seconds = 2400
```

Built-in providers: `openrouter` (`OPENROUTER_API_KEY`), `gemini`
(`GOOGLE_API_KEY`), and `zai` for Z.ai GLM models (`ZAI_API_KEY`). The `zai`
default is the GLM Coding Plan endpoint; a pay-as-you-go key needs
`base_url = "https://api.z.ai/api/paas/v4"` under `[providers.zai]`. The judge
runs on a different model family from the generator so it does not grade its
own family's writing.

Per role, `reasoning_effort = "off" | "minimal" | "low" | "medium" | "high"` sets
OpenRouter's unified reasoning control for reasoning models. OpenRouter-only
request fields (`reasoning`, provider routing) are sent to OpenRouter only.

Providers stream by default where supported (`stream = true` under
`[providers.<name>]`). Streaming makes progress visible: an attempt that sends
no data for `retry.stall_seconds` (default 60; keep-alives don't count) is
abandoned and retried at once, instead of waiting out `retry.request_seconds`
(default 300). Reasoning models get generous `max_tokens` per role so thinking
cannot starve the JSON answer.

Any provider with a `base_url` speaks the OpenAI chat-completions protocol, so
custom OpenAI-compatible endpoints work too. Env overrides: `MINER_PROVIDER`
(all roles), `MINER_MODEL` (all roles), `MINER_MODEL_<ROLE>` (one role).
`--dry-run` forces the deterministic mock provider for everything.

Transient provider failures (429, 5xx, timeouts) retry with exponential backoff and
honour `Retry-After`, so a rate limit does not discard a run's already-paid work.
Token usage is tracked per role and reported in `run.json`, `summary.json`, the report,
and the CLI. Each invocation also has independent attempt, token, and wall-clock
admission limits; budget exhaustion is recorded as a terminal `budget_exhausted` status.

## Development

```bash
make sync      # uv sync --all-extras
make test      # uv run pytest (fully offline, mock model)
make lint      # uv run ruff check src tests
make type-check # uv run mypy
make contract-check # retired-symbol and schema-owner check
make build     # build wheel and source distribution
make ci-check  # lint, test, type-check, contract-check, and build
make dry-run   # end-to-end smoke run
```

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening
a pull request.

Runs currently restart from their original input after a failure. The initial run handle
is written before ingestion; stage artifacts, terminal status, budget telemetry, and
`error.json` are durable and sufficient for diagnosis, but a public resume command and
checkpoint compatibility policy are not yet implemented. Existing `.am-counter` files
are read as a migration watermark when the SQLite allocator is first used.

## Open source

- [License](LICENSE)
- [Changelog](CHANGELOG.md)
- [Contributing guide](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Code of conduct](CODE_OF_CONDUCT.md)
- [Support guide](SUPPORT.md)

Automation Miner is released under the MIT license.

## Status

Current version: `0.1.0` (alpha). Public APIs and artifact schemas may change before
the first stable release.
