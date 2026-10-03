# Real-provider evaluation runbook

This runbook executes the evidence plan in
[`02-REAL-PROVIDER-TEST-PLAN.md`](02-REAL-PROVIDER-TEST-PLAN.md). It is an
opt-in evaluation, not a production deployment or a product-readiness claim.

## Safety gate

Use a dedicated workspace and a provider profile with a dedicated API key. Use
only redacted, non-production inputs for which the operator has consent. Keep
the workspace, raw provider payloads, and raw source documents outside Git.

The harness refuses to call a provider unless both `--live` and
`--privacy-approved` are present. It also rejects a profile whose budget is
above the default run budget (200 attempts, 1,500,000 tokens, 40 minutes), and requires serial critique
and score workers for the pilot.

Before running, record privately:

- input owner, consent, redaction check, and retention/region assumptions;
- provider, model, profile, and repository commit;
- the exact workspace path and the person responsible for deleting it.

## Provider profiles

Create a local, ignored `miner.toml` in the dedicated workspace. The first
profile is the flash/normal critic; the second is a stronger critic. Keep the
same mapper/drafter/refiner/scorer settings across the pair where practical.

```toml
[providers.openrouter]
base_url = "https://openrouter.ai/api/v1"
api_key_env = "OPENROUTER_API_KEY"
supports_json_mode = true

[profiles.live_flash.roles]
critic = { provider = "openrouter", model = "<flash-model>", max_tokens = 1000 }

[profiles.live_strong.roles]
critic = { provider = "openrouter", model = "<stronger-critic-model>", max_tokens = 1000 }

[profiles.live_flash.concurrency]
critique = 1
score = 1

[profiles.live_strong.concurrency]
critique = 1
score = 1

[profiles.live_flash.budget]
max_attempts = 200
max_tokens = 1500000
max_seconds = 2400

[profiles.live_strong.budget]
max_attempts = 200
max_tokens = 1500000
max_seconds = 2400
```

Set the key only in the shell or a secret manager:

```bash
export OPENROUTER_API_KEY='...'
```

## Bounded smoke run

Run one evidence-rich SOP or ticket export first. The `--result` path should
be outside the repository. The result contains redacted metadata and aggregate
usage, not prompts or provider responses.

```bash
uv run python scripts/live_provider_eval.py smoke \
  --live --privacy-approved \
  --workspace /private/eval/automation-miner-rich \
  --file /private/eval/redacted-sop.md \
  --profile live_flash \
  --iterations 1 \
  --result /private/eval/results/rich-smoke.json
```

Repeat with the audited thin DHL description as the negative control. Expect a
low input-richness signal and discovery-hypothesis framing; publication count
is descriptive, not a success target.

```bash
uv run python scripts/live_provider_eval.py smoke \
  --live --privacy-approved \
  --workspace /private/eval/automation-miner-thin \
  --idea 'Redacted parcel delivery operations' \
  --profile live_flash \
  --iterations 1 \
  --result /private/eval/results/thin-smoke.json
```

Stop if the run exceeds its budget, writes a non-terminal artifact, publishes
an opportunity with unresolved evidence references, or exposes unredacted
source/provider content. A budget-exhausted result is an honest operational
outcome; it is not a quality pass.

## Critic-gate corpus

The fixed corpus in
[`critic-gate-corpus.v1.json`](critic-gate-corpus.v1.json) has 10 expected-pass
grounded cases and 10 expected-block cases, including unsupported numbers,
absence claims, policy conflicts, and a prompt-injection document. The expected
labels and rationales are not sent to the model.

Run it through both configured critic profiles. The two evaluations share one
aggregate ceiling of 200 attempts, 1,500,000 tokens, and 40 minutes; the 1,000
token critic response cap leaves room for the two 20-case passes and bounded
validation retries:

```bash
uv run python scripts/live_provider_eval.py critic-gate \
  --live --privacy-approved \
  --workspace /private/eval/automation-miner-rich \
  --profile live_flash \
  --strong-profile live_strong \
  --corpus docs/improvement/critic-gate-corpus.v1.json \
  --result /private/eval/results/critic-gate.json
```

Review precision, recall, false positives, false negatives, and abstentions
for each profile. An abstention is a failed or budget-exhausted model case, not
a silently successful block.

## Human quality review

Select at least 10 opportunities across 2–3 domains, including published and
filtered outputs where available. Give each rater a copy of the briefs and
evidence without model/profile identity or the other rater's scores. Use the
seven dimensions and 0–10 anchors in the test plan. Record evidence refs and
whether claims are observed, inferred, proposed, benchmarked, or unknown.

Start from [`real-provider-rating-template.v2.json`](real-provider-rating-template.v2.json)
outside the repository, replace the placeholders, and run:

```bash
uv run python scripts/live_provider_eval.py score \
  --ratings /private/eval/results/blinded-ratings.json \
  --result /private/eval/results/rating-summary.json
```

The analyzer reports per-dimension means, quadratic-weighted Cohen's kappa,
disagreements over two points, publication-decision disagreements, critical
unsupported current-state claims, and the predeclared thresholds. Resolve every
item in `adjudication_required` before making a product decision.

## Evidence package

Keep these redacted records together outside the source workspace:

1. `rich-smoke.json` and `thin-smoke.json`;
2. `critic-gate.json`;
3. `rating-summary.json` and the adjudication record;
4. consent/redaction/provenance record and the exact commit SHA;
5. a short reviewer memo mapping each threshold to evidence.

The engineering bar can be marked executable after the offline harness gates
pass. Product readiness remains **not claimed** until 2–3 diverse evidence-rich
runs, at least 10 human-reviewed opportunities, two blinded raters,
adjudication, and the stated thresholds are all evidenced.
