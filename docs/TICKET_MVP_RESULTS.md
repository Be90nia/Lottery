# Ticket MVP: first full rolling-origin results

**Status: no predictive strategy is promoted.** These are exploratory results on an unverified historical candidate dataset, not official-source-authenticated evidence.

## Reproducibility

- Input: `data/candidates/legacy_draws.jsonl`
- Input SHA-256: `22cdd8aef049ee714020d3f5272b712cfef14da7fa7f276394ed8a1575901515`
- Rows: 2,901 (07001 / 2007-05-30 through 26083 / 2026-07-25)
- Rolling-origin minimum training history: 300 draws
- Evaluation: 2,601 strictly chronological targets, 09054 through 26083
- Models: uniform, expanding-frequency (alpha=100), EWMA (half-life=100 draws)
- Uncertainty: paired moving-block bootstrap, 1,000 replicates, 50-draw blocks, seed 20261118
- CI run: [44437002993](https://github.com/Be90nia/Lottery/actions/runs/44437002993)
- Artifact: `lottery-research-reports`, containing `rolling-origin-benchmark.json`

The score is mean marginal Bernoulli log loss per number, not a joint 7-number ticket NLL. Lower is better.

## Mean scores

| Zone | Model | Brier / number | Log loss / number |
|---|---|---:|---:|
| Front | Uniform | 0.122449 | 0.410116 |
| Front | Expanding | 0.122517 | 0.410388 |
| Front | EWMA | 0.122406 | 0.409976 |
| Back | Uniform | 0.138889 | 0.450561 |
| Back | Expanding | 0.139005 | 0.450977 |
| Back | EWMA | 0.139013 | 0.451004 |

## Paired log-loss difference versus uniform

Negative means the candidate model is better; positive means worse.

| Model | Zone | Mean delta | 95% moving-block interval |
|---|---|---:|---:|
| Expanding | Front | +0.000272 | [-0.000441, +0.000913] |
| Expanding | Back | +0.000416 | [+0.000105, +0.000720] |
| EWMA | Front | -0.000140 | [-0.000631, +0.000346] |
| EWMA | Back | +0.000443 | [+0.000026, +0.000778] |

## Decision

1. Expanding-frequency does not beat uniform on either zone; its paired back-zone interval is wholly worse.
2. EWMA has a tiny front-zone mean improvement, but its interval crosses zero; this is not evidence of a reliable advantage.
3. EWMA is worse on the back zone, with the paired interval above zero.
4. Higher top-k hit counts are descriptive only and do not override worse or inconclusive proper scoring rules.
5. No strategy is eligible for promotion. Keep uniform as the reference baseline and keep expanding/EWMA as exploratory candidate generators only.

## Limitations and next gates

- The 2,901-row input is still an unverified candidate; its checksum establishes byte identity, not official authenticity.
- This comparison does not correct for all prior model/parameter exploration and must not be treated as a preregistered confirmatory test.
- The marginal Bernoulli score is not a calibrated joint probability for a complete 5+2 ticket.
- Do not access or tune against the isolated prospective 500-draw holdout.
- Before model promotion: authenticate the dataset; freeze model and evaluation protocol; complete the dedicated #41 comparison and checkpoint/resume work; require robust improvement over uniform on both zones or a preregistered, explicitly scoped claim; and retain the full score ledger and uncertainty report.


The current one-command MVP smoke run uses the pinned 2,949-row candidate snapshot ending at draw 26131 (2026-11-16), SHA-256 `9f4cc51b76fd258dd056e0b86f675192d3d9a41c2901f771cab778c65ec2b6aa`. Its manifest trust status remains `manifest_complete_not_officially_authenticated`; this is a fresher candidate input, not an official-authentication claim. The older 2,901-row legacy candidate remains available for the historical benchmark reproduction.


## Latest pinned-input smoke (2026-11-19)

GitHub Actions run `44470702950` completed successfully and uploaded `ticket-mvp-candidates` (artifact SHA-256 `d5ac8018bcd045b7b79de7e0e4064376321ce903184cbcdb8de84093886cc248`). It generated 15 candidate tickets: five each for `uniform`, `expanding`, and `ewma`, from 2,949 records spanning draw `07001` through `26131` (2026-11-16). Dataset SHA-256: `9f4cc51b76fd258dd056e0b86f675192d3d9a41c2901f771cab778c65ec2b6aa`; adjacent manifest SHA-256: `21e225e772d9c3192eb5878d3546e20d2560ea826ec5ee21bfabf300ceedb315`. Trust status remains `manifest_complete_not_officially_authenticated`. Receipt status is `candidate_batch_generated`; automatic sync, model training, and model promotion were not performed.
