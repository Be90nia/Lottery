# LOT-063 prospective forecast/outcome scoring ledger — implementation slice

This PR adds an append-only prospective ledger with separate forecast, outcome
version and score records.

## Implemented

- One immutable forecast record per artifact pair × target draw × zone ×
  population key; it binds both front/back artifact and distribution hashes,
  active registry snapshot/generation/lifecycle state, scheduled target time,
  cutoff and timezone source, model/scoring policy, training snapshot/range/row
  count, regime-evidence manifest, code commit and runtime.
- Forecasts issued after cutoff, with training data not strictly before the
  target, or with fewer than 300 training rows are retained as ineligible with
  explicit reason codes.
- Official outcome observations require a protected evidence-verifier callback
  and legal front/back subsets. Raw evidence object reference, requested/final
  HTTPS URLs, retrieval timestamp, evidence locator, parser version, authority
  and conflict group are retained. Non-authoritative observations are preserved
  with a reason but cannot be scored.
- Outcome corrections append a new version that explicitly supersedes the
  current version; prior outcomes and prior scores remain immutable.
- Exact-set scoring is per forecast artifact × target × zone, using a supplied
  evaluator receipt that must bind the exact artifact hash and attest full-support
  normalization; uniform exact-set NLL is recorded on the identical outcome.
- Invalid, positive, zero or non-finite log probabilities fail closed; no
  arbitrary penalty score is assigned.
- Duplicate forecast/outcome/score retries are idempotent; changed forecast
  content cannot rewrite the same logical key.
- Hash-chained canonical events expose ledger edits and reordering.
- Coverage reports separate ineligible forecasts, pending/invalid outcomes,
  score-pending forecasts, completed score revisions and failed score attempts.

## Deliberate limits

- Raw official source bytes remain in the separate source-evidence archive;
  this ledger stores their SHA-256, immutable object reference and retrieval
  metadata, but does not duplicate the raw bytes.
- Evidence and artifact probability verification are injected protected
  callbacks; score receipts must attest the exact artifact hash and full-support
  normalization. This PR does not supply official credentials or model loading.
- Probability-evaluator failures and invalid probability outputs are
  retained as immutable `score_failed` attempts with stable failure codes;
  they never receive an artificial NLL.
- Expected forecast slots must be pre-registered before cutoff; issuance
  must match that expectation. The cutoff finalizer appends an immutable
  missing-at-cutoff terminal record and prevents later backfill. Coverage
  reports expected, issued, missing and unresolved denominators. Automated
  scheduler integration to register every slot and invoke the finalizer remains.
- This does not enable model refresh, Champion mutation, rollback or serving.
- The existing operational forecast/outcome ledger remains the raw ingestion
  and ticket-provenance layer; this exact-subset ledger is a separate statistical
  artifact × target × zone scoring layer, not a replacement.
- Ticket hit rates and user batch counts are not used as model-level scoring
  denominators.

LOT-042 remains untouched.
