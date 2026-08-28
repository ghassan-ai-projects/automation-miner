# Independent Code Review — Correctness / Reliability

**Reviewer:** Mill (independent review agent)  
**Date:** 2026-08-28  
**Scope:** Phase 1 and Phase 2 working tree before commit  
**Initial evidence:** 279 tests passed; Ruff clean; `git diff --check` clean  
**Final disposition:** all findings fixed and re-tested; no P0 findings

## Findings and disposition

| Severity | Finding | Disposition and evidence |
|---|---|---|
| P1 | Rich input quality scoring could exceed the schema's maximum after bonuses. | Fixed by clamping after all bonuses in `src/automation_miner/quality.py`; large rich-input regression added. |
| P1 | Clause-near negation could suppress a later valid policy, for example `not urgent, but urgent`. | Fixed with clause-bounded parsing and regression coverage in `tests/test_scoring.py`. |
| P1 | Raw evidence could close its XML-like fence, and truncated overview text could leave it open. | Fixed with HTML escaping and fence closure in `src/automation_miner/context.py`; hostile and truncation tests added. |
| P1 | Thin inputs could still be rendered as implementation briefs when the model supplied citations. | Fixed: thin source quality is an independent hypothesis-framing predicate passed to brief and summary rendering; graph regression added. |
| P1 | Unknown parameter values could activate policy when parsed from the rendered prompt string. | Fixed by persisting raw policy prose separately and parsing it directly; `MinerState` now carries `policy_constraints`; graph regression added. |
| P1 | Compliance risk capping could turn a high-risk draft into an eligible medium-risk draft. | Fixed by persisting `source_risk_level` and applying compliance eligibility to the original risk. |
| P1 | High-stakes residency/payment behavior depended on loose prose detection. | Fixed with structured `ExternalDataChannel` and `PaymentAction` contracts plus conservative rejection of unstructured sensitive actions. |
| P2 | Preflight was emitted after model-backed digesting. | Fixed by profiling source chunks and invoking the callback before digesting; ordering regression added. |
| P2 | PDF page-level telemetry was lost for empty or all-failed pages. | Fixed with page telemetry on empty pages and metadata-bearing `ReaderError`; reader regression added. |
| P2 | Structured parameters were absent from the compact summary. | Fixed by persisting raw/effective constraints and `constraint_params` in `RunSummary`. |
| P2 | Prompt provenance remained at 3.1 after prompt behavior changed. | Fixed by bumping `PROMPT_VERSION` to 3.2. |

## Verification after fixes

- `UV_CACHE_DIR=.uv-cache uv run ruff check src tests` — passed.
- `UV_CACHE_DIR=.uv-cache uv run pytest -q` — 289 passed.
- `git diff --check` — passed.

The review confirms offline correctness only. It does not prove live-provider
behavior, semantic grounding, or product value.

## Phase 3 review loop

**Scope:** Per-run execution budgets, retries and usage telemetry, terminal
failure artifacts, run attribution, and publication visibility.

The independent correctness loop identified and required fixes for hard token
admission under concurrent attempts, retry/deadline handling, exact versus
estimated usage, failed-attempt accounting, and terminal failure `calls`
values. The implementation now reserves prompt plus route-cap tokens before
each attempt, separates logical calls from attempts, preserves provider
exactness, records failed attempts with `calls=0`, and covers the behavior in
`tests/test_execution.py`, `tests/test_execution_provider.py`, and
`tests/test_graph.py`.

The latest returned correctness review (Plato) rejected two P1 findings: crash
recovery could omit `summary.json`, and failure views retained stale metadata.
Those findings were fixed with shared failure projection and a recovery-summary
regression in `tests/test_publication.py`, before commit `29d9d69`. A subsequent
replacement reviewer pair did not return within bounded waits; that
orchestration gap is not counted as approval. The returned findings are closed,
and the missing final approval verdict remains an explicit evidence gap.

## Phase 4 review

**Reviewer:** Heisenberg (independent correctness/contracts/static-typing lens)
**Date:** 2026-08-28
**Disposition:** APPROVE; no P1/P2 findings

The review confirmed consistent `DraftBatch` removal, typed shared state, bounded
dependencies, and green `mypy`, Ruff, contract, test, and build gates. The
contract checker reports 35 schema contracts and 30 state channels with live
owners.

## Phase 5 review loop

**Reviewer:** Lovelace (independent correctness/privacy/runtime lens)
**Date:** 2026-08-28

The initial review rejected missing corpus evidence fencing, weak terminal
artifact validation, repository-local live inputs/results, and incomplete
manifest/summary reconciliation. The correction loop added escaped untrusted
evidence, typed `StageFailure` validation, external-path guards, exact
cross-artifact status/usage/budget/count/ID checks, and duplicate-ID detection.
The corrected final review disposition was **APPROVE**, with no remaining P1/P2
findings. Offline harness tests and the full offline suite passed.
