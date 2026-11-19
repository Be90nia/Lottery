# Reported Set-Index Conditional Model Pilot — Preregistration

**Status:** preregistered research-only pilot; not a physical ball-set model and not a promotion authorization.

## 1. Scope and naming

This pilot conditions on the source-reported per-draw category `reported_set_index ∈ {1,2,3}`. It does **not** assert that an index identifies the same physical ball equipment across time.

Keep these fields separate:

- `reported_set_index`: the explicit label parsed from a per-draw Jiangsu provincial lottery announcement.
- `equipment_regime_id`: formal operating regime; unresolved.
- `physical_ball_set_id`: stable physical equipment identity; unresolved.

The existing LOT-058 physical-regime gate remains blocked. This pilot does not modify `training_eligibility=blocked_regime_unresolved`, assign regime IDs, or activate physical 3N slots. Its output must be called a **reported-index-conditioned candidate**, never a physical-set prediction.

## 2. Frozen development inputs

- Draw inventory: `data/ball_set/draw-inventory-20261118.jsonl`.
- Inventory SHA-256: `9f4cc51b76fd258dd056e0b86f675192d3d9a41c2901f771cab778c65ec2b6aa`.
- Inventory size: 2,949 draws, 07001–26131, 2007-05-30 through 2026-11-16.
- Label evidence: coverage report schema `lottery.ball-set-coverage/v1`, with every admitted label re-parsed from archived raw announcement bytes and tied to the hash-chained observation ledger.
- Current verified label window: 1,067 primary-verified labels, 2019-08-31 through 2026-11-16; 100% coverage within that observed window.
- Reported-index counts: index 1 = 360, index 2 = 347, index 3 = 360.
- Exclude all unobserved inventory rows, non-primary observations, conflicting/revised labels, and out-of-inventory draw 26132.
- The inventory trust status remains `candidate_unverified` / `manifest_complete_not_officially_authenticated`. The per-draw set labels are source-evidence verified, but the underlying draw-number inventory is not thereby officially authenticated. This pilot uses the pinned inventory's numbers and the separate evidence view's labels.

The derived view must bind the inventory SHA, coverage report SHA, and observation-ledger SHA. It must replay the raw evidence and fail closed on any mismatch.

## 3. Causal split and target eligibility

For each reported index (s \in \{1,2,3\}):

1. Sort only primary-verified rows for (s) by `(draw_date, draw_id)`.
2. The first 200 rows are the fixed warm-up history.
3. Evaluate every subsequent row as a rolling-origin target; at each target, train only on earlier rows with the same reported index.
4. Do not pool rows across indices, use future rows, or infer an index for unobserved draws.

Expected pilot target counts on the frozen evidence view are 160, 147, and 160 respectively (467 total). Any change in these counts requires a new preregistration version before evaluation.

## 4. Fixed model family

Evaluate the same three estimators independently within each reported index:

- Uniform inclusion baseline.
- Expanding-frequency marginal weights with fixed Dirichlet/uniform shrinkage `alpha=100`.
- EWMA marginal weights with fixed `half_life=100` draws.

Use the existing conditional-Poisson/rejective sampler to convert each estimator's front/back inclusion marginals into legal 5-of-35 and 2-of-12 unordered combinations. The sampler is a probability-distribution construction, not evidence of a physical draw mechanism.

No hyperparameter search, feature search, or strategy selection is permitted on these pilot targets.

## 5. Scoring and inference

- Primary score: exact unordered-subset negative log likelihood, front and back zones reported separately.
- Secondary score: marginal inclusion Brier score and calibration residual.
- Compare each non-uniform estimator with the uniform baseline on the same chronological targets within each index.
- The planned family is 3 indices × 2 challengers × 2 zones = 12 comparisons; apply Holm correction across all 12.
- Use paired moving-block bootstrap with block length 10, 10,000 replicates, seed `20261119`, for uncertainty intervals. Report target counts and the number of complete blocks; do not overstate precision when the number of blocks is small.
- Report per-index results and pooled descriptive results separately. No pooled result may conceal a weak or adverse index-specific result.

## 6. Holdout and promotion boundaries

- LOT-042's 500-draw holdout is sealed: no reads, training, tuning, selection, ranking, cumulative p-values, or feedback.
- This pilot is development-only and cannot promote a model, alter a champion, or claim predictive efficacy.
- A reported-index candidate may be emitted for inspection only if its receipt preserves all input hashes, per-index training counts, target windows, sampler calibration, and the unresolved physical-regime status.
- A non-significant or adverse result means retain uniform as the statistical baseline; do not cherry-pick one index, one zone, or one time window.
- Any future claim about stable physical ball identity requires a separate authoritative regime/replacement chronology and a new preregistration.

## 7. Required fail-closed conditions

Reject the view or evaluation if any of the following occurs:

- inventory, coverage report, or ledger hash mismatch;
- raw evidence replay differs from the stored coverage report;
- a verified row lacks a draw ID/date match, source URL, observation ID, or integer index 1/2/3;
- a boolean index is accepted as integer;
- any regime or physical identity is silently assigned;
- duplicate draw IDs, non-chronological targets, insufficient same-index warm-up, or any future-row leakage;
- any attempt to access LOT-042 or use its outcomes for model selection.

**Interpretation ceiling:** this pilot can establish whether the source-reported index is a useful historical conditioning label in this development window. It cannot establish stable physical identity, mechanical bias, a random seed, or improved future lottery odds.
