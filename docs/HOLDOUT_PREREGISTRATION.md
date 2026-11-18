# Prospective holdout protocol (draft frozen specification)

**Status:** protocol specification drafted; prospective holdout has not started and no holdout outcomes have been inspected.

## 1. Why a new holdout is required

The existing 2,901-draw candidate dataset (07001–26083; SHA-256
`22cdd8aef049ee714020d3f5272b712cfef14da7fa7f276394ed8a1575901515`)
has already been used for exploratory model development, full-period scoring,
and calendar-era diagnostics. It is not an untouched holdout. The additional
48 draws mentioned in LOT-037 also cannot be retrospectively called an
untouched holdout if their outcomes are known during protocol development.

## 2. Freeze boundary

The prospective holdout must begin with the first official draw whose draw
timestamp is strictly later than the timestamp of the Git commit that freezes
this protocol and the scoring implementation.

Before collecting any holdout outcomes, archive:
- this protocol's Git commit and SHA;
- the exact scoring implementation commit and dependency/runtime versions;
- the canonical training-data file and SHA-256;
- the official raw-response snapshot(s), source URL, retrieval timestamp,
  HTTP metadata, response SHA-256, parser version, and run manifest;
- the pre-holdout model probability output for each eligible target, if
  forecasts are generated and timestamped before the draw.

A draw whose outcome was publicly available before the freeze timestamp is
ineligible, even if it is absent from the current repository dataset. Do not
backdate the freeze boundary.

## 3. Fixed models

No feature or hyperparameter search is permitted during the holdout.

| Model | Fixed specification |
|---|---|
| Uniform reference | Front inclusion probability 5/35; back inclusion probability 2/12 |
| Expanding frequency | Marginal inclusion counts over all eligible earlier draws; Dirichlet shrinkage alpha = 100 pseudo-draws |
| EWMA frequency | Marginal inclusion indicators with half-life = 100 draws; same alpha = 100 shrinkage |

The training window expands forward in time. Each target probability is
computed using only strictly earlier eligible draws. The target outcome is
scored only after it is officially published and captured. The implementation
must retain the current validation that each zone's marginal probabilities
sum to the number selected (5 and 2 respectively).

No positional, equipment, ball-set, pair, date, or other feature may be added
to these models under this holdout protocol.

## 4. Sample size and stopping rule

- Collect exactly **500 consecutive eligible draws** after the freeze boundary.
- Do not stop early for favorable or unfavorable interim results.
- Do not inspect cumulative model scores, significance tests, or model rankings
  while the holdout is accruing.
- If any draw is missing, disputed, corrected, or lacks acceptable source
  provenance, pause accrual and resolve it under a documented data-quality
  rule. Do not silently skip a difficult draw and continue the sequence.
- If source verification cannot be completed, the affected draw is not scored;
  report the protocol deviation and do not replace it with a hand-picked draw.

Five hundred draws is a prospective fixed target, not a guarantee of adequate
power for very small effects. Report uncertainty and do not extend the holdout
after seeing results.

## 5. Primary and secondary endpoints

Primary endpoints are mean per-number Brier score differences (candidate minus
uniform) for:
1. expanding frequency, front zone;
2. expanding frequency, back zone;
3. EWMA, front zone;
4. EWMA, back zone.

Negative values favor the candidate. Apply Holm step-down correction across
these four primary comparisons at familywise alpha = 0.05. Use paired moving
block bootstrap intervals with 10,000 replicates, block length 50 draws, and
a fixed, recorded seed. The bootstrap resamples target-draw score differences
as paired time blocks.

Bernoulli Log Loss is a prespecified secondary endpoint and must be reported
for all four comparisons with confidence intervals. It does not replace the
primary Brier endpoint. Top-k hits are descriptive only and cannot establish
forecasting skill.

Report absolute scores for all models, paired deltas, adjusted p-values,
confidence intervals, data completeness, and all deviations. No subgroup or
era selection is allowed as a success criterion.

## 6. Success and failure interpretation

A model is not promoted merely because one comparison is nominally favorable.
Any claim of improvement must:
- have a negative primary Brier delta;
- pass the four-comparison Holm procedure;
- have a paired 95% interval excluding zero in the favorable direction;
- show no material contradictory deterioration in secondary Log Loss;
- pass data provenance and leakage audits.

If neither candidate model meets all criteria, retain uniform as the reference
and record the prospective test as no demonstrated improvement. If any protocol
deviation compromises blinding, data integrity, or temporal ordering, label the
holdout compromised and do not reinterpret it as confirmatory.

## 7. Data and code integrity

The holdout input must be an independently captured official-source dataset,
not an extension silently merged into the legacy candidate. Every raw response
must be immutable and hashed. Parsed rows must preserve raw source metadata;
uncertain fields must not be assigned physical meaning without authoritative
documentation.

The run must be reproducible from a clean checkout and emit:
- protocol and code commit IDs;
- training and holdout SHA-256 values;
- exact eligible draw IDs and dates;
- per-draw probabilities and score contributions;
- aggregate primary/secondary metrics and Holm results;
- paired bootstrap configuration and outputs;
- source snapshot manifests and a machine-readable deviations log.

## 8. Current status

LOT-042 remains open. This document fixes a prospective design, but the holdout
cannot be considered started or completed until the freeze boundary is
committed, 500 subsequent eligible draws are captured and reconciled, and the
single final analysis is run. Do not use the existing historical eras as a
substitute for this future holdout.

## 9. Pre-draw forecast ledger implementation

The repository now includes `scripts/forecast_ledger.py` and
`lottery.forecast`. Before a target draw, create a record using a canonical
training JSONL and a full code commit SHA:

```bash
python scripts/forecast_ledger.py create data/canonical/draws.jsonl \
  --target-draw-id 27XXX \
  --target-draw-at 2027-01-01T20:30:00+08:00 \
  --code-commit <40-character-commit-sha> \
  --ledger data/holdout/forecast-ledger.jsonl
python scripts/forecast_ledger.py verify data/holdout/forecast-ledger.jsonl
```

The command refuses a target timestamp that is not strictly in the future,
requires the target calendar date to follow the latest training draw date,
validates the training records, hashes the exact training file bytes, and
records the fixed uniform/expanding/EWMA marginal probabilities. Each ledger
event includes its training range, dataset hash, model parameters, code
commit, UTC creation timestamp, sequence, previous-event hash, and event hash.
Duplicate target IDs, broken chains, and altered records are rejected.

The hash chain detects accidental edits, truncation, or reordering when the
original chain head is retained independently. It is not a digital signature,
does not authenticate the source dataset, and cannot prove that the command
was run before the result became public. Archive the ledger and its latest
hash outside the working checkout before the draw. Use a single writer; do not
have concurrent processes append to the same ledger.

This tool records forecasts only. It does not fetch outcomes, inspect scores,
or declare the prospective holdout started. LOT-042 remains open until the
frozen protocol's 500 eligible future draws are collected and analyzed once.
