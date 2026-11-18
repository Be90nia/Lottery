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
1. **Same-number recurrence:** per-number joint inclusion and zone-level repeat counts.
2. **Lagged cross-number transition:** every ordered pair (a,b), preserving direction; (a→b) and (b→a) are distinct.
3. **Set overlap:** shared values between the two fixed-size draw sets at lag r. Report the complete-row permutation expectation and the independent legal-draw expectation (n−r)·k²/N.
4. **Ordered transitions:** report every ordered pair (a,b) as a descriptive effect-size table; individual pair rows do not receive confirmatory p-values. Calendar-era summaries remain separate exploratory analyses and cannot be used to select a favorable lag or era.

### Randomization and multiplicity

The null is a Monte Carlo uniform permutation of complete draw rows without replacement. Each permutation preserves every draw's legal fixed-size front/back sets and all per-number inclusion totals, while breaking chronological order between draws. This directly tests temporal dependence conditional on the observed draw rows; it does not model or imply a physical draw mechanism.

Two independent, seeded permutation samples are used: one estimates the null mean/standard deviation for every ordered transition and aggregate set-overlap statistic; the second estimates the maximum-statistic tail probability. The default is 1,999 permutations for each sample, with the seed and Monte Carlo uncertainty recorded in the output. The p-value uses the plus-one correction.

To control multiplicity without treating thousands of pair-level p-values as separately confirmatory, the family is **eight omnibus tests**: four lags × two zones. Each omnibus statistic is the maximum absolute standardized deviation across all ordered number transitions (including the same-number diagonal) and aggregate set overlap for that zone and lag. The maximum is evaluated against the independently generated row-permutation null. Holm correction is applied across all eight omnibus tests. Per-number and per-pair results are effect-size diagnostics only; they do not carry individual significance claims.

The report includes raw transition counts, permutation expectations and standard deviations, effect sizes, recurrence totals, set overlaps, permutation counts/seeds, Monte Carlo uncertainty, omnibus statistics, raw p-values, and Holm-adjusted p-values.

A statistically unusual transition is a diagnostic, not evidence of manipulation and not automatically a useful forecast feature. Any apparent signal must be independently checked before Phase C.

## Phase C — lag-feature predictive experiment

Only after Phase B's test family and implementation are frozen, evaluate one fixed lag-feature candidate:
- Model: four-lag shared-coefficient ridge logistic marginal inclusion model, fitted separately for front and back zones.
- Features: same-number inclusion indicators at lags 1–4 only. No ordered cross-number coefficient matrix and no post-hoc lag selection.
- Estimation: composite Bernoulli logistic likelihood aggregated over the 16 possible four-bit lag patterns; fixed L2 penalty λ=10.0, with no hyperparameter search.
- Causality: for target draw t, fit only on labelled historical targets j<t; each training target j uses features from j-1 through j-4. The prediction uses only t-1 through t-4.
- Calibration: solve a per-target intercept offset by bisection so the marginal inclusion probabilities sum exactly to 5 (front) or 2 (back). This is a calibrated marginal-probability vector, not a claimed joint ticket distribution.
- Compare against uniform, expanding-frequency (α=100), and EWMA (half-life=100) on identical rolling-origin targets, with minimum training history 300.
- Primary metric: per-number Brier; secondary: Bernoulli log loss. Use paired moving-block bootstrap (1,000 replicates, 50-draw blocks, fixed seed base 20261119).
- Promotion gate: the lag model must have the upper endpoint of the paired 95% interval below zero for both Brier and log loss, in both zones, against all three reference models. This is deliberately conservative; Top-K hits are descriptive only.
- Do not include draw-order, equipment, prize, sales, or promotion fields. A failure to beat the references leaves uniform as the reference; no parameter tuning is permitted on this historical extension.

## Phase D — order/equipment research gate

The legacy candidate contains 2,341 structurally valid order rows and 2,336 nonzero equipment codes, but the field semantics and row-level provenance remain unverified. The 2026 official snapshot parser retains source fields, yet the current archived rows show blank order strings and zero equipment metadata. Therefore:
- Do not call the legacy values verified physical extraction order, machine ID, or ball-set ID.
- Complete LOT-044: authorized raw-row reconciliation, official field semantics, equipment-code mapping, and missingness assessment.
- Only then predeclare position-by-number and equipment-stratified tests, with correction and a later untouched confirmation period.

## Phase E — prospective holdout

LOT-042 remains separate and unstarted. Its 500-consecutive-draw protocol must begin only after a committed freeze boundary and only for future eligible draws. Historical extension data, including draws 26084–26131, cannot be relabeled prospective.

## Decision rule

Uniform remains the reference model. No candidate is promoted on a nominal p-value, a selected era, Top-K hits alone, or a historical association. Any claimed edge must survive the predeclared proper-score comparison, uncertainty/multiplicity controls, data-quality gates, and ultimately independent prospective validation.

This project does not assume a recoverable random seed. No statistical pattern by itself establishes manipulation, a physical mechanism, or guaranteed prediction.
