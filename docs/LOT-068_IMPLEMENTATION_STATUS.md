# LOT-068 exact-subset engine implementation status

## Implemented in this slice

- Isolated `lottery.subset_probability` module; legacy `backtest.py`, `forecast.py`, and LOT-042 ledger remain untouched.
- Canonical fixed-size support enumeration and strict ascending-subset validation.
- Symmetric feature extraction (sum, odd count, range, adjacent pairs, front gap variance); zero-variance feature omission.
- Exhaustive uniform-support moments and exact integer feature-cell multiplicities.
- Full-support exponential-family log partition and exact-set log probability using grouped cells and stable log-sum-exp.
- Exact log-space elementary-symmetric-polynomial DP, inclusion marginals, conditional-Poisson log probability, and backward sampling with injected deterministic RNG.
- Small-support brute-force checks, front/back support counts, theta=0 uniform recovery, invalid-input rejection, extreme finite log-weight checks, and deterministic sampler replay.

## Explicitly not yet complete

- Exponential-family fitting is not enabled yet. The preregistered contract requires SciPy L-BFGS-B with fixed solver settings, but the repository currently has no dependency lock or hash-checked wheel/source lock. Adding an unpinned numerical dependency would violate the supply-chain contract. This must be resolved with LOT-066 dependency locking before enabling the optimizer.
- Weighted-subset marginal calibration is not yet enabled. DP normalizers and marginals are exact, but the constrained convex-dual solver and its fail-closed terminal receipt remain required.
- RFC 8785 JCS artifact serialization and cross-language golden vectors remain required before artifacts can be treated as content-addressed model artifacts.
- Exact-set rolling-origin evaluation, bootstrap and Holm family correction are downstream LOT-055 work and are not implemented by this module.
- No model is forecast-ready, promoted, or user-facing. This module does not use equipment/ball-set labels or LOT-042 holdout data.

## Commands

`python -m unittest discover -s tests -p "test_subset_probability.py" -v`

The full front-support enumeration is deterministic and exhaustive. CI timing and memory measurements must be collected from the repository's own runner; no machine-specific performance claim is made here.
