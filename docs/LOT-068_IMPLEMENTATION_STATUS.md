# LOT-068 / LOT-054 / LOT-055 first-batch implementation status

## Implemented in the isolated research branch

- Exact fixed-size support enumeration and strict canonical subset validation.
- Symmetric feature extraction (sum, odd count, range, adjacent pairs, front gap variance), exhaustive legal-support moments, zero-variance omission, and exact integer feature-cell multiplicities.
- Complete-support exponential-family log partition, exact-set log probability, mean-NLL objective, analytic gradient, and replication-invariance checks.
- Exact log-space elementary-symmetric-polynomial DP, inclusion marginals, conditional-Poisson log probability, constrained weighted-marginal calibration with a zero-sum gauge, and exact backward sampling with injected RNG.
- Expanding-frequency and EWMA marginal target formulas with fixed alpha=100 and half-life=100, calibrated into fixed-size subset distributions.
- Restricted JCS canonicalization, SHA-256 content IDs, tamper checks, an RFC-style number-formatting golden vector, and a canonical byte hash fixture.
- Separate exact-set rolling-origin primitives: frozen snapshot/target-manifest preflight, uniform exact-set NLL, complete terminal-row accounting, non-circular block bootstrap, and Holm step-down adjustment.
- Explicit exact-backtest CLI requiring snapshot, target manifest, dependency-lock bytes/hash, experiment ID, code revision, bootstrap seed, and output directory.
- Frozen LOT-055 target manifest generated from the pinned archive snapshot: 2,949 rows; 2,649 targets; first target 09054; last target 26131; 300 prior rows at the first target.

## Validation evidence

GitHub Actions run 44511945472 completed successfully:
- Ubuntu unit-tests: 138 tests passed, including full front/back support counts and grouped feature-cell coverage.
- Windows ledger-lock tests: passed.
- Existing legacy dataset validation, prize audit, source reconciliation, and diagnostic smoke steps: passed.

These checks validate the new deterministic primitives and preserve the legacy test suite. They are not a full 2,649-target model fit or a claim of predictive advantage.

## Remaining blockers before the first batch can be called complete

1. **Optimizer runtime lock:** the L-BFGS-B adapter is implemented against SciPy, but the repository currently has no pinned/hash-checked dependency lock. The fitter and CLI deliberately fail closed until LOT-066 supplies the reviewed lock. No optimizer convergence claim has been made.
2. **JCS conformance breadth:** the serializer has an RFC-style number vector and a byte/hash fixture, but still needs the complete applicable RFC 8785 vectors and independent cross-language golden verification before production artifact use.
3. **Confirmatory multiplicity policy:** Holm adjustment is implemented, but Issue #35 does not yet fully pin the p-value construction and exact hypothesis-family membership. The CLI therefore marks confirmatory status BLOCKED and does not promote or claim a confirmatory result.
4. **Frozen run inputs:** the target manifest is checked in; the 1 MB data snapshot remains on the separate archive branch at its pinned commit and must be supplied explicitly to the runner. The target-manifest SHA-256 is `2afa95db29eba3f13ce93ddc8e4930714cdb060c3b05cea12d843f98b74b46f5`.
5. **Full evaluation:** the 2,649-target run has not been started. It is intentionally not triggered in Actions because it is compute-intensive and the Actions budget has been constrained.

## Safety and isolation

- No edits to legacy marginal `backtest.py`, prospective `forecast.py`, or LOT-042 holdout files.
- No equipment/ball-set fields enter this pooled model engine.
- No user-facing predictor, three-slot API, Champion promotion, or forecast-ready artifact is enabled.
- Historical exact-set scores, when eventually produced, remain historical research only; prospective validation is still required.
