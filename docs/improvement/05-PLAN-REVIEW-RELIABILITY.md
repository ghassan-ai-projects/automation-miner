# Independent Plan Review — Reliability / Security / Architecture

**Reviewer:** independent plan-review subagent  
**Date:** 2026-08-28  
**Disposition:** revise, then approved after corrections

## Findings

| Severity | Finding | Disposition |
|---|---|---|
| High | Unresolved evidence ids were recorded but did not independently block publication. | Fixed in the bar and Phase 2: deterministic resolvability exclusion is a separate predicate, with a critic-that-passes adversarial test. |
| High | A budget stored on `MinerModel` would mix simultaneous runs and overshoot under check-then-record concurrency. | Fixed: Phase 3 now specifies per-run execution context, atomic attempt admission, retry/attempt semantics, deadline handling, and shared-model isolation tests. |
| High | Ingestion failures could occur before a run directory existed; later attribution used newest-directory mtime. | Fixed: Phase 3 allocates a run handle and initial manifest before ingestion and records explicit stage/status ownership. |
| Medium/High | Generic string parameters and reparsing rendered text could make policy nondeterministic. | Fixed: typed recognized policy, direct application, explicit precedence, conservative legacy prose, advisory unknowns. |
| Medium | Evidence fences mitigate accidental instruction following but are not a complete trust boundary. | Fixed: bar language calls them mitigation, requires provenance and security documentation, and keeps deterministic checks narrowly scoped. |
| Medium | A naïve replacement for `fcntl` could lose cross-process atomicity. | Fixed: use SQLite `BEGIN IMMEDIATE` or an equivalently tested adapter plus subprocess tests. |
| Medium | A type checker alone would not catch dead contracts or budget races. | Fixed: require reduced untyped state plus a separate orphan-contract check and concurrency tests. |
| Medium | The original 50-call live cap was below the pipeline's candidate maximum. | Fixed: live plan now requires explicit candidate/iteration/retry/digest caps with a mathematical maximum below the budget. |

## Positive evidence

The reviewer confirmed the offline baseline remained healthy: workspace-local
`UV_CACHE_DIR=.uv-cache uv run pytest -q` passed 272 tests. No files were edited
by the reviewer.
