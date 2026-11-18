# R1–R4 adjacent-draw dependence diagnostics

Date: 2026-11-18  
Tracking: [LOT-050](https://github.com/Be90nia/Lottery/issues/10)  
Implementation: [PR #11](https://github.com/Be90nia/Lottery/pull/11)  
CI: [run #44264899201](https://github.com/Be90nia/Lottery/actions/runs/44264899201)

## Dataset and reproducibility

- Dataset: `data/processed/draws-20261118.jsonl`
- Draws: 2,949 (07001–26131)
- SHA-256: `9f4cc51b76fd258dd056e0b86f675192d3d9a41c2901f771cab778c65ec2b6aa`
- Zones: front 5/35; back 2/12
- Lags: 1–4; lag 1 is the immediately preceding draw
- Null: exact enumeration of all 2,948 non-zero circular shifts of complete draw rows
- Monte Carlo: none; no random seed or Monte Carlo error interval

The null preserves each complete draw's fixed-size selected set and each number's total inclusion count. It conditions on observed marginal frequencies and tests whether a particular circular time offset is unusually aligned. It assumes no privileged cyclic origin and includes wraparound at the series boundary. This is a conditional phase-randomization diagnostic, not a direct test of every possible form of temporal dependence.

## Confirmatory results

The confirmatory family contains eight omnibus maximum-statistic tests (four lags × two zones). Each statistic is the maximum absolute standardized deviation across all ordered transitions, including same-number recurrence and aggregate set overlap. Holm correction is applied across all eight tests.

| Zone | Lag | Max statistic | Exact circular-shift p | Holm-adjusted p |
|---|---:|---:|---:|---:|
| Front | 1 | 3.112 | 0.8955 | 1.000 |
| Front | 2 | 3.491 | 0.4600 | 1.000 |
| Front | 3 | 3.397 | 0.5889 | 1.000 |
| Front | 4 | 3.417 | 0.5522 | 1.000 |
| Back | 1 | 2.402 | 0.9071 | 1.000 |
| Back | 2 | 2.852 | 0.4518 | 1.000 |
| Back | 3 | 2.693 | 0.6323 | 1.000 |
| Back | 4 | 2.583 | 0.7347 | 1.000 |

No zone/lag omnibus test is significant. This does not establish that every possible form of temporal dependence is absent; it says that these predeclared lag offsets are not unusually extreme under this conditional circular-shift null.

## Aggregate recurrence and overlap

Counts below sum shared numbers across the 2,949 cyclic draw-pairs at each lag. The independent fixed-size expectation is (n k^2/N); the conditional circular-shift expectation additionally preserves observed per-number frequencies.

| Zone | Lag | Observed overlap | Circular-shift expected | Independent fixed-size expected | Descriptive two-sided shift p |
|---|---:|---:|---:|---:|---:|
| Front | 1 | 2,144 | 2,114.96 | 2,106.43 | 0.4783 |
| Front | 2 | 2,135 | 2,114.96 | 2,106.43 | 0.6187 |
| Front | 3 | 2,115 | 2,114.96 | 2,106.43 | 1.0000 |
| Front | 4 | 2,198 | 2,114.96 | 2,106.43 | 0.0448 |
| Back | 1 | 968 | 983.07 | 983.00 | 0.5984 |
| Back | 2 | 910 | 983.07 | 983.00 | 0.0095 |
| Back | 3 | 991 | 983.07 | 983.00 | 0.7904 |
| Back | 4 | 976 | 983.07 | 983.00 | 0.8100 |

The front lag-4 excess and back lag-2 deficit are descriptive only. They are not independent confirmatory findings; the aggregate overlap feature is included in the omnibus maximum-statistic family, whose corresponding adjusted p-values remain 1.000.

## Interpretation and decision

1. Do not add lag 1–4 recurrence or transition weights to V3 based on this diagnostic.
2. Keep uniform as the reference model.
3. Preserve the complete per-number and ordered-pair effect tables in the CI artifact for reproducibility; these are descriptive and carry no individual significance claims.
4. Proceed to Phase C only as a separately predeclared rolling-origin forecast experiment. Features must use prior draws only and must beat uniform/expanding/EWMA on proper scores with paired uncertainty controls.
5. Do not infer manipulation, a recoverable seed, or a physical draw mechanism from these statistics.

Artifact: `official-snapshot-r1-r4-lag-dependence.json` in the CI run above.
