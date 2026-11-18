# Initial rolling-origin benchmark report

**Status:** reproducible exploratory benchmark; no predictive edge established.

## Provenance

- GitHub Actions run: [44216273468](https://github.com/Be90nia/Lottery/actions/runs/44216273468)
- Dataset: `data/candidates/legacy_draws.jsonl`
- Dataset SHA-256: `22cdd8aef049ee714020d3f5272b712cfef14da7fa7f276394ed8a1575901515`
- Records: 2,901, draw IDs 07001–26083
- Dates: 2007-05-30 through 2026-07-25
- Initial training window: 300 draws
- Evaluation targets: 2,601
- Expanding shrinkage: 100 pseudo-draws
- EWMA half-life: 100 draws

The source manifest labels this dataset `candidate_unverified`. It is a cleaned historical candidate, not a canonical dataset of immutable raw official responses. Results must not be generalized beyond this file.

## Marginal probability scores

Lower Brier and log loss are better.

| Model | Front Brier | Front log loss | Back Brier | Back log loss |
|---|---:|---:|---:|---:|
| Uniform | 0.122449 | 0.410116 | 0.138889 | 0.450561 |
| Expanding frequency | 0.122517 | 0.410388 | 0.139005 | 0.450977 |
| EWMA frequency | 0.122406 | 0.409976 | 0.139013 | 0.451004 |

The expanding model is worse than uniform in both zones. EWMA is marginally better in front but worse in back. These score differences are very small.

## Paired moving-block bootstrap

Each value is candidate minus uniform; negative favors the candidate. Intervals are exploratory 95% percentile intervals from 1,000 paired moving-block bootstrap replicates with 50-draw blocks and seed 20261118.

| Model | Zone | Metric | Mean delta | 95% interval |
|---|---|---|---:|---:|
| Expanding | Front | Brier | +0.0000678 | [-0.0001081, +0.0002297] |
| Expanding | Front | Log loss | +0.0002721 | [-0.0004407, +0.0009132] |
| Expanding | Back | Brier | +0.0001160 | [+0.0000256, +0.0002027] |
| Expanding | Back | Log loss | +0.0004160 | [+0.0001046, +0.0007200] |
| EWMA | Front | Brier | -0.0000425 | [-0.0001664, +0.0000788] |
| EWMA | Front | Log loss | -0.0001404 | [-0.0006310, +0.0003456] |
| EWMA | Back | Brier | +0.0001238 | [+0.0000097, +0.0002171] |
| EWMA | Back | Log loss | +0.0004428 | [+0.0000263, +0.0007783] |

Interpretation:

1. Both front-zone candidate intervals include zero. The slight EWMA front advantage is not distinguishable from noise under this exploratory interval.
2. Both models are worse than uniform in the back zone on both proper scores; the reported intervals are above zero.
3. Top-k overlap is descriptive and not a proper probabilistic score. Do not use it alone to claim forecasting advantage.
4. The moving-block intervals do not correct for model, feature, time-window, or hyperparameter selection. The evaluation history was used during exploratory model development and is not an untouched final holdout.
5. The candidate dataset's provenance and date coverage remain incomplete; no equipment-level causal conclusion is possible.

## Decision

Do **not** promote expanding frequency or EWMA to production prediction weights. Retain uniform as the benchmark. Continue data provenance reconciliation and preregistered period stability tests. Any later model selection must be evaluated on a newer untouched holdout.
