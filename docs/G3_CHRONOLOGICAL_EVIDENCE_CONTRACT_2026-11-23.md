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
- The verifier replays all six 1,000-replicate moving-block comparisons (uniform/expanding/EWMA × front/back) from the per-target score deltas using the preregistered per-zone/per-comparator seeds. It recomputes percentile intervals and the one-sided null-centered p-values before checking the Holm correction.
- Calibration evidence must include 2,649 per-target absolute-error diagnostics in each zone; the reported maximum is recomputed from those values and compared with the preregistered method/tolerance. A summary-only calibration PASS is rejected.
- The candidate's 95% interval must be below zero in both zones and the preregistered non-regression upper bounds against expanding/EWMA must be nonpositive.
- The Holm family must contain exactly two hypotheses; adjusted p-values are recomputed from raw p-values and must match the step-down correction. Both co-primary tests and intervals must pass.
- Calibration must use the preregistered method, cover all targets in both zones and remain within the registered tolerance.
- The nested ledger path and digest are verified under the bounded evidence root and must be unique.


## Existing full-run diagnostic evidence (not confirmatory)

The PR #98 full diagnostic rerun (Actions run `44996717511`, artifact `14749238221`, branch head `a244b5731575a5aced47bcc44ff40870f321a112`) completed all 2,649 targets × 4 model lanes × 2 zones:

- 21,192/21,192 terminal records were present.
- All 21,192 records were `scored`; the prior 10,596 expanding/EWMA `artifact_invalid` records were eliminated by correcting the baseline artifact identity to include the registered solver and optimizer settings.
- The run manifest still labels the run `exploratory_diagnostic` and `confirmatory_eligible=false`, because the solver repair followed observed fit failures. This cannot be relabeled confirmatory.
- Candidate-vs-uniform front: mean NLL delta -0.00887, 95% CI [-0.02032, 0.00087], one-sided p=0.06294.
- Candidate-vs-uniform back: mean NLL delta +0.00059, 95% CI [-0.00033, 0.00151], one-sided p=0.89910.
- Holm-adjusted p-values: front 0.12587; back 0.89910. Neither co-primary zone passes.
- Non-regression against expanding/EWMA fails in the front zone because candidate-vs-EWMA CI upper endpoint is +0.00556. Back-zone non-regression passes.

The result is a useful complete exploratory diagnostic and a negative confirmatory signal, not a G3 PASS and not evidence of predictive advantage. No Champion promotion, serving, or LOT-042 access occurred.

## Implementation verification — 2026-11-23

The semantic verifier is wired into the LOT-074 typed G3 gate. Its terminal-ledger contract now matches the actual LOT-055 normalized ledger fields, including per-record content hashes, model/configuration identity, artifact references, pairing keys, training first/last draw IDs and strict target dates. It rejects missing/duplicate model × zone × target rows, invalid terminal statuses, altered uniform probabilities, score/probability disagreement, mixed run IDs and tampered row hashes.

The verifier independently replays the six moving-block comparisons from the ledger and recorded seed schedule. It does not trust the report's p-values or confidence intervals. Calibration evidence is required to carry all 2,649 per-target diagnostics per zone, with the aggregate maximum recomputed before applying the pre-registered tolerance.

GitHub Actions run #1365 (`45112291638`) passed on the current G3 implementation head:
- 297 unit tests passed; one existing long-form test skipped.
- Workflow security policy passed.
- Windows ledger-lock tests passed.

This closes the G3 semantic-verifier implementation slice. It does not close G3 acceptance: the full historical run is exploratory and fails the co-primary statistics/non-regression criteria, and the current rolling-origin evaluator does not yet emit the required per-target calibration artifact or a typed evidence bundle tied to an approved pre-outcome registration.

## Current boundary / remaining G3 work

This code verifies the structure and arithmetic consistency of the supplied evidence. It does not independently rerun the model fitting, recompute every exact-set probability from source artifacts, or regenerate the moving-block bootstrap samples from per-target score deltas. Those require the separate exact-set evaluator/run artifacts and independent replay. The receipt verifier's SHA-256 checks establish byte integrity, not producer authenticity.

The next implementation pass must connect this semantic contract to the actual LOT-055 frozen evaluator outputs and generate real G3 evidence from a complete run. The bootstrap replay contract is now implemented and independently reproduces the stored full-run diagnostic intervals and p-values exactly. The existing full-run diagnostic still cannot be accepted as confirmatory and has no per-target calibration artifact; its negative statistical result remains a hard blocker. Do not label G3 PASS until those artifacts and a current-head CI run are verified.

## Run-manifest binding and evidence adapter — 2026-11-23

The verifier now requires the normalized terminal ledger to be bound to the immutable LOT-055 run manifest, not only to a caller-supplied ledger hash. It checks:
- The run-manifest file SHA-256 and its internal canonical manifest digest.
- Experiment identity/class and `confirmatory_eligible`; an exploratory child run cannot be relabeled by a receipt.
- Snapshot SHA-256 and row count against the release manifest and preregistration.
- Target-list digest, target count and first/last target IDs against the exact ordered target IDs/dates in the chronology evidence.
- The 1,000 × 50 bootstrap configuration and per-zone/per-comparator seed schedule.
- Expected/actual denominator, terminal status counts, and the run manifest's target-ledger SHA-256 and byte count.
- The complete `model-artifacts.jsonl` byte digest, byte count and 15,894-artifact inventory count; under a v2 release manifest, both the run manifest and model-artifact ledger must also appear in their corresponding immutable release evidence collections.
- The exact eight model × zone configuration identities; every ledger row must match its model configuration and feature-schema hashes.

Added `scripts/build_g3_evidence.py` to adapt immutable LOT-055 run outputs into the six G3 documents. The CLI requires explicit snapshot/run-manifest digests, the frozen snapshot, normalized ledger, model-artifact ledger and a machine-readable registration. It copies the run manifest and ledger byte-for-byte into the evidence directory, computes paired baseline summaries and replayable bootstrap/Holm evidence from the ledger, and never fabricates a calibration result. Without a supplied target-level calibration artifact it emits an explicit `lottery.g3-calibration-blocked/v1` document.

The diagnostic adapter workflow downloads the completed historical run artifact from Actions run `44996717511`, checks out the exact snapshot commit `fb33963442170bd212d039f3debd07bde58feac6`, and builds the evidence bundle. The associated registration record deliberately preserves `experiment_class=exploratory_diagnostic`, `outcomes_observed_at_registration=true`, and `UNSPECIFIED_NO_PREREGISTERED_METHOD` for calibration. It is not a confirmatory registration.

**Calibration diagnostic now implemented:** `marginal-inclusion-ece-10-bin-v1` computes exact first-order inclusion marginals from each target's fitted exponential-family artifact. It uses the exhaustive feature-cell item-inclusion counts already stored by `UniformFeatureTable`, so it does not approximate the model's marginal probabilities with Monte Carlo. For each zone it reports 10 fixed-width reliability bins, per-target Brier scores, overall Brier score, expected calibration error (ECE), and maximum absolute bin gap. The verifier recomputes ECE from the bin counts and rejects malformed or self-inconsistent calibration evidence. Unit tests compare exact marginals against brute-force full-support enumeration on a small support.

**Important limitation:** LOT-055 Issue #18 asks for calibration diagnostics "where meaningful" but did not register this particular marginal-calibration statistic, ten-bin partition or 0.05 tolerance before outcomes. The adapter now computes the diagnostic for research transparency, but labels it `EXPLORATORY_UNREGISTERED`; the historical G3 gate still rejects it. This is first-order marginal calibration only, not calibration of the complete joint subset distribution. A future prospective confirmatory experiment must register the method, bins and tolerance before target outcomes are observed. The method cannot be retroactively attached to the post-outcome diagnostic.

The historical diagnostic still has 21,192/21,192 scored rows but is explicitly exploratory, fails both co-primary candidate-vs-uniform Holm tests, and fails front-zone non-regression against EWMA. Its G3 evidence bundle is therefore expected to remain BLOCKED. No G3 PASS, model promotion, serving or LOT-042 access is authorized.
