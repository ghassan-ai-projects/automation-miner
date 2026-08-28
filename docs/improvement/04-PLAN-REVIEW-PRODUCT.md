# Independent Plan Review — Product / Value / Evidence

**Reviewer:** independent plan-review subagent  
**Date:** 2026-08-28  
**Disposition:** revise, then approved after corrections

## Findings

| Severity | Finding | Disposition |
|---|---|---|
| High | The first plan deferred the audit's highest-value action (2–3 evidence-rich real runs) and required only one run for readiness. | Fixed: product proof is now a separate gate requiring 2–3 diverse domains, redacted outputs, and manual review. |
| High | The initial rubric had no sample size, anchored scoring rules, evaluator independence, agreement protocol, or thresholds. | Fixed in `02-REAL-PROVIDER-TEST-PLAN.md`: minimum sample, two blinded raters, adjudication, agreement, anchored thresholds, and acceptable honest no-op outcomes are now explicit. |
| High | Critic/gate quality versus model choice was not actually evaluated. | Fixed: the plan now requires a labelled grounded/ungrounded corpus and flash-versus-strong critic comparison with false-positive/false-negative reporting. |
| High | Reference existence was overstated as grounding proof. | Fixed: the bar and plan now call this a deterministic resolvability gate only; semantic support remains evaluator/verifier evidence. |
| Medium/High | Structured and free-form constraint semantics had ambiguous precedence. | Fixed: structured policy is authoritative; unknown parameters are advisory; legacy prose is conservative and warning-producing. |
| Medium | Privacy and provider retention/region assumptions were underspecified. | Fixed: the live plan prohibits production-sensitive data and requires provenance, redaction checks, and provider-policy capture. |

## Positive evidence

The reviewer confirmed the offline baseline remained healthy: workspace-local
`UV_CACHE_DIR=.uv-cache uv run pytest -q` passed 272 tests. No files were edited
by the reviewer.
