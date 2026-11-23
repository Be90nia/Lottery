# G1 official-source provenance audit — 2026-11-23

## Scope

This audit covers the 2026-11-18 Sporttery Super Lotto historical snapshot used by the model. It does not access LOT-042. It separates three different claims:

1. **Byte integrity:** stored bytes match declared SHA-256 values.
2. **Source provenance:** capture metadata points to the expected official HTTPS endpoint and records status/time.
3. **Source authenticity:** an independently trusted signature or equivalent proves who produced the response.

The repository currently supports the first two as auditable metadata. It does not have a Sporttery response signature, so it must not claim the third.

## Canonical snapshot facts

The processed snapshot is `data/processed/draws-20261118.jsonl`:

- 2,949 rows and 2,949 unique draw IDs.
- Draw ID range: 07001–26131.
- Draw-date range: 2007-05-30–2026-11-16.
- The processed manifest records 30 raw-page SHA-256 values and 30 per-page provenance-complete flags.
- Current trust label remains `manifest_complete_not_officially_authenticated`.

The repository's archive-layout note distinguishes the incoming ZIP, immutable raw snapshots, and processed analytical data. The raw page bodies and sidecars are retained in `data/incoming/dlt_official_raw.zip`; the documented expanded raw directory is not currently committed.

## Archive audit implementation

`scripts/audit_official_snapshot_archive.py` now independently checks:

- ZIP CRC/readability, safe member paths, exact page/sidecar/collection-manifest inventory.
- 30 contiguous page numbers and expected 2,949-record pagination (29 × 100 plus 49).
- Every raw page's SHA-256 against its filename and sidecar.
- Sidecar source name, HTTPS host/path, gameNo=85, pageNo, HTTP 200, JSON content type, collector version (`raw-snapshot-collector/1.0.0`), run ID and timezone-aware retrieval timestamp. The importer parser is separately recorded as `0.1.0`; these are different stages and must not be conflated.
- A single collection run and bounded retrieval interval.
- Raw page parsing through the repository ingestion parser.
- Raw-page SHA-256 inventory against the processed manifest.
- Byte-for-byte rebuilding of the processed JSONL from the raw response bodies.
- Crosswalk row agreement with the canonical processed dataset.

CI now invokes this audit and includes its JSON report in the research artifact bundle. The first CI attempt exposed an incorrect assumption in the new audit: sidecars identify the collection tool as `raw-snapshot-collector/1.0.0`, while `0.1.0` is the later offline importer parser. The verifier and fixture were corrected to validate these as separate versions. CI run #1327 (`45108013254`) passed the archive audit; run #1333 (`45108455907`) passed again after the verifier was strengthened to validate the collection manifest page inventory entry-by-entry and compare its pagination metadata against each raw API response. Run #1333 completed successfully with 289 unit tests (one pre-existing long-form test skipped), workflow security policy, Windows ledger-lock tests, crosswalk verification and all data/research smoke steps. The audit reported a 676,600-byte ZIP with SHA-256 `e112babccdd387aa8cf54e7bba46e4162defac8284a9f9c3acb1f51f53b55c30`, 30 pages, 30 sidecars, 2,949 raw/unique draws, and byte-identical processed JSONL reconstruction with SHA-256 `9f4cc51b76fd258dd056e0b86f675192d3d9a41c2901f771cab778c65ec2b6aa`. The collection manifest contains 30 page entries; each page number, filename, SHA-256, record count, retrieval timestamp and source pagination metadata is now cross-checked against its raw page and sidecar. The collection run ID/version/start/end timestamps are also bound to the per-page records.

## Official announcement crosswalk sample

The crosswalk registry now has 23 rows:

- 16 purposive convenience crosswalks.
- 7 matches from the reproducible 16-row, one-draw-per-year stratified random sample.
- 9 of the 16 random selections still have no located official DLT announcement URL in this search pass.

Two additional random-sample matches were found and compared with the canonical processed snapshot:

| Draw | Date | Front result | Back result | Front order | Back order | Equipment |
|---|---|---|---|---|---|---:|
| 25006 | 2025-01-13 | 03 04 13 19 35 | 03 10 | 03 35 04 13 19 | 10 03 | 2 |
| 26025 | 2026-03-11 | 03 15 24 28 29 | 03 07 | 24 29 28 15 03 | 03 07 | 2 |

Official announcement sources:
- Draw 25006: Guangdong Sports Lottery Center official PDF: https://www.gdlottery.cn/f_html/kjgg_pdf_bak/AN.307-%E8%B6%85%E7%BA%A7%E5%A4%A7%E4%B9%90%E9%80%8F-25006%E6%9C%9F-20250113215113882.pdf
- Draw 26025: Guangdong Sports Lottery Center official announcement: https://www.gdlottery.cn/f_html/kjgg/P085_26025.html

The values match the canonical processed rows. The registry deliberately records `url_transcribed_not_archived`: the raw HTML/PDF response bytes and their retrieval hashes have not yet been added. These are additional official-page cross-checks, not cryptographic attestations.

The remaining nine selected IDs are: 11038, 12120, 13071, 14128, 15138, 16029, 18070, 19011, and 23048. Search results that expose only third-party pages or news articles without official draw-order/equipment fields are not promoted to official crosswalk evidence.

## Known ingestion gap

The existing `ingest_snapshot_directory` validates each page's sidecar digest and selected endpoint metadata. The new archive-level audit additionally checks ZIP CRC/readability, the exact 30-page/30-sidecar inventory, collection-level run metadata, and every entry in the collection manifest's `pages` array against the corresponding raw page, sidecar and API response metadata. It also rebuilds the processed JSONL byte-for-byte from the raw pages. This full archive audit passed in CI run #1333.

## G1 disposition

**Status: IN PROGRESS — not yet PASS.**

Reasons:
- Archive-level audit is implemented but the current-head CI run must pass before it is accepted.
- Nine random-sample official announcement URLs remain unlocated.
- Crosswalk source HTML/PDF bytes are not archived.
- No cryptographic signature or independent publisher identity proof exists for the raw API responses.

Do not upgrade the trust label to authenticated. Keep `manifest_complete_not_officially_authenticated` and keep Shadow/production authorization disabled until the remaining G1 requirements are resolved.
