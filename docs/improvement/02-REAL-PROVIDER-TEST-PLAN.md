# Real-Provider Test Plan

This is an opt-in evaluation plan, not a claim that the offline mock suite
proves provider quality or product value. It must be run only with approved,
redacted, non-production inputs.

## Objective

Measure whether the trust layer remains useful with a real OpenAI-compatible
provider and whether evidence-rich inputs produce more actionable output than
the audited 944-token domain description.

## Provider setup

- Use a dedicated provider profile in `miner.toml` with an explicit model for
  mapper/drafter/refiner and a stronger, low-temperature model for critic/scorer.
- Supply credentials only through the configured environment variable. Never
  commit `.env`, keys, raw provider responses, or private source documents.
  Record consent/provenance, redaction verification, provider retention and
  region assumptions, and the exact commit/profile used for each run.
- Set the new run budget to a bounded pilot: at most 70 HTTP/mock attempts,
  120,000 total tokens, and 30 minutes. The selected profile must cap candidate
  count at 5, critique iterations at 1, digest calls at 1, retries at 1, and
  all worker pools so the worst-case planned path remains below 70 attempts.
- Set critique and score concurrency to 1 for the first run to simplify
  attribution; increase only after the serial run is sound.

## Inputs

Run at least one domain with evidence-rich, non-sensitive or redacted material:

- an SOP with named owners, systems, handoffs, volumes, durations, error rates,
  approvals, and controls;
- a small ticket/export sample with stable identifiers and operational context;
- optionally a second domain in German to measure retrieval degradation.

Keep the audited thin DHL description as a negative-control input. It should
produce a low-richness warning and mostly hypothesis-level output, not be used
as evidence that the engine is weak.

## Labelled critic-gate evaluation

Create a fixed, versioned, redacted corpus of at least 20 drafts: 10 grounded
drafts whose refs resolve and whose claims are supported, and 10 deliberately
ungrounded drafts (including unsupported numbers, absence claims, and a prompt-
injection document). Store the expected gate decision and rationale outside the
provider prompt. Run the same corpus through the configured flash critic and a
stronger critic. Report precision, recall, false positives, false negatives,
and abstentions separately. A model's self-reported score is not the label.

## Assertions

### Safety and integrity

- Run completes within the configured call/token/time ceiling or produces a
  typed budget-exhaustion artifact.
- Every published opportunity's evidence refs resolve to `context.json`.
- The deterministic resolvability gate filters unknown ids even when the critic
  returns an empty violation list. Reference existence is not treated as proof
  of semantic claim support.
- Crafted instruction-like text in a source document is treated as data and does
  not cause the critic/scorer to waive grounding violations.
- Summary, manifest, report, and briefs agree on counts, policy decisions,
  usage, and model routing.

### Output quality rubric

Score a labelled sample of published and filtered opportunities from 0–10 on:

1. groundedness;
2. specificity;
3. actionability;
4. auditability;
5. honesty/calibration;
6. non-generic differentiation;
7. presentation polish.

Use at least 10 opportunities across 2–3 domains, with at least two raters who
are blinded to model, run order, and the other rater's scores. Anchor scores as:

- 0–3: mostly unsupported/generic or not usable;
- 4–6: mixed quality, useful only as a discovery lead;
- 7–8: specific and actionable with minor gaps;
- 9–10: independently verifiable, implementation-ready, and well-calibrated.

Require weighted mean >= 7.0 for groundedness and honesty, >= 6.0 for
actionability and specificity, >= 6.0 overall, and no critical unsupported
current-state claim in a published sample. Report per-dimension agreement using
weighted Cohen's kappa or an equivalent predeclared statistic; disagreements of
more than 2 points or any publication decision disagreement require adjudication.
An honest all-filtered result passes if the input is thin and the gate correctly
explains why; publication count and ICE yield are not success targets.

Record each evaluator's evidence refs and whether each claim is observed,
inferred, proposed, benchmarked, or unknown. Do not use the model's own score as
the only quality measure.

### Comparison

Compare the evidence-rich run with the thin-input negative control:

- input-quality score and warning;
- published/filtered ratio (descriptive only, never a success target);
- unresolved refs and grounding violations;
- median and top ICE;
- human-rated groundedness and actionability;
- calls, tokens, wall-clock, and estimated cost.

## Result record

For every live run, save a redacted result record containing the run id, commit
SHA, provider/model names, profile, budget, input profile, aggregate metrics,
quality rubric scores, failures, and reviewer name/date. Store private raw input
and provider payloads outside the repository.

## Product-validation gate

Product readiness requires 2–3 diverse evidence-rich domains, at least 10
reviewable opportunities across the set, two blinded raters with adjudication,
the agreement statistic, the thresholds above, and redacted reference outputs
reviewed against the thin-input negative control. If any privacy, budget,
grounding, or threshold condition is missing, readiness remains an evidence gap.

## Exit criteria

The engineering bar may be marked complete when this plan is executable and the
offline adversarial suite passes. Product readiness must remain an evidence gap
until 2–3 evidence-rich real-provider runs are completed, manually scored by two
blinded raters, and reviewed. A single successful HTTP response is provider
connectivity proof, not output-quality proof.
