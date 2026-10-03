# Quality Loop — Iteration Log

Each entry is one full suite run (`scripts/quality_suite.py`, three cases, real
provider, independent judge) against [`00-QUALITY-BAR.md`](00-QUALITY-BAR.md).
Raw run directories live outside the repository; the numbers below are copied
from each suite's `quality-report.json`.

## Iteration 0 — baseline, engine as shipped (`09ac2f6`)

**Verdict: FAIL — 0/3 runs completed.**

| Case | Result |
|---|---|
| claims | `budget_exhausted` after 9 calls (144k of 120k tokens) during portfolio planning |
| strategy | `budget_exhausted` (125k) at drafting |
| oneliner | `budget_exhausted` (125k) at drafting |

Root cause: the default `RunBudget` (120k tokens) was below what any real run
needs, and admission reserves each call's `max_tokens` up front, so parallel
drafting overshoots immediately. Every real run with default settings failed.
The previous program never caught this because it never made a provider call.

## Iteration 0b — baseline engine, budget raised (reference only)

| Case | Result |
|---|---|
| oneliner | completed in 20.6 min · 3/6 published · 8 lint errors (6 hedges) · judge overall **2.0** (reference judge) |
| strategy | **failed**: the critic returned empty content 4× — a 4k `max_tokens` was consumed by reasoning before any JSON |
| claims | stopped to preserve API credit |

## Iteration 1 — prompts v4, hygiene gate, budget, brief layout

**Verdict: FAIL** (reference judge). Functionality and hygiene fixed; content quality not.

| Case | Published | Min | Lint err | Overall | Fabricated | Coverage |
|---|---|---|---|---|---|---|
| claims | 7/8 | 15.5 | 0 | 2.57 | 42 | 3 |
| strategy | 4/5 | 11.5 | 0 | 2.25 | 19 | 2 |
| oneliner | 5/6 | 13.6 | 0 | 2.00 | 26 | 3 |

What the judge found, and what changed in response:

| Finding | Change |
|---|---|
| Observed facts stretched beyond their scope (a 9-min figure for email+paper applied to paper alone; causes and system capabilities asserted) | Precision rule in drafter, critic, refiner, and repair prompts |
| The best idea (MD-downcoding screen, ICE 36) filtered for one half-sentence; the refiner made it worse (8.2 → 6.8) | Critic quotes each defect; surgical repair + independent verifier |
| Obvious big wins missed (policy lookup, API claim creation, auto-acknowledgement, duplicates) | Layer analysts size pains; code ranks a pain ledger; planner must cover the top pains, with one revision round |
| All ICE 18–36, all "low"; tiers meaningless | Comparative portfolio scoring on value-anchored ladders; code caps confidence by evidence |
| MVPs without success criteria; regulation vague; autonomy phases broke constraints | `success_metrics` field; regulation and constraint-in-every-phase instructions |
| "OpenClaw agent" in unrelated briefs | Removed the concrete example from the planner prompt |
| A 26-row metrics CSV lost rows 16–21 including a storm spike | Small tables read in full; numeric stats; outlier rows survive sampling |
| Strategy briefs presented as implementation briefs | Framing decided in code and stored on the opportunity |

## Iteration 2 — pain ledger, comparative scoring, surgical repair

**Verdict: incomplete.** All three runs completed. The judge phase stopped when
the OpenRouter key reached its $5 cap (HTTP 403), so content quality is not
yet graded.

| Case | Published | Min | Calls | Tokens | Lint err | Hedges |
|---|---|---|---|---|---|---|
| claims | 6/7 | 19.9 | 31 | 484k | 0 | 0 |
| strategy | 5/5 | 19.3 | 29 | 281k | 0 | 0 |
| oneliner | 4/6 | 19.3 | 38 | 300k | 0 | 0 |

Findings and changes since:

| Finding | Change |
|---|---|
| ~19–20 min per run, above the 15-min bar; single calls ran for minutes | Streaming transport: a stall is 60 s with no data (keep-alives don't count), 300 s request cap |
| Reasoning consumed most of each call's output budget | Per-role `reasoning_max_tokens` cap |
| One upstream provider produced runaway, very slow completions | Provider routing passthrough; `openrouter` ignores it by default |
| The largest quantified pain (email/paper re-keying) was absent from the ledger | Analyst prompt must size every pain the evidence quantifies, observed hours first |
| One judge sample per brief is noisy | `evaluate_run(samples=2)`: mean grades, median critique |
| Spend was invisible until the key cap hit | Provider-reported `cost_usd` per role and run, `max_cost_usd` budget, live stage progress |
| A failed run had to restart from scratch | `resume` reuses every completed stage from `trace/` |

Iteration 3 needs the key cap raised.
