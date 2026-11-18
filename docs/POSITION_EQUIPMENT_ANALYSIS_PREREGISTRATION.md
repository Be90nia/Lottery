# LOT-044: Position and ball-set analysis preregistration

Status: **design only; blocked pending source-provenance gate**  
Date: 2026-11-18  
Tracking: [LOT-050](https://github.com/Be90nia/Lottery/issues/10)

## Purpose

Test whether the official published draw-order sequence is consistent with random assignment of the selected numbers to positions, and whether any departure is concentrated within a numbered draw-ball set.

This is a test of the published order metadata. It is not a test for a recoverable RNG seed, does not establish manipulation, and does not by itself establish predictive value.

## Eligibility gate

Do not run confirmatory analysis until the analysis dataset is frozen and every included row has:

1. A unique draw ID and date.
2. Five distinct front numbers in 1..35 and two distinct back numbers in 1..12.
3. Five front and two back values in the official published draw order, each exactly a permutation of that draw's selected numbers.
4. A ball-set code in {1,2,3} corroborated by an official source for that row.
5. Direct source provenance: official announcement URL plus archived raw page/response bytes and SHA-256, or an immutable official API response snapshot with a row-level pointer.
6. A versioned parser and reproducible crosswalk result.

Rows with missing order or unknown ball-set code are excluded, never imputed. Rows validated only by structural permutation checks or by the convenience crosswalk sample are not automatically eligible for the confirmatory dataset.

The current 21 crosswalks are useful source evidence but are not a representative or sufficiently large analysis dataset. The 16-row random audit sample had five official pages located and matched, while eleven did not have a source URL located in the current search pass. No positional or equipment inference is authorized from this sample.

## Primary hypotheses

Analyze front and back zones separately.

- **H-F:** Conditional on the five selected front numbers in a draw, their assignment to positions 1–5 is uniform over all 5! permutations.
- **H-B:** Conditional on the two selected back numbers in a draw, their assignment to positions 1–2 is uniform over both 2! permutations.

The null is conditional on each draw's unordered selected set. This preserves the actual selected numbers and all per-number frequencies while testing only whether the published order assigns those numbers to positions uniformly.

## Primary randomization test

For each eligible draw independently:

1. Keep its selected front set fixed and uniformly permute its five values across positions.
2. Keep its selected back set fixed and uniformly permute its two values across positions.
3. Keep draw date and ball-set label fixed.

For each zone, compute a predeclared omnibus statistic: the maximum absolute standardized deviation across all number-by-position cells. Standardization parameters are estimated from an independent permutation sample, then the test statistic is evaluated on a second independent sample.

- Default: 9,999 moment permutations and 9,999 independent test permutations.
- Seeds: 20261118 and 20261119.
- P-value: plus-one Monte Carlo correction.
- Report Monte Carlo standard error and interval.
- Holm correction across the two primary zone-level omnibus tests.
- Cell-level counts and effects are descriptive; no individual number-position discovery claims.

This conditional permutation null preserves every draw's selected set and all chronological/ball-set labels. It tests position assignment, not whether the unordered selected sets themselves are uniform.

## Ball-set analyses

Ball-set codes are treated as numbered draw-ball sets, not machine IDs.

Secondary analyses are predeclared as three within-set tests per zone (six total): test the same conditional position-uniformity hypothesis within each ball set, using the same statistic and randomization method. Apply Holm correction across all six secondary tests.

These tests ask whether a position departure exists within a given set. They do not establish that changing the set causes a difference. Report draw counts, dates, and equipment-set usage periods for each group. If a set is concentrated in a particular calendar era, explicitly flag the time confounding; do not interpret the set comparison causally.

No additional subdivision by year, month, promotion, prize, sales, or post-hoc detected change points is allowed in the confirmatory family. Such analyses may be labelled exploratory and must not determine feature selection.

## Robustness and data-quality checks

Before looking at test results:

- Verify every included order array is a permutation of the corresponding selected-number set.
- Verify no duplicate draw IDs and no duplicate rows.
- Report missingness by year and ball-set code; do not assume missingness is random.
- Report the number of eligible draws per set and per calendar year.
- Re-run the analysis after excluding each year in turn as a stability diagnostic; these are sensitivity analyses, not extra hypothesis tests.
- Preserve the exact dataset hash, crosswalk-registry hash, code commit, configuration, seeds, and full output artifact.

## Prediction gate

A significant positional association is not automatically a forecast edge. Any candidate model must be predeclared, strictly causal, and evaluated on rolling-origin targets that were not used to choose the position feature. Compare proper marginal scores against the uniform baseline and the fixed expanding/EWMA references. A position feature is not promoted unless it improves the predeclared proper-score family with uncertainty intervals excluding zero and later passes the separate 500-draw prospective protocol.

Do not fit a predictive model on the full history and then report its in-sample fit as evidence of forecasting skill.

## Current decision

**Blocked.** Do not run position or ball-set hypothesis tests yet. First finish the row-level source audit or acquire an authorized immutable official snapshot with order and ball-set fields. The current evidence validates the published field meaning for a small set of rows only.
