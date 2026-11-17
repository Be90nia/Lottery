# Architecture

## Data flow

`official sources -> immutable raw snapshots -> parsing -> normalization -> validation -> canonical dataset -> analysis/features/backtests/reports`

Each stage must be reproducible and must retain references to its inputs and code version.

## Layers

- **Sources:** official result pages/APIs and authoritative rule notices.
- **Raw:** exact source payloads, retrieval timestamp, source URL, content hash.
- **Ingestion:** transport, pagination, retries, and source-specific parsing.
- **Canonical:** normalized draw records and separately normalized prize records.
- **Metadata:** rule eras, equipment, ball sets, and documented incidents with provenance and confidence.
- **Analysis:** descriptive statistics, simulation tests, anomaly screening.
- **Experiments:** time-aware features, baselines, models, and backtests.
- **Reporting:** generated tables and reports linked to dataset and code revisions.

## Invariants

1. Raw snapshots are immutable; corrections create new versions.
2. Every canonical row can be traced to source records.
3. Invalid records are quarantined with explicit reasons, not silently discarded.
4. Draw numbers and dates are identifiers/data, not inferred from adjacent records.
5. Post-draw information must never enter pre-draw prediction features.
6. Training and evaluation splits are chronological.
7. Exploratory analysis and confirmatory tests are labeled separately.

## Storage

Keep source code, schemas, manifests, compact metadata, and reports in Git. Large raw or derived datasets should use Git LFS or versioned external storage, with checksums and manifests committed to Git. Do not commit secrets or access tokens.

## Suggested package layout

```
src/lottery/
  sources/
  ingest/
  schemas/
  normalize/
  validation/
  statistics/
  features/
  models/
  backtest/
  prizes/
  reporting/
data/
  raw/
  interim/
  processed/
tests/
  unit/
  integration/
  fixtures/
configs/
reports/
```
