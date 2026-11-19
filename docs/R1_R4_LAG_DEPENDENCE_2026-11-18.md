# R1–R4 adjacent-draw dependence diagnostics

Date: 2026-11-18  
Tracking: [LOT-050](https://github.com/Be90nia/Lottery/issues/10)  
Implementation: [PR #11](https://github.com/Be90nia/Lottery/pull/11)  
CI: [run #44268128430](https://github.com/Be90nia/Lottery/actions/runs/44268128430)

## Dataset and reproducibility

- Dataset: `data/processed/draws-20261118.jsonl`
- Draws: 2,949 (07001–26131)
- SHA-256: `9f4cc51b76fd258dd056e0b86f675192d3d9a41c2901f771cab778c65ec2b6aa`
- Zones: front 5/35; back 2/12
- Lags: 1–4; lag 1 is the immediately preceding draw
- Null: uniform permutation of complete draw rows without replacement
- Moment-estimation permutations: 1,999, seed 20261118
- Independent test permutations: 1,999, seed 20261119
- P-value: `(exceedances + 1) / (permutations + 1)`

Each permutation preserves every complete draw's legal fixed-size front/back sets and all per-number inclusion totals, while breaking chronological order between draw rows. One independent permutation sample estimates means/standard deviations; a second independent sample estimates maximum-statistic tail probabilities. Monte Carlo standard errors and approximate 95% intervals are included for the omnibus p-values.

## Confirmatory results

The confirmatory family contains eight omnibus maximum-statistic tests (four lags × two zones). Each statistic is the maximum absolute standardized deviation across all ordered transitions (including the same-number diagonal) and aggregate set overlap. Holm correction is applied across all eight tests.

| Zone | Lag | Max statistic | Permutation p | MC SE | Holm-adjusted p |
|---|---:|---:|---:|---:|---:|
| Front | 1 | 3.204 | 0.8310 | 0.0084 | 1.000 |
| Front | 2 | 3.553 | 0.3880 | 0.0109 | 1.000 |
| Front | 3 | 3.509 | 0.4610 | 0.0111 | 1.000 |
| Front | 4 | 3.422 | 0.5475 | 0.0111 | 1.000 |
| Back | 1 | 2.384 | 0.9215 | 0.0060 | 1.000 |
| Back | 2 | 2.823 | 0.4945 | 0.0112 | 1.000 |
| Back | 3 | 2.721 | 0.5990 | 0.0110 | 1.000 |
| Back | 4 | 2.648 | 0.6920 | 0.0103 | 1.000 |

No zone/lag omnibus test is significant. The p-values are far from the 0.05 threshold even allowing for their Monte Carlo uncertainty. This does not prove that every possible form of temporal dependence is absent; it says that the predeclared R1–R4 transition family does not stand out against randomized orderings of the same draw rows.

## Aggregate recurrence and overlap

Counts sum shared numbers across the (n-r) chronological draw pairs at each lag. The independent fixed-size expectation is ((n-r)k^2/N). The permutation expectation additionally conditions on the observed collection of complete draw rows.

| Zone | Lag | Observed overlap | Permutation expected | Independent fixed-size expected | Descriptive two-sided p |
|---|---:|---:|---:|---:|---:|
| Front | 1 | 2,143 | 2,114.24 | 2,105.71 | 0.4980 |
| Front | 2 | 2,134 | 2,113.25 | 2,105.00 | 0.6060 |
| Front | 3 | 2,114 | 2,113.98 | 2,104.29 | 1.0000 |
| Front | 4 | 2,198 | 2,111.75 | 2,103.57 | 0.0295 |
| Back | 1 | 967 | 983.27 | 982.67 | 0.5380 |
| Back | 2 | 910 | 982.40 | 982.33 | 0.0080 |
| Back | 3 | 991 | 982.55 | 982.00 | 0.7755 |
| Back | 4 | 974 | 982.23 | 981.67 | 0.7745 |

The front lag-4 excess and back lag-2 deficit are unadjusted descriptive summaries only. Their aggregate overlap statistic is included in the eight-test omnibus maximum-statistic family; the corresponding Holm-adjusted omnibus p-values remain 1.000. Do not treat these two descriptive p-values as discoveries.

## Interpretation and decision

1. Do not add lag 1–4 recurrence or transition weights to V3 based on this diagnostic.
2. Keep uniform as the reference model.
3. Preserve the complete per-number and ordered-pair effect tables in the CI artifact; these are descriptive and carry no individual significance claims.
4. Phase C's four-lag rolling-origin challenger has also failed its predeclared proper-score promotion gate; see `docs/FOUR_LAG_MODEL_BACKTEST_2026-11-18.md`.
5. Do not infer manipulation, a recoverable seed, or a physical draw mechanism from these statistics.

The earlier circular-shift version of this diagnostic is superseded. Circular shifts tested whether a particular temporal offset was exceptional relative to other offsets, but did not adequately break the chronological ordering to serve as the primary no-temporal-dependence null. This row-permutation report is the confirmatory Phase B result.
