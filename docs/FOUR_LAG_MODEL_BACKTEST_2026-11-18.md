# Four-lag logistic model: rolling-origin backtest

Date: 2026-11-18  
Tracking: [LOT-050](https://github.com/Be90nia/Lottery/issues/10)  
Implementation: [PR #12](https://github.com/Be90nia/Lottery/pull/12)  
CI: [run #44266482277](https://github.com/Be90nia/Lottery/actions/runs/44266482277)

## Dataset and protocol

- Dataset: `data/processed/draws-20261118.jsonl`
- Draws: 2,949 (07001–26131)
- SHA-256: `9f4cc51b76fd258dd056e0b86f675192d3d9a41c2901f771cab778c65ec2b6aa`
- Evaluation targets: 2,649, from 09054 through 26131
- Minimum training history: 300 draws
- Candidate: four shared lag coefficients per zone; ridge logistic marginal inclusion model over the 16 four-bit lag patterns
- Ridge penalty: λ=10.0, fixed before evaluation
- Baselines: uniform; expanding frequency α=100; EWMA half-life=100
- Metrics: per-number Brier (primary), Bernoulli log loss (secondary); Top-K hits descriptive only
- Uncertainty: paired moving-block bootstrap, 1,000 replicates, block length 50, seed base 20261119

Each training example for historical target j uses only draws j−1 through j−4. For forecast target t, model fitting uses only labelled targets j<t, and the target feature uses only t−1 through t−4. Prefix sufficient statistics are used to make each expanding-origin refit efficient without changing the training window.

The model estimates marginal inclusion probabilities, then solves a per-target intercept offset so probabilities sum to 5 (front) or 2 (back). It does not claim a joint distribution over tickets.

## Candidate scores

| Zone | Mean Brier | Mean log loss | Mean Top-K hits | Uniform expected Top-K |
|---|---:|---:|---:|---:|
| Front | 0.12245427 | 0.41013696 | 0.73575 | 0.71429 |
| Back | 0.13890879 | 0.45063237 | 0.33786 | 0.33333 |

Top-K hit rates are descriptive and cannot override proper-score results.

## Paired score differences

All deltas are candidate minus baseline; negative is better. Parentheses show the paired 95% moving-block bootstrap interval.

| Baseline | Zone | Δ Brier | Δ log loss |
|---|---|---:|---:|
| Uniform | Front | +0.0000053 (−0.0000170, +0.0000230) | +0.0000206 (−0.0000649, +0.0000933) |
| Uniform | Back | +0.0000199 (−0.0000424, +0.0000892) | +0.0000712 (−0.0001766, +0.0003421) |
| Expanding | Front | −0.0000627 (−0.0002369, +0.0000887) | −0.0002520 (−0.0009385, +0.0003035) |
| Expanding | Back | −0.0000948 (−0.0001999, +0.0000168) | −0.0003401 (−0.0006942, +0.0000770) |
| EWMA | Front | +0.0000465 (−0.0000664, +0.0001694) | +0.0001567 (−0.0002830, +0.0005951) |
| EWMA | Back | −0.0001031 (−0.0002142, +0.0000458) | −0.0003678 (−0.0007781, +0.0001426) |

Every paired interval crosses zero. Against uniform, the lag model is slightly worse by point estimate in both zones. It is slightly better than expanding by point estimate in both zones, and mixed against EWMA, but none of those differences is resolved by the paired intervals.

## Promotion decision

**Not eligible for promotion.** The predeclared gate requires the upper endpoint of the paired 95% interval to be below zero for both proper scores, in both zones, against all three reference models. None of the 12 comparisons meets that requirement.

No lag weights are added to V3. Uniform remains the reference model. The result does not justify tuning ridge strength, selecting individual lags, or retaining the candidate based on Top-K hits.

## Limitations and next step

This is a historical rolling-origin extension, not untouched prospective validation. It does not prove that all temporal dependencies are absent, nor that a seed or physical mechanism exists. LOT-042's 500-draw prospective protocol remains separate and must begin only after a committed freeze boundary.

The next useful step is not to tune this model against the same 2,949 draws. Preserve the result, keep the candidate unpromoted, and move to independently predeclared feature families only when there is a defensible reason and a clean prospective evaluation boundary.
