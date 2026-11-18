# Calendar-era rolling-origin score stability

**Status:** exploratory diagnostic; no stable predictive advantage established.

## Provenance and protocol

- Workflow run: [44220221913](https://github.com/Be90nia/Lottery/actions/runs/44220221913)
- Dataset: `data/candidates/legacy_draws.jsonl`
- Dataset SHA-256: `22cdd8aef049ee714020d3f5272b712cfef14da7fa7f276394ed8a1575901515`
- Total evaluation targets: 2,601 (initial training history: 300 draws)
- Models: expanding historical frequency and EWMA, each compared with the legal uniform marginal-probability baseline.
- Per-era uncertainty: paired moving-block bootstrap, 1,000 replicates, maximum block length 50 draws, fixed seed 20261118.

The era bins are fixed five-calendar-year ranges: 2007–2011, 2012–2016, 2017–2021, and 2022–2026. The expanding training history is **not reset** at era boundaries. Every target is scored using only strictly earlier draws.

Important: these bins were introduced after earlier full-period results had been inspected. They are post-hoc descriptive partitions, not preregistered confirmatory periods. The intervals below are not adjusted for the multiple model × zone × era × metric comparisons. The dataset remains `candidate_unverified`; the final era ends at draw 26083 (2026-07-25), not the end of calendar 2026.

## Results

Each delta is candidate minus uniform; negative values favor the candidate. Brier and Log Loss are both proper scores, and lower is better.

| Era | Evaluation draws | Model | Zone | Δ Brier (95% CI) | Δ Log Loss (95% CI) |
|---|---:|---|---|---:|---:|
| 2007–2011 | 407 | Expanding | Front | -0.0005456 [-0.0009554, -0.0001618] | -0.0021143 [-0.0037479, -0.0006348] |
| 2007–2011 | 407 | Expanding | Back | +0.0002915 [-0.0001799, +0.0005897] | +0.0010610 [-0.0005642, +0.0020874] |
| 2007–2011 | 407 | EWMA | Front | -0.0005262 [-0.0009099, -0.0002124] | -0.0020343 [-0.0035513, -0.0007802] |
| 2007–2011 | 407 | EWMA | Back | +0.0002617 [-0.0001094, +0.0005080] | +0.0009529 [-0.0003756, +0.0018317] |
| 2012–2016 | 768 | Expanding | Front | -0.0000406 [-0.0004626, +0.0004283] | -0.0001500 [-0.0018146, +0.0016961] |
| 2012–2016 | 768 | Expanding | Back | +0.0001293 [-0.0000524, +0.0002648] | +0.0004633 [-0.0001620, +0.0009156] |
| 2012–2016 | 768 | EWMA | Front | -0.0001085 [-0.0003766, +0.0001712] | -0.0003909 [-0.0014633, +0.0007192] |
| 2012–2016 | 768 | EWMA | Back | +0.0001061 [-0.0000731, +0.0002545] | +0.0003782 [-0.0002641, +0.0009232] |
| 2017–2021 | 741 | Expanding | Front | +0.0003396 [+0.0001636, +0.0005297] | +0.0013206 [+0.0006117, +0.0021008] |
| 2017–2021 | 741 | Expanding | Back | +0.0000795 [-0.0000493, +0.0001867] | +0.0002726 [-0.0001841, +0.0006590] |
| 2017–2021 | 741 | EWMA | Front | +0.0001013 [+0.0000240, +0.0001946] | +0.0004119 [+0.0001069, +0.0007885] |
| 2017–2021 | 741 | EWMA | Back | +0.0000389 [-0.0002151, +0.0002492] | +0.0001337 [-0.0007842, +0.0008876] |
| 2022–2026* | 685 | Expanding | Front | +0.0002599 [+0.0001669, +0.0003428] | +0.0010290 [+0.0006529, +0.0013553] |
| 2022–2026* | 685 | Expanding | Back | +0.0000364 [-0.0000504, +0.0001385] | +0.0001350 [-0.0001798, +0.0005036] |
| 2022–2026* | 685 | EWMA | Front | +0.0001632 [+0.0000724, +0.0002460] | +0.0006681 [+0.0003095, +0.0009997] |
| 2022–2026* | 685 | EWMA | Back | +0.0001535 [-0.0000074, +0.0003041] | +0.0005467 [-0.0000263, +0.0011075] |

*2022–2026 evaluation coverage ends at draw 26083 on 2026-07-25.*

## Interpretation

1. **The apparent early front-zone improvement is not stable.** Both frequency estimators have negative front-zone score deltas in 2007–2011, but the advantage largely disappears in 2012–2016 and reverses in 2017–2021 and 2022–2026.
2. **Later front-zone periods are worse than uniform.** In both 2017–2021 and 2022–2026, both models have positive Brier and Log Loss deltas, with the displayed unadjusted intervals above zero.
3. **No convincing back-zone improvement appears.** Most back-zone point estimates are positive; several intervals cross zero. This is consistent with the full-period result that historical-frequency models do not beat uniform in the back zone.
4. The early-era result is a diagnostic lead only. It may reflect sampling variation, nonstationarity, data quality, or an unmodeled historical change. This analysis cannot distinguish those explanations and is not evidence of manipulation or a recoverable random seed.
5. Since the partitions were chosen after earlier inspection and no multiplicity correction is applied here, the interval signs must not be treated as confirmatory discoveries.

## Decision and next steps

- Do not promote expanding frequency or EWMA to production weights.
- Keep uniform as the reference model.
- Do not tune model parameters to the era with the most favorable result.
- Keep LOT-042 (untouched later holdout and preregistered selection protocol) open. Before any future model selection, freeze the feature family, parameter grid, target metrics, period boundaries, and multiplicity procedure; evaluate once on a later untouched period.
- Continue LOT-044 official raw-source and metadata provenance verification. The selected-number dataset used here is still a candidate, not canonical official raw data.

This task establishes that the existing frequency-model performance is period-dependent in this candidate dataset; it does not establish an exploitable or durable forecasting edge.
