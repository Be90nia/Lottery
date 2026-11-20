# LOT-062 atomic three-slot batch publisher — implementation slice

This PR adds an offline all-or-none publisher that composes the LOT-060
verified Champion resolver with the LOT-065 immutable object store.

## Implemented

- Requires a fully verified, non-suspended three-population × front/back
  Champion generation and protected approval verifier.
- Samples all three population slots before writing any storage object.
- Requires exactly N legal front/back tickets per slot and exactly 3N total.
- Retains duplicate tickets and reports within-slot and cross-slot duplicate
  counts; it never silently deduplicates.
- Binds the batch manifest to the exact registry/Champion generation, six
  artifact IDs, seed commitment, RNG algorithm, sampler version and producer
  runtime/commit.
- Re-resolves the Champion generation after sampling and blocks publication
  if the registry changed during generation.
- Stages, validates, commits and publishes one immutable batch manifest via a
  single CAS pointer. A failure before the pointer commit exposes no partial
  batch.
- Idempotency key reuse with changed ticket bytes is rejected by the storage
  layer.

## Deliberate limits

- The sampler is injected; this PR does not claim three statistically
  independent ball populations or infer physical set identity.
- The protected seed itself is not stored in the manifest; only its commitment
  digest and RNG algorithm are recorded.
- This is a local offline publication adapter, not production serving.
- A production release still requires remote durable storage, backup/restore,
  signing/KMS, security gates, source evidence and end-to-end release readiness.

LOT-042 remains inaccessible and no automatic promotion or public serving is
enabled.
