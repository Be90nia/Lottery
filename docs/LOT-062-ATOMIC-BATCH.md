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
  artifact IDs, protected master-seed reference and commitment, RNG algorithm,
  sampler version and producer runtime/commit.
- Derives separate deterministic front/back slot seeds with domain-separated
  HMAC-SHA256 over population key, zone and exact artifact ID. The sampler
  receives only derived seed bytes; the manifest stores stream IDs and the
  protected seed reference, never the raw master seed.
- Includes the full sorted registry snapshot and its SHA-256 identity, per-zone
  artifact training cutoff/inventory/evidence/evaluation/approval provenance,
  and stable ticket IDs bound to request, population slot and ticket contents.
- Returns a published status and the immutable UTC pointer-publication timestamp;
  the timestamp is preserved by idempotent retries and crash recovery.
- Enforces a conservative offline maximum of 100 tickets per slot (300 total)
  before resolving the registry or invoking the sampler.
- Holds the Champion registry CAS lock through the batch-pointer publication.
  A registry change after object commit but before pointer publication leaves
  only an unreferenced immutable object for reconciliation; it cannot publish
  a stale-generation batch.
- Re-resolves the Champion generation after sampling and blocks publication
  if the registry changed during generation; a final generation guard closes
  the check-to-publish race.
- Stages, validates, commits and publishes one immutable batch manifest via a
  single CAS pointer. A failure before the pointer commit exposes no partial
  batch.
- Idempotency key reuse with changed ticket bytes is rejected by the storage
  layer.

## Deliberate limits

- The sampler is injected; this PR verifies and passes the per-slot seed inputs
  and pinned algorithm/version but cannot prove an injected callback actually
  consumes those seeds or samples from the bound artifacts. The production
  sampler must be a separately verified adapter over the exact model artifacts.
- The 100-ticket ceiling is a conservative offline cap, not a production load
  certification; raise it only after measured resource and latency testing.
- This PR does not claim three statistically independent ball populations
  or infer physical set identity.
- The protected seed itself is not stored in the manifest; only its commitment
  digest and RNG algorithm are recorded.
- This is a local offline publication adapter, not production serving.
- A production release still requires remote durable storage, backup/restore,
  signing/KMS, security gates, source evidence and end-to-end release readiness.

LOT-042 remains inaccessible and no automatic promotion or public serving is
enabled.
