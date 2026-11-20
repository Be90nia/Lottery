# LOT-063 prospective forecast/outcome scoring ledger — implementation slice

This PR adds an append-only prospective ledger with separate forecast, outcome
version and score records.

## Implemented

- One immutable forecast record per artifact × target draw × zone × population
  key; it binds the artifact/distribution hashes, training snapshot/cutoff,
  registry generation, policy, source-evidence digest, code commit and runtime.
- Forecasts issued after cutoff or using training data not strictly before the
  target are retained as ineligible with explicit reason codes.
- Official outcome observations require a protected evidence-verifier callback
  and legal front/back subsets. Non-authoritative observations are preserved
  with a reason but cannot be scored.
- Outcome corrections append a new version that explicitly supersedes the
  current version; prior outcomes and prior scores remain immutable.
- Exact-set scoring is per forecast artifact × target × zone, using a supplied
  artifact probability evaluator; uniform exact-set NLL is recorded on the
  identical outcome.
- Invalid, positive, zero or non-finite log probabilities fail closed; no
  arbitrary penalty score is assigned.
- Duplicate forecast/outcome/score retries are idempotent; changed forecast
  content cannot rewrite the same logical key.
- Hash-chained canonical events expose ledger edits and reordering.

## Deliberate limits

- Raw official source bytes remain in the separate source-evidence archive;
  this ledger stores their SHA-256 reference only.
- Evidence and artifact probability verification are injected protected
  callbacks; this PR does not supply official credentials or model artifact
  loading.
- Score execution failures are surfaced as errors but a separate immutable
  score-failure-attempt ledger is still required.
- This does not enable model refresh, Champion mutation, rollback or serving.
- Ticket hit rates and user batch counts are not used as model-level scoring
  denominators.

LOT-042 remains untouched.
