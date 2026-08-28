# Automation Miner Improvement Plan

**Source audit:** `docs/audit/`  
**Bar:** [`00-IMPLEMENTATION-BAR.md`](00-IMPLEMENTATION-BAR.md)  
**Created:** 2026-08-28  
**Status:** Plan reviews complete; implementation in progress

## Operating rules

1. Preserve unrelated user changes.
2. One phase has one bounded write scope, a focused verification gate, and its
   own commit before the next phase starts.
3. Every behavior change gets a regression test and an artifact/CLI check where
   the behavior is user-visible.
4. Review evidence is independent: reviewers receive the current bar, plan,
   audit findings, and repository state, but do not share conclusions.
5. Do not call a fixture-provider result a real-model result.

## Phases

| Phase | Outcome | Main changes | Exit evidence | Status |
|---|---|---|---|---|
| 0 | Baseline and control | Record git/test/lint baseline; create tracking docs; review plan | Two plan reviews recorded; baseline captured | complete |
| 1 | Honest input and output framing | Deterministic evidence profile, preflight callback/CLI notice, Discovery Hypothesis briefs, step numbering, PDF telemetry | Focused tests + complete offline suite; artifacts show profile and framing | complete |
| 2 | Typed policy and trust boundary | Structured/negation-safe policy parsing, evidence data fences, deterministic resolvability gate, security docs | Adversarial policy/injection/grounding tests; no false-positive activation | complete |
| 3 | Bounded execution and reliability | Per-run budget/admission context, typed budget-exhaustion failure, terminal status, pre-ingestion run handle, portable ID locking | Budget tests under concurrency; failure artifacts identify exact run | pending |
| 4 | Contract and maintenance cleanup | Remove dead symbols/contracts, update mock/tests, reduce typed-state `Any`, static type gate, dependency bounds | `ruff`, `pytest`, type gate, orphan check, build all green | pending |
| 5 | Real-provider evaluation package | Add opt-in bounded smoke/evaluation harness, labelled gate corpus, privacy controls, and evidence-rich runbook | 2–3-domain plan, sample size, two blinded raters, agreement and thresholds | pending |
| 6 | Review loop and closure | Two independent code reviews; fix/re-review until bar; final status matrix | Review records, final tests, known evidence gaps, bar decision | pending |

## Design decisions to validate in review

- Use deterministic source and retained-evidence richness profiles for preflight
  and transparency. The model's `InputAssessment` remains responsible for
  operational-vs-strategy semantics; heuristics provide warnings and never
  override the model. Thin source input always forces hypothesis framing.
- Use a typed policy object for recognized structured parameters, with explicit
  precedence: structured values apply directly; legacy prose is parsed
  conservatively and records ambiguity/negation warnings; unknown parameters
  remain prompt context and never become hard filters without a registered
  handler. Never reparse a rendered prompt to make execution decisions.
- Fence evidence as data in prompts and add a code-level resolvability check for
  every draft's `evidence_refs`; a critic may add qualitative violations, but it
  cannot waive unresolved ids. Do not call id existence semantic grounding.
- Keep provider routing/transport on `MinerModel`, but put budget, deadline,
  cancellation, and usage ownership in a per-invocation `RunExecutionContext`.
  Atomically admit every HTTP/mock attempt before execution; count retries as
  attempts and expose logical calls separately.
- Allocate and persist a run handle before ingestion and pass it through every
  stage. Record explicit stage ownership and terminal status; do not infer
  failure ownership from filesystem mtime.
- Use SQLite `BEGIN IMMEDIATE` or an equally tested cross-process locking
  adapter for AM-ID allocation; do not replace `fcntl` with an untested rename.
- Prefer `mypy` with a narrow initial configuration, but require a measured
  reduction of untyped state and a separate orphan-contract check. Any ignored
  dynamic boundary must be named.

## Dependency order

```text
baseline/docs
    ↓
input profile + output framing ───────┐
                                      ├─→ budgets + cleanup → real-provider package
typed policy + trust boundary ───────┘             ↓
                                     independent code reviews ↺ fixes
```

## Tracking protocol

For each phase, append:

- implementation commit/change summary (one commit per phase);
- files changed;
- focused test command and result;
- full-suite command and result;
- reviewer findings and disposition;
- remaining evidence gap or decision.

The phase table is updated as work progresses. Review records live beside this
plan so a future maintainer can reconstruct why a change was accepted.

Product proof is a separate gate from engineering completion. It requires 2–3
diverse evidence-rich real-provider runs, at least 10 manually reviewable
opportunities across the set (published and filtered), two blinded raters, an
adjudicated disagreement sample, and the thresholds in the real-provider plan.
