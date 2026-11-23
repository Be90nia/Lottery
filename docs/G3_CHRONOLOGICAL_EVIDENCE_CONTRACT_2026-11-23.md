# G3 chronological evaluation evidence contract — 2026-11-23

## Scope

This is the G3 semantic-verifier implementation slice for LOT-074. It makes the typed readiness receipt verifier inspect the contents of experimental-validity evidence rather than accepting arbitrary hash-valid files.

It does not claim that a new 2,649-target evaluation has been run, that the candidate has predictive skill, or that Shadow/production is authorized. LOT-042 remains sealed.

## Frozen LOT-055 protocol

The verifier requires the frozen confirmatory protocol identity:

- Snapshot SHA-256: `9f4cc51b76fd258dd056e0b86f675192d3d9a41c2901f771cab778c65ec2b6aa`.
- Snapshot rows: 2,949.
- Target count: 2,649; first target 09054, last target 26131.
- Minimum training history: 300 rows.
- Every target must use the exact preceding snapshot row as its training cutoff; training count grows from 300 by one per target.
- One candidate and the fixed uniform, expanding-frequency and EWMA comparators; front/back zones are separate.
- Exactly 1,000 non-circular moving-block bootstrap replicates, block length 50 and the preregistered seed.
- Confirmatory family: exactly candidate-vs-uniform for front and candidate-vs-uniform for back; Holm step-down at alpha 0.05.
- Equipment/ball-set fields are excluded from pooled LOT-055 evaluation. LOT-042 access is prohibited.

The verifier requires a pre-outcome confirmatory registration. Any post-outcome amendment belongs to a new exploratory child experiment and cannot inherit confirmatory status.

## Six closed evidence schemas

The G3 receipt check inventory is fixed to six evidence documents:

1. `lottery.g3-preregistration/v1`: frozen protocol, model identities, target/snapshot hashes, bootstrap policy, two-hypothesis family and calibration tolerance.
2. `lottery.g3-chronological-targets/v1`: exact 2,649 target IDs and their per-target preceding training cutoff IDs, snapshot identity, minimum history and leakage/holdout exclusions.
3. `lottery.g3-terminal-ledger-index/v1`: expected denominator of 2,649 × 4 models × 2 zones = 21,192 terminal records, status counts and a SHA-256-bound JSONL ledger.
4. `lottery.g3-baseline-comparison/v1`: exact target-paired NLL means for candidate/uniform/expanding/EWMA, candidate-minus-uniform confidence intervals and non-regression upper bounds.
5. `lottery.g3-holm-control/v1`: the fixed two confirmatory hypotheses, bootstrap identity, raw p-values and Holm-adjusted p-values.
6. `lottery.g3-calibration/v1`: preregistered calibration method and per-zone full-target diagnostics.

## Semantic checks

The verifier currently enforces:

- All six reports bind the same target-manifest hash and compatible model identities.
- Target IDs are ordered, unique, exactly 2,649, and anchored at 09054–26131; their canonical hash must match.
- Every target's training cutoff is the exact preceding draw ID. Training counts must be 300, 301, …, 2,948.
- The JSONL terminal ledger contains exactly 21,192 unique model × zone × target rows. Missing, duplicated, reordered-to-another-target, failed, or invalid terminal outcomes cannot be hidden.
- Each scored record has a finite nonnegative NLL; failed records must have null NLL, never an arbitrary penalty.
- Uniform exact-set NLL is checked against `log(C(35,5))` and `log(C(12,2))` on every target.
- Reported baseline means are recomputed from the full terminal ledger; paired target coverage must be 2,649 in each zone.
- The candidate's 95% interval must be below zero in both zones and the preregistered non-regression upper bounds against expanding/EWMA must be nonpositive.
- The Holm family must contain exactly two hypotheses; adjusted p-values are recomputed from raw p-values and must match the step-down correction. Both co-primary tests and intervals must pass.
- Calibration must use the preregistered method, cover all targets in both zones and remain within the registered tolerance.
- The nested ledger path and digest are verified under the bounded evidence root and must be unique.

## Current boundary / remaining G3 work

This code verifies the structure and arithmetic consistency of the supplied evidence. It does not independently rerun the model fitting, recompute every exact-set probability from source artifacts, or regenerate the moving-block bootstrap samples from per-target score deltas. Those require the separate exact-set evaluator/run artifacts and independent replay. The receipt verifier's SHA-256 checks establish byte integrity, not producer authenticity.

The next implementation pass must connect this semantic contract to the actual LOT-055 frozen evaluator outputs, verify bootstrap resample lineage/replay, and generate real G3 evidence from a complete run. Do not label G3 PASS until those artifacts and a current-head CI run are verified.
