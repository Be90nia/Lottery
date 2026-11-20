# LOT-060: Immutable Champion lifecycle (offline implementation slice)

This module adds a filesystem-backed lifecycle registry for exact-subset model
artifacts. It is intentionally separate from the legacy LOT-042 forecast ledger.

## State and publication model

- Model artifacts are validated with the shared LOT-071 RFC 8785 serializer and
  stored write-once under their SHA-256 content ID.
- A slot is keyed by the exact pair `(population_key, zone)`; the caller must
  provide a regime-scoped population key for set-conditioned models. No
  physical ball-set identity is inferred by this module.
- Registry changes require an expected generation (compare-and-swap).
  Concurrent or stale workers fail without changing the Champion pointer.
- The lifecycle event ledger is append-only and hash-chained. Registry writes
  use a write-ahead journal so a process interruption between pointer
  publication and event append is recoverable on the next operation.
- Candidate validation receipts are stored as immutable canonical JSON and
  bind the exact artifact, evaluation manifest, target list, denominator and
  all preregistered numerical/statistical gates.
- Promotion and restoration require an injected protected approval verifier.
  Missing verifier, invalid signature, stale generation, or mismatched receipt
  scope fails closed. The approval receipt binds the exact evaluation receipt
  hash, not merely a mutable manifest name.
- Rejection and suspension preserve all artifacts and history. A suspended
  slot retains its Champion pointer for audit but cannot resolve for serving.
- Verified set-conditioned population keys use the canonical form
  `<equipment_regime_id>|reported_set_index=<1|2|3>`. The signed evaluation
  receipt binds the population evidence digest and the exact filtered training
  snapshot hash; front/back artifacts for one index must share that training
  population, while the three reported indices must have three distinct
  training populations and distinct zone artifacts.
- Verified set-conditioned Champions cannot be promoted one zone at a time.
  `promote_three_slot_generation` atomically publishes exactly six artifacts
  (indices 1/2/3 × front/back) under one registry generation, with one shared
  evidence/evaluation/target manifest and six scoped approvals.
- `restore_three_slot_generation` performs the corresponding atomic rollback.
  Individual `restore_retired` is restricted to pooled equipment-blind slots.
- Three-slot resolution requires exactly three distinct population keys and
  both zones for every key (six immutable artifacts), all carrying the same
  atomic Champion generation. Every approval signature is reverified at
  resolution time.
  Missing or suspended slots reject the entire resolution.

## Current boundary

This is an offline lifecycle primitive, not a production registry backend.
The repository does not yet provide the protected-environment signing/KMS
verifier, durable object store, independent backup/restore drills, or a
user-facing exact-subset serving API. The verifier is therefore an explicit
dependency and is never replaced by a JSON `approved: true` flag. The module
does not enable collection, fitting, promotion workflows, or serving.

LOT-042 remains untouched. No prospective holdout is read or modified.
