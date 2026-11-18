# Official archive layout

The repository uses three distinct layers so that future model runs do not need to re-download historical official data.

## 1. Incoming — transport staging

`data/incoming/dlt_official_raw.zip`

Purpose: exact uploaded archive received from an external collection run.
- Temporary/staging artifact.
- Never edit or reserialize it.
- Verify its checksum before expansion.
- It is not the canonical analytical dataset.

## 2. Raw — immutable source snapshots

`data/raw/sporttery/2026-11-18/`

Purpose: extracted official HTTP response bodies and sidecar manifests, retained byte-for-byte.
- source URL
- retrieval timestamp
- HTTP status and content type
- SHA-256
- collector/parser version
- raw filename

This is the primary evidence layer.

## 3. Processed — deterministic analytical data

`data/processed/draws-20261118.jsonl`

Purpose: normalized draw records produced offline from raw snapshots.

A processed dataset is reproducible from a specific raw snapshot set and parser version. It never replaces the raw source.

## 4. Prize layer

Prize rows are deliberately separate from normalized draw rows.

The official raw response contains `prizeLevelList`; the future prize importer must preserve each complete source object and emit separate prize records with explicit source-to-derived mappings.

Do not force all historical draws into a fixed tier count. The audited 2026-11-18 snapshot contains prize-list lengths from 9 to 22 entries.

## Lifecycle

external collection -> data/incoming/*.zip -> data/raw/sporttery/<collection-date>/ -> data/processed/draws-*.jsonl -> model/backtest

`incoming` is the handoff boundary; `raw` is immutable evidence; `processed` is reproducible derived data.

## Trust labels

- `candidate_unverified`: provenance incomplete.
- `manifest_complete_not_officially_authenticated`: source manifest and integrity checks complete, but no independent cryptographic source signature.
- A normalized prize dataset must not be promoted to ground truth merely because its importer succeeds.