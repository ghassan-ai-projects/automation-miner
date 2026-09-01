# Automation Miner Improvement Bar

**Source:** `docs/audit/00-AUDIT-PLAN.md` through `docs/audit/05-EXECUTIVE-SUMMARY.md`  
**Created:** 2026-08-28  
**Status:** Engineering bar met; product-readiness evidence remains external

## Purpose

Raise the project from a strong, well-tested engine to a safer and more useful
production-quality system without rewriting the pipeline or weakening its
deterministic verification boundary.

The bar is evidence-based. A checkbox is green only when the implementation,
tests, and persisted artifacts demonstrate it. A passing fixture test is not
real-provider or product-outcome evidence.

## Completion bar

### B1 — Input quality and product framing

- [x] Every run computes deterministic source and retained-evidence quality
  profiles and records their signals, missing categories, scores, and warnings
  in `context.json`, `summary.json`, `run.json`, and `report.md`.
- [x] The CLI exposes the profile before the expensive analysis stages begin,
  without printing from library code.
- [x] Thin/low-confidence published briefs are explicitly labeled
  **Discovery Hypothesis** and promote validation questions near the top.
- [x] Brief step rendering never produces duplicated list numbering.
- [x] A real evidence-rich provider evaluation is specified with 2–3 diverse
  domains, a fixed minimum sample, blinded independent raters, adjudication,
  agreement measurement, and predeclared thresholds; no offline run is
  misrepresented as product validation.

### B2 — Policy correctness

- [x] Constraint semantics have one typed source of truth for structured
  parameters and free-form compatibility syntax.
- [x] Negated prose such as “no budget concerns”, “compliance is not relevant”,
  and “not urgent” does not activate a hard policy.
- [x] Structured constraint parameters used for policy decisions are validated,
  persisted, rendered, and covered by focused tests.
- [x] Policy decisions remain deterministic after parsing; all overrides and
  exclusions remain auditable.

### B3 — Trust boundary and input robustness

- [x] Evidence inserted into every model prompt is visibly marked as untrusted
  data, with instructions that content inside the data region is not executable
  instruction.
- [x] Grounding references are deterministically re-resolved against the run's
  evidence index before publication; unresolved references are a hard quality
  gate, even if a critic omits a violation. This proves resolvability, not that
  the cited text semantically supports every claim.
- [x] PDF page extraction failures are recorded as telemetry rather than silently
  disappearing.
- [x] `SECURITY.md` documents the prompt-injection boundary and its residual
  limitations.

### B4 — Run safety and observability

- [x] Configurable per-invocation run budgets bound model attempts, tokens, and
  wall-clock time without sharing cumulative state across simultaneous runs.
- [x] Budget exhaustion stops the pipeline with a typed, honest failure artifact
  that identifies the limit, observed usage, admission policy, and artifacts
  already written.
- [x] Budget configuration and terminal status are persisted in the manifest and
  surfaced in the summary/report.
- [x] Concurrent failures are attributed to their own run directory, not merely
  the newest directory.
- [x] A run directory and initial status manifest exist before ingestion or any
  provider/digest call; partial publication has an explicit terminal-status
  policy.

### B5 — Code health and contract integrity

- [x] Stale v3.1 symbols and unused schema/test contracts are removed or have a
  documented live owner.
- [x] Static typing is configured for the production package and runs in CI with
  an explicit, reviewed boundary for unavoidable dynamic provider/LangGraph
  values; the shared state and run context have materially less `Any`, and a
  separate orphan-contract check covers what typing cannot detect.
- [x] Dependency compatibility bounds are explicit for the used framework
  surfaces.
- [x] POSIX-only ID locking is either portable or clearly rejected with a tested
  compatibility path.

### B6 — Verification and tracking

- [x] Focused tests cover each changed behavior and the complete offline suite is
  green.
- [x] Two independent plan reviews are recorded before implementation.
- [x] Two independent code reviews are recorded after implementation, covering
  correctness/reliability and architecture/maintainability/security.
- [x] Each review finding is dispositioned as fixed, accepted with rationale, or
  an explicit evidence gap.
- [x] A real-provider test plan names provider setup, capped scope, fixtures,
  assertions, cost/time guardrails, privacy/provenance controls, a labelled
  critic-gate corpus, and the evidence required before claiming product
  readiness.

## Non-goals

- Replacing LangGraph, the reader plugin model, or the artifacts-as-source-of-
  truth design.
- Claiming that deterministic tests prove model quality, provider behavior, or
  customer value.
- Building the long-term lifecycle feedback loop before the current run and
  evidence contracts are stable.

## Release decision

The engineering bar is met only when B1–B6 are green or explicitly marked as an
external evidence gap. Product readiness remains **not claimed** until the
real-provider plan is executed on 2–3 evidence-rich domains and the results are
reviewed against the rubric in `02-REAL-PROVIDER-TEST-PLAN.md`.
