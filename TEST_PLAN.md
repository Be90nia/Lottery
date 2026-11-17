# Test Plan

## Unit tests
- Source parser behavior for valid, missing, malformed, and unexpected fields.
- Draw number bounds, uniqueness, count, and leading-zero preservation.
- Draw-order permutation validation.
- Exact monetary arithmetic and prize-tier mapping.
- Rule-period and promotion-boundary behavior.

## Data integrity tests
- Duplicate draw identifiers.
- Conflicting source snapshots.
- Missing periods and unexpected date ordering.
- Source hash and manifest consistency.
- Quarantine behavior for invalid records.

## Statistical tests
- Simulated legal draws reproduce expected marginal frequencies within Monte Carlo uncertainty.
- Fixed-size sampling assumptions are respected.
- Multiple-testing correction is applied to exploratory scans.
- Test outputs are deterministic for a fixed analysis seed.

## Backtest tests
- No future rows enter training features.
- Splits are chronological and reproducible.
- Random baseline follows the official draw structure.
- Model selection never reads the final holdout.
- Metrics are computed on exactly the declared evaluation period.

## Integration tests
- Ingestion from saved fixtures without network access.
- End-to-end raw-to-canonical pipeline.
- Reproducible report build from a pinned dataset version.

## Release gate

No release should publish predictive claims without an untouched chronological evaluation, a legal random baseline, uncertainty reporting, and reproducible artifacts.
