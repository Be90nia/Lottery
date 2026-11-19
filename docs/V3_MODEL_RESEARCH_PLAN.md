# V3 predictive model research plan

Date: 2026-11-18  
Tracking: [LOT-050](https://github.com/Be90nia/Lottery/issues/10)

## Purpose and course correction

The primary objective is to test whether any information available before a draw improves calibrated number-inclusion probabilities beyond the legal uniform baseline. Prize accounting and source-conflict adjudication are separate workstreams; they must not become substitutes for predictive-model research.

No model is assumed to have an edge. Existing evidence is negative or inconclusive:
- On the 2,901-draw legacy candidate, expanding frequency loses to uniform in both zones.
- EWMA's tiny front-zone point improvement has a paired interval crossing zero, while back-zone scores deteriorate.
- The apparent early front-zone frequency advantage reverses in later calendar eras.
- The legacy data source is candidate-unverified, and these historical results are exploratory.

## Dataset lanes

1. `data/processed/draws-20261118.jsonl`: 2,949 selected-number/date records from the immutable archived API snapshot. This is the preferred current historical dataset for number-only diagnostics, subject to the archive's stated provenance limitations. The 48 records beyond the legacy candidate are already-known historical outcomes, not a prospective holdout.
2. `data/candidates/legacy_draws.jsonl`: 2,901 records with additional legacy fields such as order/equipment. Use only for explicitly labeled candidate-data sensitivity checks. Do not treat its order/equipment fields as verified physical metadata.
3. Prize rows: excluded from number-prediction features and targets. Their source conflicts do not invalidate selected-number/date fields by themselves.

## Phase A — baseline replication

Run the existing fixed rolling-origin benchmark on the 2,949-draw selected-number snapshot using unchanged settings:
- minimum training history: 300 draws;
- expanding-frequency shrinkage: 100 pseudo-draws;
- EWMA half-life: 100 draws;
- models: uniform, expanding frequency, EWMA;
- metrics: per-number Brier and Bernoulli log loss, with paired moving-block intervals.

This is an exploratory extension of the historical evaluation, not an untouched test. Preserve the legacy-candidate result alongside it and record both dataset hashes. Do not tune alpha or half-life based on this extension.

## Phase B — R1–R4 adjacent-draw dependence diagnostics

Use lag (r in {1,2,3,4}), where lag 1 means the immediately preceding draw. Analyze front and back zones separately.

Predeclared statistics:
1. **Same-number recurrence:** for every number, compare observed joint inclusion (I_{t,n}I_{t-r,n}) with the independent-draw expectation ((k/N)^2). Also report zone-level repeat counts per draw.
2. **Lagged cross-number transition:** for every ordered pair ((a,b)), compare (I_{t-r,a}I_{t,b}) with its legal independent-draw expectation. Preserve direction; do not collapse (a 	o b) and (b 	o a).
3. **Set overlap:** number of shared values between draw (t-r) and draw (t), compared with the exact hypergeometric overlap distribution for two independent fixed-size draws.
4. **Temporal stability:** report the same fixed statistics in predeclared calendar blocks only as a descriptive robustness view; do not select a favorable era after seeing results.

Multiplicity:
- Define the full family before computation: four lags × two zones × all same-number hypotheses, plus four lags × two zones × all ordered cross-number hypotheses.
- Apply Holm correction across the complete family, not separately within a chosen lag or zone.
- Use a legal without-replacement permutation/simulation null that preserves each draw's zone size. For temporal dependence tests, permute whole draw rows within the specified eligible series or use a circular/block shift that breaks alignment while preserving each draw's internal selected set.
- Report raw counts, expected values, effect sizes, raw p-values, adjusted p-values, and Monte Carlo uncertainty/seed where simulation is used.

A statistically unusual transition is a diagnostic, not evidence of manipulation and not automatically a useful forecast feature.

## Phase C — lag-feature predictive experiment

Only after Phase B's test family and implementation are frozen:
- Construct features using strictly earlier draws only.
- Candidate family: lagged same-number inclusion indicators at lags 1–4, lagged zone overlap summaries, and optionally a shrinkage-weighted recurrence count.
- Do not include draw-order, equipment, prize, sales, or promotion fields.
- Use regularization/shrinkage fixed in advance. Avoid one free coefficient per arbitrary transition unless sample size and correction support it.
- Compare uniform, expanding, EWMA, and lag-feature model on the same rolling-origin targets.
- Primary metric: per-number Brier; secondary: Bernoulli log loss. Report paired moving-block uncertainty and full feature-family multiplicity/selection controls.
- A feature may be retained only if the predeclared comparison supports out-of-sample improvement; in-sample significance is insufficient.

## Phase D — order/equipment research gate

The legacy candidate contains 2,341 structurally valid order rows and 2,336 nonzero equipment codes. The upstream project code directly fetched the official Sporttery history API and read `lotteryUnsortDrawresult` / `lotteryEquipmentCount`. Sixteen purposive official-page crosswalks and five matches from a reproducible stratified random audit sample now match the legacy values exactly. However, the raw API response bodies and row-level hashes were not retained; eleven rows in the random sample did not have an official DLT page URL located in the current search pass; and the remaining 2,320 order-bearing rows are not directly reconciled.

The official provincial announcements label the sequence “本期出球顺序” and identify equipment codes as numbered draw-ball sets (codes 1, 2, and 3 are all cross-checked). This validates the published meaning for the crosswalked rows, not the complete legacy history or every operational detail of the physical extraction process.

- Do not use the full legacy history for confirmatory position/equipment inference yet.
- Complete LOT-044 row-level provenance and missingness assessment, or acquire an authorized immutable official order/equipment snapshot.
- The position/ball-set analysis family is now predeclared in [POSITION_EQUIPMENT_ANALYSIS_PREREGISTRATION.md](POSITION_EQUIPMENT_ANALYSIS_PREREGISTRATION.md). It uses within-draw conditional permutations, preserves each selected set and ball-set label, and separates overall position tests from within-ball-set tests.
- No tests are run until the eligibility gate in that preregistration is satisfied.

## Phase F — exact unordered-subset distribution experiment

This is a separate, equipment-blind experiment over complete unordered subsets:
- Front support: all C(35,5) legal subsets; back support: all C(12,2) legal subsets.
- The current exponential-family candidate uses permutation-invariant subset-shape features: sum, odd-count, range, adjacent-pair count, and front-zone gap variance. It does not encode individual ball identities; it tests whether whole-subset structure adds value beyond the per-number baselines.
- Comparators are uniform and exact conditional-Poisson distributions calibrated to expanding-frequency and EWMA inclusion marginals.
- Rolling-origin protocol: 300 prior draws minimum, then all 2,649 eligible targets in the pinned 2,949-row snapshot; front/back exact subset negative log likelihood; no target or later draw enters its own fit.
- The six-comparison family is front/back × uniform/expanding/EWMA. Use paired non-circular moving-block bootstrap (block length 50, 1,000 replicates), a null-centered one-sided p-value, and Holm step-down over all six comparisons. Missing model coverage or invalid p-values fail closed.
- Solver: SciPy 1.15.3 L-BFGS-B with NumPy 2.2.6; no box bounds; lambda=1, maxiter 5,000, maxfun 500,000, maxcor 10, maxls 60, ftol 0, final gradient acceptance 1e-7. Runtime versions and options are bound into checkpoint and result receipts.
- This experiment remains equipment-blind. Its pinned snapshot is manifest-complete but not officially authenticated; a statistical pass is not production readiness and cannot open LOT-042.

## Phase E — prospective holdout

LOT-042 remains separate and unstarted. Its 500-consecutive-draw protocol must begin only after a committed freeze boundary and only for future eligible draws. Historical extension data, including draws 26084–26131, cannot be relabeled prospective.

## Decision rule

Uniform remains the reference model. No candidate is promoted on a nominal p-value, a selected era, Top-K hits alone, or a historical association. Any claimed edge must survive the predeclared proper-score comparison, uncertainty/multiplicity controls, data-quality gates, and ultimately independent prospective validation.

This project does not assume a recoverable random seed. No statistical pattern by itself establishes manipulation, a physical mechanism, or guaranteed prediction.
