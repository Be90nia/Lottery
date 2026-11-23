# LOT-074 typed offline readiness receipts

This implementation slice adds a typed receipt verifier on top of the structural
LOT-067 evaluator. It is deliberately offline and does not introduce a user
account, login, MFA, human identity provider, or KMS dependency.

## What is verified

- The v2 release manifest pins the immutable source commit and references the
  workflow policy, dependency lock, readiness policy, canonical snapshot,
  source-evidence ledger, runtime/toolchain, SBOM, security scan, experiment
  registration/evaluation manifests, Champion registry, model artifacts,
  sampler/RNG identity, storage receipts, backup generation and independent
  restore receipt. Every reference is resolved beneath the evidence root and
  checked against actual bytes; duplicate paths are rejected.
- Each G0-G8 result references one JSON receipt with a gate-specific
  `receipt_type`, exact `gate_id`, release ID, source commit and digest of the
  exact release manifest.
- Gate receipts must contain the complete gate-specific check inventory (for
  example G0 pins source/workflow/dependencies/runtime/SBOM; G2 checks full
  support, normalization, exact probabilities and numerical stability). Every
  check explicitly passes and references its own evidence file and SHA-256.
  The caller does not supply an authoritative PASS field.
- Check evidence files are verified byte-for-byte, and cannot be reused across
  checks, gates or fault receipts.
- Each F01-F15 result references a fault-specific receipt binding the fault ID,
  injection method, expected and observed states, recovery action, runner
  commit, UTC timestamp, and evidence file digest.
- A fault receipt is accepted only when the observed state matches the expected
  state and output publication is explicitly `none`.
- Receipt and evidence files are checked by SHA-256 under a bounded evidence
  root. Paths must be canonical relative POSIX paths and symlinks are rejected.
- Every gate and fault must have exactly one receipt; receipt bytes and paths
  cannot be reused across gates/faults.
- All receipts bind the same immutable release manifest and source commit.
  Mutable release refs are rejected.

## G2 numerical evidence semantics

G2 no longer accepts arbitrary hash-valid text files for its numerical checks.
The verifier parses strict JSON and validates:
- Full-support counts against the exact front `C(35,5)=324632` and back
  `C(12,2)=66) supports.
- Probability normalization, nonnegative minimum probability and bounded
  numerical error (at most `1e-12`) for both zones.
- Exact probability oracle coverage over every legal subset in both zones.
- Conditional-Poisson algorithm identity and finite probability/marginal oracle
  errors.
- Deterministic backward-DP sampler identity, fixed-seed replay and zero
  invalid samples.
- Numerical stress coverage with no non-finite outputs and bounded normalization
  error.

A hash-valid report with a probability sum of 0.5 is rejected. These are
content/contract checks; evidence producer authenticity is still not claimed.

## Champion registry cross-check

The lifecycle API also exposes a read-only
`ChampionLifecycle.audit_three_slot_generation(population_keys)` check. It
loads the real registry snapshot and immutable artifacts/evaluation/approval
receipts, then verifies all six front/back pointers across reported-set indices
1/2/3: one registry generation, one Champion generation, distinct population
training snapshots, paired front/back training and regime-evidence hashes,
matching artifact/evaluation scope, and valid approval-receipt structure.

This is intentionally not the protected resolver: it does not claim approval
signature authenticity and returns both
`approval_authenticity_verified=false` and `readiness_authorized=false`.
The existing `resolve_three_slot_generation` remains separately protected by
the injected approval verifier.

## What this does not prove

SHA-256 establishes byte integrity, not who produced the bytes or whether a
source is authoritative. This verifier does not authenticate a person, service
account, KMS signer or external data provider. Official draw provenance still
requires the relevant source evidence and independent data checks. No login,
MFA, approval portal, KMS, cloud identity or signed attestation service is
required for the offline MVP receipt contract.

The helper never returns a readiness authorization. When all typed receipt
files are present and valid it reports `receipt_completeness=COMPLETE`, while
`readiness=NOT_READY`, `shadow_authorized=false` and
`production_ready=false`. LOT-042 access changes completeness to
`BLOCKED_LOT042`. This avoids treating self-authored, hash-valid receipts as
proof that a gate is operationally satisfied. The existing LOT-067 evaluator
remains the release-state authority until the v2 manifest, gate-specific
evidence semantics and source provenance are fully integrated and reviewed.

## Files

- `src/lottery/readiness_receipts.py`: typed receipt and evidence verification.
- `schemas/gate-receipt-v1.schema.json`: gate-specific receipt envelope.
- `schemas/fault-receipt-v1.schema.json`: fault and recovery receipt envelope.
- `tests/test_readiness_receipts.py`: deterministic negative and positive tests.

Run the focused tests with:

```sh
python -m unittest tests.test_readiness_receipts -v
```


## CLI integration

The existing readiness CLI exposes the typed receipt path without changing the
legacy structural v1 mode:

```sh
python scripts/evaluate_release_readiness.py \
  --manifest release-manifest-v2.json \
  --gate-results typed-gate-index.json \
  --fault-results typed-fault-index.json \
  --evidence-root ./release-evidence \
  --output receipt-completeness.json \
  --typed-receipts
```

Exit code 0 means the typed receipt inventory and referenced bytes are complete.
It does **not** mean the release is ready: the report still says
`readiness=NOT_READY`, `shadow_authorized=false` and
`production_ready=false`. Exit code 2 means missing, invalid or blocked
receipt evidence.

## G3 semantic evidence integration (2026-11-23)

The G3 semantic verifier now cross-binds its terminal score ledger and complete model-artifact ledger to a hash-verified LOT-055 run manifest, including the exact snapshot, target-list digest, experiment class/eligibility, bootstrap seed schedule, denominator/status counts, ledger bytes, model-artifact bytes/count and all eight model × zone configuration identities. Under a v2 release manifest, both the run manifest and model-artifact ledger must also be present in their immutable release evidence inventories. An exploratory run manifest cannot be relabeled as confirmatory by a G3 receipt.

`scripts/build_g3_evidence.py` adapts a frozen snapshot, immutable run manifest, normalized terminal ledger, model-artifact ledger and explicit registration into the six G3 evidence documents. It recomputes baseline means, paired moving-block intervals and Holm inputs from the terminal ledger. It also computes exact first-order item-inclusion marginals from the candidate model artifacts and reports Brier score, 10-bin reliability, ECE and maximum bin gap. The verifier recomputes ECE from bin counts and enforces the fixed method/tolerance contract.

The diagnostic adapter workflow is pinned to the existing completed run artifact `44996717511` and frozen snapshot commit `fb33963442170bd212d039f3debd07bde58feac6`. The run remains `exploratory_diagnostic`, `confirmatory_eligible=false`; the generated registration record preserves that boundary. This workflow is an evidence adaptation, not a new confirmatory evaluation and not a readiness authorization.

Calibration remains an explicit G3 blocker for the historical run: exact marginal-inclusion diagnostics are now generated, but LOT-055 did not preregister the ten-bin method or its tolerance before observing outcomes. The historical calibration report is therefore `EXPLORATORY_UNREGISTERED` and cannot satisfy G3. This is marginal calibration, not full joint-subset calibration. Do not relabel the historical experiment or retrofit a confirmatory claim.
