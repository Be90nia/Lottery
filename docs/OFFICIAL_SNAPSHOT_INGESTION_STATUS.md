# Official snapshot ingestion status

## Current branch

`lot-050-official-snapshot-archive`

## Current state

The exact uploaded archive is staged at:

`data/incoming/dlt_official_raw.zip`

It contains 30 raw API response pages, 30 sidecar manifests, and one collection manifest. The audited snapshot contains 2,949 draws from 07001 through 26131.

## Required next transition

The archive must be expanded into:

`data/raw/sporttery/2026-11-18/`

The expanded files are immutable source evidence. Do not edit the JSON, reserialize it, or use a normalized dataset as a substitute for these files.

The deterministic draw importer may then produce:

`data/processed/draws-20261118.jsonl`

## Prize data is a separate transition

The raw source contains `prizeLevelList` for every draw. Because the list length varies from 9 to 22 entries, prize normalization must be ruleset-aware.

The next prize-ingestion deliverable is:

`data/processed/prizes-20261118.jsonl`

It must retain:
- draw ID and source position;
- complete raw prize object;
- source snapshot SHA-256;
- source URL and retrieval timestamp;
- parser version;
- occurrence identity;
- content fingerprint.

No prize amount should be inferred, filled, merged, or converted without an explicit tested mapping.

## Acceptance gates

The archive is considered **archived** only when the raw files exist under `data/raw/sporttery/2026-11-18/` and their hashes still match the incoming archive.

The draw dataset is considered **processed** only when the deterministic importer passes.

The prize dataset is considered **validated** only after schema mapping and historical ruleset reconciliation pass.

The model must consume only an accepted processed dataset, never the incoming ZIP directly.