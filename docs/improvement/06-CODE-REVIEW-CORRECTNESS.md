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
