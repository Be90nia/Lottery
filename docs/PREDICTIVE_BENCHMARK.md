# Predictive model benchmark

## Purpose and limits

This benchmark tests whether simple historical-frequency estimators improve
probabilistic forecasts over the legal uniform baseline. It does not assume
that lottery draws are predictable, and it does not attempt to recover a
physical random-number-generator seed.

## Models

- **Uniform:** front inclusion probability 5/35; back inclusion probability 2/12.
- **Expanding frequency:** empirical inclusion rate shrunk toward the uniform
  prior with 100 pseudo-draws:
  `p_i = (c_i + alpha * p0) / (n + alpha)`.
- **EWMA frequency:** the same shrinkage, but historical inclusion indicators
  receive exponentially decaying weights with a fixed 100-draw half-life.

All settings are fixed before the evaluation run. No hyperparameter search is
performed on the evaluation period in this initial benchmark.

## Evaluation protocol

1. Sort records by official draw date and draw identifier.
2. Use the first 300 draws as the initial training history.
3. For each subsequent draw, estimate probabilities using only preceding draws.
4. Score the target draw, then advance the origin by one draw.
5. Report mean per-number Brier score and Bernoulli log loss for each zone.
   Lower is better. Also report mean overlap between the predicted top-k
   numbers and the actual k selected numbers.
6. Compare all models on exactly the same target draws.

The top-k metric is descriptive and has a uniform expected overlap of k²/N.
The Brier and log-loss metrics score marginal inclusion probabilities; they do
not model dependence among numbers or provide the probability of a complete
ticket. The test sequence is chronological but not an untouched final holdout
if model design is changed after inspecting these results. Any subsequent
model selection requires a new later holdout.

## Reproduction

```bash
python scripts/backtest_models.py data/candidates/legacy_draws.jsonl
```

Optional parameters: `--min-train`, `--alpha`, `--half-life`, and
`--output`. Every report records the exact input file SHA-256 and effective
date range. Preserve the report even when all candidate models lose to uniform.
