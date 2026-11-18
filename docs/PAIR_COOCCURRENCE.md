# Pair co-occurrence diagnostics

**Status:** implemented exploratory diagnostic. The repository candidate dataset is
still marked `candidate_unverified`; this report must not be interpreted as a
claim about verified official draws.

## Null model

For a zone with a pool of (N) numbers and (k) selected numbers per draw, a
fixed pair is included with probability

[
p_{pair}=\frac{k(k-1)}{N(N-1)}.
]

Across (T) independent draws, the pair count has a
(operatorname{Binomial}(T,p_{pair})) distribution under the uniform legal
draw null. Each pair receives a conservative equal-tailed exact two-sided
binomial p-value. The front and back pair hypotheses are combined into one
family of 595 + 66 = 661 tests, and Holm's step-down procedure controls the
family-wise error rate at 0.05 under arbitrary dependence among the tests.

This is not a test of whether a pair is more likely on the next draw. The null
requires independence across draws. Holm correction does not repair temporal
dependence or a misspecified data-generating process.

## Reproduction

```bash
python scripts/analyze_pairs.py data/candidates/legacy_draws.jsonl \
  --output pair-cooccurrence.json
```

The output includes every front/back pair, observed and expected counts, raw
and Holm-adjusted p-values, and the 20 smallest adjusted p-values. The CLI
records the dataset SHA-256 and the dataset validator result.

## Interpretation safeguards

- Do not interpret a small adjusted p-value as evidence of manipulation,
  physical equipment effects, or a causal mechanism.
- Do not use pair statistics as forecast features or as a reason to change
  the fixed prospective-holdout models.
- The candidate file's historical source/provenance limitations apply to all
  results; a hash proves byte identity, not official origin.
- Because the null assumes independent draws over time, a separate
  time-dependence audit would be needed before treating the nominal p-values
  as confirmatory.
- The output is exploratory and should be reported in full, not selectively
  filtered to a preferred pair.
