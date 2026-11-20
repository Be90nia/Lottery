# LOT-067 Release Readiness v1

This is a fail-closed readiness evaluator, not a deployment switch. It derives a readiness state from the exact release-manifest bytes, nine gate receipts, and locally verifiable evidence files. It never enables collection, serving, Champion mutation, or automatic promotion.

## Gate groups

| Gate | Required evidence domain |
|---|---|
| G0 | Source/build integrity, reviewed workflow definitions, full action commit pins, runtime and dependency lock, SBOM/provenance |
| G1 | Frozen draw snapshot, official-source evidence, parser/coverage receipts, row-level provenance |
| G2 | Exact-support probability engine, conditional-Poisson calibration/sampling, normalization and numerical tests |
| G3 | Preregistration, full target denominator, failed-fit accounting, paired score ledger and multiplicity procedure |
| G4 | Verified same-regime population eligibility and three independently evidenced historical populations; no inferred physical identity |
| G5 | Immutable Champion generation, exactly three eligible compatible slots, all-or-none 3N publication and request semantics |
| G6 | Pre-outcome forecast binding, official outcome validation, append-only feedback and monitoring policy |
| G7 | Atomic publication, CAS/fencing, backup generation, isolated restore drill and measured recovery |
| G8 | Signed provenance, least privilege, secret handling, incident response, rollback and operational monitoring |

Every gate must be present exactly once. A gate can be `PASS`, `FAIL`, `BLOCKED`, or `UNKNOWN`. `PASS` requires at least one evidence file whose bytes match the declared SHA-256, no remaining blockers, and all declared fault-injection receipts passing. Missing, duplicate, stale, malformed, or hash-mismatched evidence fails closed.

## Readiness state machine

- `READY_FOR_OFFLINE_VALIDATION`: G0–G3 pass; scheduled collection, user-facing serving, and automatic promotion are disabled.
- `READY_FOR_SHADOW`: G0–G7 pass; all three Champion slots pass the all-or-none generation checks; `shadow_only=true`; user-facing serving and automatic promotion remain disabled.
- `READY_FOR_PRODUCTION`: reserved for all G0–G8 passing plus protected-environment cryptographic approval. **The v1 production approval verifier is intentionally not implemented, so v1 never emits this state.** A boolean or self-asserted JSON field cannot authorize production.
- `NOT_READY`: any prerequisite is missing, failed, blocked, unknown, inconsistent, or unverifiable.

LOT-042 access always denies readiness. Three slots must have three distinct artifact IDs and content hashes, all eligible and bound to one registry generation. The evaluator does not claim statistical independence from different artifact IDs or labels.

## Inputs and commands

Schemas and policy:

- `schemas/release-manifest-v1.schema.json`
- `schemas/release-gates-v1.schema.json`
- `schemas/readiness-report-v1.schema.json`
- `config/release-readiness-policy-v1.json`

Evidence paths are relative to `--evidence-root`; absolute paths, traversal outside the root, missing files, symlink escapes, and SHA-256 mismatches are rejected.

Build an immutable report:

```bash
python scripts/release_readiness.py build \
  --release-manifest release-manifest.json \
  --gate-results gate-results.json \
  --evidence-root evidence/ \
  --output artifacts/readiness-report.json
```

Recompute and verify every input binding:

```bash
python scripts/release_readiness.py verify \
  --report artifacts/readiness-report.json \
  --release-manifest release-manifest.json \
  --gate-results gate-results.json \
  --evidence-root evidence/
```

The report binds the exact release-manifest and gate-results file bytes, each verified evidence-file digest, the full gate status vector, and all blocking reasons. It is write-once: a conflicting report at the same output path is rejected.

## Current boundary

This evaluator is a contract and local verification harness. It does not yet provide signed approval verification, a protected signing environment, a Champion registry, durable object-store restore, or production deployment integration. Those gates remain `UNKNOWN`/blocked until their own implementation receipts exist. Passing unit tests for this evaluator is not evidence that the system itself is ready.
