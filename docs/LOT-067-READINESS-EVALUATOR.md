# LOT-067 release-readiness evaluator

This slice implements an offline, fail-closed evaluator. It does not claim the
system is ready merely because code or an issue exists.

## Machine-readable contracts\n\nThe versioned policy and JSON Schemas live in `schemas/readiness-policy-v1.json`, `schemas/release-manifest-v1.schema.json`, `schemas/readiness-gate-results-v1.schema.json`, `schemas/readiness-fault-results-v1.schema.json`, and `schemas/readiness-report-v1.schema.json`. Unit tests assert that the executable evaluator constants match the policy file.\n\n## Inputs

- A release manifest pins an immutable source commit, workflow policy,
  dependency lock, canonical snapshot digest, and explicit LOT-042 isolation.
- Gate results contain exactly one result for each G0–G8. A PASS requires at
  least one evidence file under the supplied evidence root, with a matching
  SHA-256 digest.
- Fault results contain at most one result for each F01–F15. A fault PASS
  requires an explicit injection, matching expected/observed terminal state,
  and a verified evidence file.

Evidence paths are relative, traversal and symlinks are rejected, and files
must resolve beneath the evidence root. Duplicate JSON keys, duplicate gate
or fault IDs, unknown IDs, mutable release refs, missing receipts and digest
mismatches fail closed.

## Derived states

- `NOT_READY`: any required offline gate/fault is absent, blocked, failed,
  unverifiable, or LOT-042 isolation is not explicitly false.
- `READY_FOR_OFFLINE_VALIDATION`: G0–G3 and the core source/snapshot,
  optimizer and partial-evaluation fault cases F01/F03/F04/F05 pass.
- `READY_FOR_SHADOW`: all G0–G8 and all F01–F15 pass.
- `READY_FOR_PRODUCTION` is deliberately not emitted. Version 1 has no
  protected cryptographic production-approval verifier; a JSON boolean cannot
  authorize production.

## CLI

```sh
python scripts/evaluate_release_readiness.py \
  --manifest release-manifest.json \
  --gate-results gate-results.json \
  --fault-results fault-results.json \
  --evidence-root ./release-evidence \
  --output readiness-report.json
```

The output is canonical JSON and no-clobber. Exit code 0 means offline or
shadow readiness; exit code 2 means NOT_READY or invalid evidence. The report
binds the exact manifest, gate-results and fault-results digests and lists all
verified evidence and blockers.

This evaluator is a policy mechanism, not evidence that any gate has passed.
The repository's current snapshot remains unauthenticated by an independent
official-source audit; LOT-042 remains sealed.
