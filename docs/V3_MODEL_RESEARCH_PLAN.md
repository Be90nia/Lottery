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
3. **Set overlap:** shared values between the two fixed-size draw sets. Report both the conditional circular-shift expectation and the independent legal-draw expectation n·k²/N.
4. **Temporal stability:** calendar-block summaries are descriptive only and cannot be used to select a favorable era.

### Randomization and multiplicity

The implemented null is exact enumeration of all non-zero circular shifts of the complete draw-row sequence. This preserves each draw's legal fixed-size set, the per-number inclusion totals, and front/back separation. It conditions on observed marginal frequencies and asks whether any particular temporal phase is unusually aligned.

The circular-shift null assumes that, under no temporal dependence, no cyclic time origin is privileged. It includes wraparound at the series boundary; this assumption and limitation are recorded in the output. It is a conditional phase-randomization diagnostic, not a physical model of the draw mechanism.

To avoid impossible p-value resolution from applying thousands of individual tests to only 2,948 available shifts, the confirmatory family is **eight omnibus tests**: four lags × two zones. Each omnibus statistic is the maximum absolute standardized deviation across all ordered number transitions (including the same-number diagonal) for that zone and lag. Its exact randomization p-value is computed against the maximum-statistic distribution over all non-zero shifts. Holm correction is then applied across all eight omnibus tests. Per-number and per-pair results are effect-size diagnostics only; they do not carry individual significance claims.

The report includes raw transition counts, conditional expected counts, effect sizes, recurrence totals, set overlaps, exact shift counts, omnibus statistics, raw p-values, and Holm-adjusted p-values. There is no Monte Carlo sampling and therefore no simulation seed or Monte Carlo error interval.

A statistically unusual transition is a diagnostic, not evidence of manipulation and not automatically a useful forecast feature. Because the circular boundary assumption is imperfect for a finite chronological series, any apparent signal must be independently checked before Phase C.

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

The legacy candidate contains 2,341 structurally valid order rows and 2,336 nonzero equipment codes, but the field semantics and row-level provenance remain unverified. The 2026 official snapshot parser retains source fields, yet the current archived rows show blank order strings and zero equipment metadata. Therefore:
- Do not call the legacy values verified physical extraction order, machine ID, or ball-set ID.
- Complete LOT-044: authorized raw-row reconciliation, official field semantics, equipment-code mapping, and missingness assessment.
- Only then predeclare position-by-number and equipment-stratified tests, with correction and a later untouched confirmation period.

## Phase E — prospective holdout

LOT-042 remains separate and unstarted. Its 500-consecutive-draw protocol must begin only after a committed freeze boundary and only for future eligible draws. Historical extension data, including draws 26084–26131, cannot be relabeled prospective.

## Decision rule

Uniform remains the reference model. No candidate is promoted on a nominal p-value, a selected era, Top-K hits alone, or a historical association. Any claimed edge must survive the predeclared proper-score comparison, uncertainty/multiplicity controls, data-quality gates, and ultimately independent prospective validation.

This project does not assume a recoverable random seed. No statistical pattern by itself establishes manipulation, a physical mechanism, or guaranteed prediction.
