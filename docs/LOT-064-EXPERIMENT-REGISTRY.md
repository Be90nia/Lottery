# LOT-064 immutable experiment registry — implementation slice

This PR adds an offline, append-only preregistration and trial-history registry.

## Implemented

- Content-addressed preregistration records using the shared RFC 8785 JCS
  canonicalizer.
- Confirmatory registration requires a protected approval-verifier callback
  bound to the exact specification digest.
- Fixed target manifests, training cutoff, source/feature/snapshot hashes,
  bootstrap policy, multiplicity family and complete trial configuration plan.
- LOT-042 holdout access is rejected; targets must be strictly later than the
  declared training cutoff.
- Trial starts must match one of the predeclared configurations.
- Every retry receives a distinct attempt ID; failed, timed-out, invalid and
  abandoned attempts remain in the append-only event history.
- Terminal trial results cannot be overwritten.
- Child experiments created after parent results were observed must be
  explicitly exploratory.
- Hash-chained canonical event records make event mutation detectable.
- Population claims are limited to explicit evidence classes; the registry
  does not infer statistical independence from three model labels.

## Deliberate limits

- This is an offline local registry, not a multi-writer remote database.
- Production signing identity, KMS/HSM integration and protected reviewer
  workflow are not included; absent verifier fails closed.
- The registry does not decide whether source evidence proves physical ball-set
  identity or causal independence. It only binds the supplied evidence digest.
- It does not authorize use of LOT-042 or model promotion.

## Remaining work

1. Add protected reviewer identity and key rotation/revocation workflow.
2. Bind trial attempts to immutable build provenance and durable object-store
   commit receipts.
3. Add cross-process crash recovery and reconciliation for event-ledger
   partial writes.
4. Integrate the registry with the rolling-origin evaluator and release gate.
5. Keep all three-slot statistical claims blocked until independent population
   evidence and identical-eligibility paired evaluation exist.
