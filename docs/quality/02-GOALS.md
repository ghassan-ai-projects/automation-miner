# Goal and Work Plan

## Goal

**One complete quality-suite run passes every check in
[`00-QUALITY-BAR.md`](00-QUALITY-BAR.md)**, using only cheap models
(`deepseek-v4-flash` or cheaper), with the engineering gates green:

- Every Python file is at most 300 lines (`make size-check`).
- Every function in `src/` is at most 25 code lines (`make function-check`).
- ruff, mypy, the contract check, tests, and the build pass (`make ci-check`).

The goal is met only by evidence: a `quality-report.md` with verdict PASS and a
green `make ci-check` on the same commit.

## Status

| # | Item | Status | Evidence |
|---|---|---|---|
| Q1 | Real runs complete under default settings | ✅ | iter-1/iter-2: 3/3 complete (baseline 0/3) |
| Q2 | 0 lint errors in published briefs | ✅ | iter-1/iter-2: 0 errors, 0 hedges |
| Q3 | Judge ≥ 4.0 overall, honesty, coverage | ⏳ | iter-2 judge blocked by the API key cap; iter-3 pending |
| Q4 | Wall clock ≤ 15 min per run | ⏳ | iter-2: ~19–20 min → streaming, reasoning cap, runaway-provider exclusion added |
| E1 | Files ≤ 300 lines | ✅ | `make size-check` |
| E2 | Functions ≤ 25 lines in `src/` | ✅ | `make function-check` (97 → 0) |
| E3 | `make ci-check` green | ✅ | lint, 384 tests, mypy, contracts, size, function size, build |

### Improvement scan (2026-10-03)

| # | Item | Status |
|---|---|---|
| 1 | Live stage progress in the CLI | ✅ |
| 2 | Provider-reported $ cost per role/run, `max_cost_usd` budget | ✅ |
| 3 | `resume` a failed run, reusing completed stages | ✅ |
| 4 | Typed constraint policy instead of prose regexes | ✅ |
| 5 | Suite covers large inputs and the original DHL input | ✅ |
| 6 | Unicode tokenizer and German retrieval vocabulary | ✅ |
| 7 | Prior-idea memory across differently named runs of one domain | ✅ |
| 8 | Lifecycle commands (status / measured outcome) | ✅ |
| 9 | Readers free of per-parse instance state | ✅ |
| 10 | Long functions split (see E2) | ✅ |
| 11 | Judge variance: 2 samples per brief | ✅ |
| 12 | Remove `type: ignore` in ingest | ✅ |
| 13 | Stakeholder export (HTML one-pager) | ⬜ |
| 14 | Readable report title for KB input | ✅ |

### Blocker

The OpenRouter key reached its $5 cap during iteration 2. Iteration 3 and the
judge cannot run until the cap is raised; every item above that needs no
provider call continues meanwhile.
