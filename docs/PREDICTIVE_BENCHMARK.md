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


## Uncertainty for paired model comparisons

The report additionally compares each frequency model with the uniform baseline
on the exact same target draws. For each target, it records the difference in
per-number Brier score and Bernoulli log loss (candidate minus uniform); a
negative value favors the candidate. A paired moving-block bootstrap with
1,000 replicates and 50-draw blocks produces exploratory 95% percentile
intervals. Blocks preserve some local temporal dependence better than an
i.i.d. bootstrap, but the intervals remain descriptive: they do not correct
for trying multiple models, feature families, cut points, or hyperparameters.
A candidate should not be considered predictive unless improvements are
material, stable across predeclared periods, and replicated on a later,
untouched holdout.

## Calendar-era score stability

The rolling-origin report now partitions evaluation targets into fixed descriptive
five-calendar-year bins (2007-2011, 2012-2016, 2017-2021, and 2022-2026).
Each target is still scored using only draws strictly earlier than that target;
training history is not reset at era boundaries. For every era with evaluation
targets, paired candidate-minus-uniform Brier and log-loss differences are
summarized with a 1,000-replicate moving-block bootstrap (maximum block length
50 draws).

These bins were introduced after inspection of earlier full-period results.
They are therefore exploratory, not preregistered confirmatory periods.
Per-era intervals are not multiplicity-adjusted and must not be used to select
a winning era or model. A genuinely confirmatory stability claim requires a
future protocol fixed before observing the corresponding evaluation outcomes
and replication on a later untouched holdout.
