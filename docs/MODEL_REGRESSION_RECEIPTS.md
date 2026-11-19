# LOT-073: Paired model regression receipts

src/lottery/evaluation.py builds deterministic, content-addressed evaluation receipts from chronological per-target scores. It compares a candidate against both the current champion and the legal uniform baseline, separately for front/back zones and Brier/log-loss.

## Input contract

A JSON input file contains score_rows in chronological order. Every target must contain exactly three model roles (candidate, champion, uniform), each with front and back, each with finite non-negative brier and log_loss values. Scores must use the same target denominator for all roles; the gate rejects missing models/metrics, duplicate target IDs, and insufficient coverage.

## Gate semantics

- Negative candidate-minus-reference deltas are improvements.
- Eligibility requires the upper endpoint of the paired moving-block 95% interval to be below zero for both metrics, both zones, and both references (champion and uniform).
- Otherwise the decision is rejected_or_inconclusive.
- Default minimum coverage is 200 targets; bootstrap uses 1,000 replicates, 50-target blocks, and a fixed seed.
- The receipt binds model IDs, dataset hash, code commit, protocol version, scope, target-window endpoints, target-ID digest, all comparisons, and its own SHA-256.
- Only rolling_origin and shadow scopes are accepted. Prospective holdout scope is rejected.

This is a conservative evidence gate, not a training loop. It does not fit or tune models, mutate a champion pointer, or enable serving. Even a passing result is only eligible_for_human_review; production_ready and automatic_promotion remain false. The caller must ensure the per-target score file was generated from a preregistered, leakage-safe evaluation and a verified dataset snapshot. A hash proves byte identity, not source authenticity.

## CLI

    python scripts/evaluation_receipt.py build scores.json --candidate-model-id candidate-v2 --champion-model-id champion-v1 --dataset-sha256 HASH --code-commit COMMIT --protocol-version frozen-v1 --output artifacts/evaluation-receipt.json
    python scripts/evaluation_receipt.py verify artifacts/evaluation-receipt.json

This first slice is not yet wired to automatic candidate fitting or lifecycle registry writes. Existing forecast/outcome ledgers record prospective marginal forecasts and outcomes, but do not yet provide a reviewed champion/candidate role mapping or full exact unordered-subset NLL. Integration remains blocked on the frozen LOT-055 evaluation contract and LOT-060 lifecycle implementation. LOT-042 remains untouched.


The gate enforces a hard floor of 200 chronological, strictly increasing five-digit draw IDs, at least 1,000 bootstrap replicates, and a block length of at least 50 and no more than half the minimum target count. Callers cannot lower these floors. The receipt records the complete evaluation configuration and a SHA-256 of the canonical per-target score rows, in addition to the target-ID digest.
