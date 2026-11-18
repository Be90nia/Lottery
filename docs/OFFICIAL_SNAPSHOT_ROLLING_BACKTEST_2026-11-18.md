# Official selected-number snapshot: rolling-origin baseline

Run: [GitHub Actions #44262492821](https://github.com/Be90nia/Lottery/actions/runs/44262492821)  
Dataset: `data/processed/draws-20261118.jsonl`  
Dataset SHA-256: `9f4cc51b76fd258dd056e0b86f675192d3d9a41c2901f771cab778c65ec2b6aa`  
Rows: 2,949 (07001–26131), 2007-05-30 through 2026-11-16  
Evaluation: 2,649 targets, first 09054, last 26131  
Configuration unchanged: minimum training 300; expanding alpha 100; EWMA half-life 100.

## Result

Lower Brier and Bernoulli log loss are better. Deltas are candidate minus uniform; negative favors the candidate. Intervals are paired moving-block bootstrap 95% percentile intervals (1,000 replicates, block length 50, seed 20261118).

| Model | Zone | Mean Brier | Mean Log Loss | Δ Brier (95% CI) | Δ Log Loss (95% CI) |
|---|---|---:|---:|---:|---:|
| Uniform | Front | 0.122449 | 0.410116 | reference | reference |
| Expanding | Front | 0.122517 | 0.410389 | +0.000068 [-0.000093, +0.000227] | +0.000273 [-0.000373, +0.000900] |
| EWMA | Front | 0.122408 | 0.409980 | -0.000041 [-0.000164, +0.000071] | -0.000136 [-0.000625, +0.000307] |
| Uniform | Back | 0.138889 | 0.450561 | reference | reference |
| Expanding | Back | 0.139004 | 0.450972 | +0.000115 [+0.000022, +0.000200] | +0.000411 [+0.000085, +0.000712] |
| EWMA | Back | 0.139012 | 0.451000 | +0.000123 [+0.000009, +0.000208] | +0.000439 [+0.000029, +0.000746] |

## Interpretation

1. Expanding frequency is worse than uniform in both zones; the back-zone deterioration has an interval above zero.
2. EWMA has a very small front-zone point improvement, but both Brier and Log Loss intervals cross zero. This is not evidence of a stable front-zone edge.
3. Both frequency estimators are worse than uniform in the back zone; both paired intervals are above zero.
4. Top-K hit counts are descriptive only. They do not replace proper probabilistic scores and do not establish a forecasting advantage.
5. The result extends the prior 2,901-row legacy candidate analysis to the 2,949-row archived selected-number snapshot. It is still a historical exploratory backtest: all 2,949 outcomes are already known. In particular, the 48 draws 26084–26131 are not a prospective holdout.

## Calendar-era stability

Fixed five-calendar-year descriptive bins (post-hoc, not confirmatory):
- 2007–2011: 407 evaluation draws; both frequency models show a favorable front-zone delta.
- 2012–2016: 768 draws; front-zone deltas are close to zero and intervals cross zero.
- 2017–2021: 741 draws; both frequency models are worse than uniform in the front zone, with intervals above zero.
- 2022–2026: 733 draws through 26131; both frequency models are again worse than uniform in the front zone, with intervals above zero.

The early-era advantage does not persist. Era boundaries were not preregistered before earlier full-period inspection, and per-era intervals are not multiplicity-adjusted. Do not select an era or tune parameters from these results.

## Decision

No frequency model is promoted. Uniform remains the reference. Next model work should test predeclared R1–R4 adjacent-draw dependence and strictly causal lag features, using the same proper scores and rolling-origin design. Draw-order/equipment predictors remain gated on LOT-044 source-semantic and row-level provenance checks.

This analysis does not establish manipulation, a recoverable random seed, or predictable outcomes. It tests marginal number-inclusion probabilities, not a joint ticket-ranking system.
