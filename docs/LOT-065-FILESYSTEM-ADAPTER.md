# LOT-065 filesystem storage adapter — implementation slice

This PR adds an offline filesystem-backed storage adapter for deterministic,
local integration and fault-injection tests. It is deliberately not represented
as a production durable-storage deployment.

## Implemented

- Deterministic operation IDs derived from opaque idempotency keys.
- Staged immutable byte objects with byte-length and SHA-256 verification.
- Explicit semantic/bytes-only validation receipts.
- Content-addressed immutable object publication and commit receipts.
- Atomic compare-and-swap pointer replacement under the repository's
  cross-process ledger lock.
- Pointer read-back verification against the immutable commit receipt and
  object bytes.
- Read-only reconciliation of staged, validated, committed, and referenced
  objects, including missing or corrupt publication receipts after a pointer
  replacement. A crash window is visible until the same operation is retried
  and its immutable publication receipt is recovered. The pointer and receipt
  carry the same immutable UTC publication timestamp, which survives retries.

## Deliberate limits

- A local filesystem is one failure domain; it is not an independent backup.
- No cloud object-store adapter, object lock, KMS, encryption, key recovery,
  backup schedule, isolated restore drill, or measured RPO/RTO is included.
- The adapter does not enable scheduled ingestion, Champion promotion, or
  user-facing prediction serving.
- A bytes-only validation receipt proves byte integrity only; domain-specific
  callers must supply a semantic validator before commit.
- Reconciliation never repairs, adopts, deletes, or quarantines automatically.

## Required next work

1. Add a separately authenticated/versioned object-store backend and distinct
   staging/commit/pointer identities.
2. Bind fencing tokens to every mutable pointer operation.
3. Extend crash-recovery testing to concurrent writers and interrupted
   operations that are superseded before receipt reconciliation.
4. Add backup manifests, independent-domain backup, key recovery and isolated
   restore drills before assigning RPO/RTO.
5. Exercise crash, concurrency, corruption, duplicate-delivery, and stale-worker
   fault injection on the selected production backend.
