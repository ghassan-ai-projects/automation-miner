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

The latest bounded re-review was reissued after the preceding reviewer context
timed out. It had not returned a verdict at the time of this record; that
orchestration gap is not counted as approval. Phase 3 remains eligible for
commit only after the final independent verdict is recorded or the same review
is independently completed by another reviewer pair.
