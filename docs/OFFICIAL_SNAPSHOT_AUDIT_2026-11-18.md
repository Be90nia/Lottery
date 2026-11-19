# Official Sporttery DLT snapshot audit — 2026-11-18

**Status:** snapshot audit passed for structural integrity and the checks listed below. The raw archive itself is not yet committed in this branch; see the repository handoff note below.

## Source snapshot

- Endpoint: `https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry`
- Game: `gameNo=85` (超级大乐透)
- Collection run: `20261118T035858Z`
- Retrieved: `2026-11-18T03:58:58Z` through `2026-11-18T03:59:36Z`
- HTTP status: 200 on all 30 page responses
- Page size: 100
- Source-reported total: 2,949 records / 30 pages
- Actual total: 2,949 records (29 × 100 + 49)

The uploaded archive contains 30 raw page response bodies, 30 per-page sidecar manifests, and one collection manifest.

## Checks performed against the uploaded ZIP

| Check | Result |
|---|---:|
| Raw page responses | 30 |
| Per-page sidecars | 30 |
| Records parsed | 2,949 |
| Unique draw IDs | 2,949 |
| Duplicate draw IDs | 0 |
| SHA-256 mismatches (page vs collection manifest) | 0 |
| SHA-256 mismatches (page vs sidecar) | 0 |
| Missing `prizeLevelList` | 0 |
| Null `prizeLevelList` | 0 |
| Empty `prizeLevelList` | 0 |
| Invalid draw dates | 0 |
| Invalid 5+2 number formats/ranges | 0 |

- First API row: draw `26131`, dated `2026-11-16`.
- Last API row: draw `07001`, dated `2007-05-30`.
- Draw-date coverage: `2007-05-30` through `2026-11-16`.
- Every raw JSON body round-trips through UTF-8 decode/encode without changing bytes.
- All page sidecars identify the Sporttery API host/path, `gameNo=85`, HTTP 200, a timezone-aware retrieval timestamp, the exact raw filename, and the matching SHA-256.

## Important prize-schema finding

All 2,949 draws contain a non-empty `prizeLevelList`, but the number of entries varies:

| Entries per draw | Draw count |
|---:|---:|
| 9 | 101 |
| 11 | 2,707 |
| 13 | 1 |
| 14 | 17 |
| 15 | 3 |
| 18 | 23 |
| 22 | 97 |

Observed original labels include ordinary tiers, additional-bet tiers, and promotion overlays. Therefore:

- Preserve each complete raw prize object exactly as received.
- Do not force every draw into a fixed 9-tier or 11-tier schema.
- Do not infer that a missing label means zero winners or zero payout.
- Do not collapse promotion rows into ordinary base/additional awards.
- Do not promote derived prize accounting until the source-field mapping and ruleset-specific reconciliation are independently tested.

This audit confirms structural presence and preservation, not the correctness of every historical prize amount or the physical authenticity of the draw process. HTTPS response metadata and SHA-256 manifests provide provenance/integrity evidence, not a source digital signature.

## Raw archive handoff

Expected archive contents are the original uploaded `dlt_official_raw.zip`:

- `collection-20261118T035858Z.manifest.json`
- `page-00001-*.json` through `page-00030-*.json`
- matching `page-*.manifest.json` sidecars

The archive is intentionally not represented as committed in this PR. After placing it in the repository, run:

```powershell
pwsh -File scripts/import_official_snapshot_archive.ps1 -ArchivePath .\data\incoming\dlt_official_raw.zip
```

The helper extracts immutable snapshots under `data/raw/sporttery/2026-11-18/` and invokes the existing offline snapshot importer to build the selected-number dataset. Raw prize objects remain available in the archived source JSON; the current normalized draws importer does not yet emit normalized prize rows.

## Trust status

Use the repository importer’s status `manifest_complete_not_officially_authenticated` for the normalized output. Keep the raw snapshot as the source of truth and treat any normalized prize dataset as a separate follow-up deliverable.
