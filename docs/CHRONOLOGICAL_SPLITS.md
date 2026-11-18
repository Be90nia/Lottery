# Chronological dataset splitting

The repository provides a deterministic, no-shuffle train/validation/test split
for exploratory model development.

```bash
python scripts/split_dataset.py data/candidates/legacy_draws.jsonl \
  --output-dir data/splits/legacy-70-15-15
```

Defaults are 70% training dates, 15% validation dates, and the remaining 15%
test dates. The utility validates the complete input and requires it to be
chronologically sorted. It splits only between distinct draw dates, so two
records on the same date can never land in different partitions. It writes
`train.jsonl`, `validation.jsonl`, `test.jsonl`, and
`split-manifest.json` containing input/output SHA-256 hashes, actual row
fractions, date and draw boundaries, and validation metadata.

Because the split is date-grouped, actual row fractions can differ slightly
from the requested fractions. At least three distinct draw dates are required.

This utility is not a replacement for leakage-safe rolling-origin backtests.
It does not create or start the preregistered 500-draw prospective holdout, and
the candidate input retains its existing `candidate_unverified` provenance
status. Do not tune models repeatedly against the static test partition and
then describe it as untouched.
