# LOT-074 typed offline readiness receipts

This implementation slice adds a typed receipt verifier on top of the structural
LOT-067 evaluator. It is deliberately offline and does not introduce a user
account, login, MFA, human identity provider, or KMS dependency.

## What is verified

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

## What this does not prove

SHA-256 establishes byte integrity, not who produced the bytes or whether a
source is authoritative. This verifier does not authenticate a person, service
account, KMS signer or external data provider. Official draw provenance still
requires the relevant source evidence and independent data checks. No login,
MFA, approval portal, KMS, cloud identity or signed attestation service is
required for the offline MVP receipt contract.

The helper returns `READY_FOR_SHADOW` only when the full typed receipt inventory
is present and valid and LOT-042 is explicitly isolated. This is a receipt
contract result, not authorization to enable scheduled collectors, serving,
promotion, rollback or production. The existing LOT-067 evaluator remains the
release-state authority until the v2 manifest and gate-specific contracts are
fully integrated and reviewed. Production readiness remains disabled.

## Files

- `src/lottery/readiness_receipts.py`: typed receipt and evidence verification.
- `schemas/gate-receipt-v1.schema.json`: gate-specific receipt envelope.
- `schemas/fault-receipt-v1.schema.json`: fault and recovery receipt envelope.
- `tests/test_readiness_receipts.py`: deterministic negative and positive tests.

Run the focused tests with:

```sh
python -m unittest tests.test_readiness_receipts -v
```
