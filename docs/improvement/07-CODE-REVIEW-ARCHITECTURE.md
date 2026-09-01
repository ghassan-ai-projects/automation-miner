# Independent Code Review — Architecture / Security / Maintainability

**Reviewer:** Harvey (independent review agent)  
**Date:** 2026-08-28  
**Scope:** Phase 1 and Phase 2 working tree before commit  
**Initial evidence:** 279 tests passed; Ruff clean  
**Final disposition:** all findings fixed and re-tested; no P0 findings

## Findings and disposition

| Severity | Finding | Disposition and evidence |
|---|---|---|
| P1 | Model-produced artifacts were inserted into downstream prompts without a data boundary. | Fixed with one escaped `_untrusted()` prompt helper and fenced domain-map artifacts across prompt builders. |
| P1 | Digesting used raw source content and an empty system prompt, bypassing the trust protocol. | Fixed: digest content is escaped/fenced, `MAPPER_SYSTEM` owns the mapper contract, and the mock extracts the source block. |
| P1 | Payment and residency prose matching was too fragile for high-stakes hard policy. | Fixed with typed draft declarations and conservative unstructured-action exclusions. |
| P2 | Case-insensitive duplicate structured keys silently collapsed. | Fixed in `normalize_constraint_params`; direct parser calls also record deterministic duplicate warnings. |
| P2 | Unknown parameters were described as binding in prompts while code treated them as advisory. | Fixed in `CONSTRAINT_RULES`, rendering, and candidate drafting language. Raw and rendered constraints are now separate. |
| P2 | Input quality was calculated only after digesting. | Fixed with source and retained profiles; source preflight occurs before digest. |
| P2 | Artifact classification was duplicated between brief and summary rendering. | Fixed by reusing `is_discovery_hypothesis()` in reports. |
| P2 | Report wording claimed every non-published item was a constraint exclusion. | Fixed section heading and explanation to cover policy and quality gates. |
| P2 | `MAPPER_SYSTEM` and the old `draft_prompt()` path were orphaned. | `MAPPER_SYSTEM` is now the live digest system contract; unused `draft_prompt()` was removed and tests now cover the live candidate path. `ease_first()` remains a supported parameter-aware compatibility helper. |
| P2 | Fatal PDF extraction did not preserve page details. | Fixed through metadata-bearing `ReaderError` and skip telemetry propagation. |

## Verification after fixes

- Prompt injection regression covers hostile closing tags and escaped artifacts.
- End-to-end unresolved evidence-reference regression proves a critic-pass draft
  is still filtered before publication.
- `UV_CACHE_DIR=.uv-cache uv run pytest -q` — 289 passed.
- `UV_CACHE_DIR=.uv-cache uv run ruff check src tests` — passed.
- `git diff --check` — passed.

The prompt fence is a mitigation, not an isolation boundary. Provider-side
retention, sensitive-data handling, and semantic grounding remain external or
human-evaluation evidence gaps documented in the live-provider plan.

## Phase 3 review loop

**Scope:** Execution ownership, cross-process AM-ID allocation, failure
visibility, registry/API publication safety, and operational maintenance.

The Phase 3 architecture reviews found and required fixes for mixed legacy/new
allocator coordination, partial publication, missing failure access through the
MCP surface, provider-attempt token caps, usage ownership, malformed manifests,
and fail-open visibility of incomplete generated briefs. The implementation
now uses SQLite `BEGIN IMMEDIATE` with a migration lock, writes a pending
manifest before promotion, exposes manifest/error retrieval, owns usage in a
per-run execution context, and requires a completed source manifest plus
opportunity membership before registry or direct lookup visibility. Malformed
source manifests are fail-closed and covered by `tests/test_registry.py`.

The latest returned architecture review (Cicero) rejected five findings: crash
ordering, fail-open direct lookup, malformed-manifest masking, unlocked
quarantine, and duplicated/stale failure projection. Those findings were fixed
with a journal recovery state machine, strict frontmatter/manifest validation,
locked quarantine plus reindex, malformed-read guards, and shared projection
helpers before commit `29d9d69`. A subsequent replacement reviewer pair did not
return within bounded waits; that orchestration gap is not counted as approval.
The returned findings are closed, and the missing final approval verdict
remains an explicit evidence gap.

## Phase 4 review loop

**Reviewer:** Hubble (independent architecture/maintenance lens)
**Date:** 2026-08-28
**Initial disposition:** REJECT, P2

The reviewer found an orphaned `MinerState.analysis` channel and noted that the
contract checker did not inspect `TypedDict` channels. The channel was removed
from `src/automation_miner/graph/state.py`, and
`scripts/check_contracts.py` now enumerates TypedDict fields and requires a
production owner outside the declaration.

**Corrected re-review disposition:** APPROVE; no remaining P1/P2 findings.
**Verification:** 320 tests passed, Ruff passed, mypy passed, contract check
passed, and the build passed.

## Phase 5 review loop

**Reviewer:** Hypatia (independent architecture/maintenance/evaluation lens)
**Date:** 2026-08-28

The initial review rejected weak corpus balance/provenance, profile collapse,
missing label rationales, insufficient rating/adjudication gates, identity
leakage controls, and an aggregate budget contradiction. The correction loop
added canonical corpus hashing and rationales, distinct profiles, a shared
70-attempt/120,000-token/30-minute budget with a 1,000-token critic cap,
identity-key variant rejection, 2–3 domain enforcement, claim-level evidence
annotations, a weighted-kappa threshold, and mandatory adjudication. The
corrected final review disposition was **APPROVE**, with no remaining P1/P2
findings.
