# LOT-063 prospective schedule runner

The schedule runner provides an idempotent command boundary for an external
trusted scheduler. It does not discover the current Champion registry, load
model artifacts, generate a forecast, or authorize a user-facing prediction.

## Schedule contract

A schedule JSON document has schema `lottery.prospective-schedule/v1`,
a canonical `schedule_id` (SHA-256 over the complete document excluding
`schedule_id`), a timezone-aware `generated_at_utc`, and a non-empty
`expected_forecasts` array. Each record contains the complete expectation
identity: target/cutoff, zone and population key, front/back artifact hashes,
registry snapshot and generation, model specification, training snapshot and
range, policies, model family, code revision and runtime.

The runner rejects duplicate artifact × target × zone × population slots,
unknown/missing fields, schedule digest mismatches, invalid chronology and
schedules generated after the target cutoff.

## Operations

Register expected slots before cutoff:

```sh
python scripts/run_prospective_schedule.py \
  --schedule expected-slots.json \
  --ledger data/prospective/ledger.jsonl \
  --mode register
```

At/after cutoff, finalize slots without an issued forecast:

```sh
python scripts/run_prospective_schedule.py \
  --schedule expected-slots.json \
  --ledger data/prospective/ledger.jsonl \
  --mode finalize
```

Registration preflights the entire schedule against a temporary ledger before
writing any real expectation. Real writes are individually idempotent, so a
process interruption can be retried safely. Finalization uses the ledger's
actual UTC clock; a caller cannot backdate the check time. Existing issued or
missing terminal records are skipped and cannot be rewritten or backfilled.

A partial run returns a non-zero exit code and lists each failed slot. The
ledger remains the source of truth for expected, issued, missing and unresolved
denominators.

## Explicit limits

This is a callable schedule runner, not a hosted cron service. A protected
scheduler must still obtain a verified registry snapshot, construct and sign
the schedule, invoke the runner before each cutoff, and invoke finalization
after cutoff. The runner does not grant access to LOT-042 and does not perform
forecast generation, model refresh, promotion, rollback or serving.
