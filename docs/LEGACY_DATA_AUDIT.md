# Legacy Dataset Audit

## Scope and provenance

The repository `rbk64513-debug/dlt-analysis` contains `public/data/dlt_clean.json`, a derived JSON array. It was imported here as a **candidate dataset**, not as immutable raw source data.

- Source: https://github.com/rbk64513-debug/dlt-analysis/blob/main/public/data/dlt_clean.json
- Git blob SHA: `bde880c7272f70b4e558ee01b58c63c1e65e632c`
- Source file size reported by GitHub: 3,823,201 bytes
- Draw coverage: `07001` (2007-05-30) through `26083` (2026-07-25)
- Draw records: 2,901
- Prize rows: 33,098
- Prize label variants: 25

Imported files:
- `data/candidates/legacy_draws.jsonl`
- `data/candidates/legacy_prizes_part_01.jsonl` through `legacy_prizes_part_09.jsonl`
- `data/candidates/legacy_manifest.json`

Money fields are represented as decimal strings in the imported candidate files. This avoids introducing further binary floating-point calculations, but cannot restore the exact lexical representation lost when the original cleaner converted source values to Python `float`.

## Structural audit results

| Check | Result |
|---|---:|
| Draw records | 2,901 |
| Unique draw IDs | 2,901 |
| Duplicate draw IDs | 0 |
| Draws with valid front/back numbers | 2,901 |
| Draws with valid recorded draw order | 2,341 |
| Missing draw order | 560 |
| Equipment code 0 (unknown / no recorded code) | 565 |
| Equipment code 1, 2, or 3 | 2,336 |
| Legacy promotion flag set to true | 141 |
| Missing sales values | 1,398 |
| Prize rows | 33,098 |
| Prize label variants | 25 |

All 2,901 records have five distinct front numbers in 1..35 and two distinct back numbers in 1..12. Draw IDs are unique, and dates are in ascending order. For all 2,341 non-null draw-order records, the first five values are a permutation of the front numbers and the last two are a permutation of the back numbers.

The 141 legacy promotion flags form these six contiguous ranges:

- 21039–21059
- 22040–22068
- 23039–23059
- 24030–24062
- 25038–25057
- 26050–26066

These ranges are observations about the imported file, not yet an independently verified official promotion calendar.

## Known cleaning-script defects and interpretation risks

The original `scripts/clean_dlt.py` was inspected. It contains several issues that prevent automatic promotion of this candidate to trusted research data:

1. **Promotion boolean conversion:** `bool(r.get("lotteryPromotionFlag"))` is unsafe if the API ever supplies strings such as `"0"` / `"1"`; `bool("0")` is true in Python. The raw source field types were not retained in this cleaned file, so the 141 flags need reconciliation against raw API snapshots.
2. **Prize award type filter is a no-op:** the code says `if p.get("awardType") != 0: pass`, then appends the row anyway. All original labels are preserved here; we do not guess which award types should be excluded.
3. **Binary floating-point money:** the old cleaner converts monetary fields with `float()`. Financial reconciliation must use official raw values and decimal arithmetic.
4. **Missing values are not uniform:** 560 missing order values, 1,398 missing sales values, and equipment code 0 must remain unknown rather than be imputed.
5. **Promotion prize semantics:** 21 draws (23039–23059) contain 147 promotion prize rows across tiers 3–9 where the recorded per-ticket `amount` is 0 while `total` is positive. These rows must not be interpreted as ordinary `amount × winner_count` prize rows.
6. **Download provenance:** the old downloader reuses existing page cache files and silently overwrites duplicate draw IDs in a dictionary. It does not store response hashes or a per-run manifest.

## Decision

**Status: candidate / not yet trusted for confirmatory statistics or predictive training.**

The selected-number fields pass structural checks and can support parser fixtures and provisional exploratory work. Prize accounting, promotion flags, equipment metadata, and source completeness remain quarantined pending comparison with immutable official API snapshots.

The new collector in `src/lottery/ingest.py` is the intended path for obtaining fresh immutable source snapshots. Once live API retrieval and pagination have been verified, we should reconcile the overlap and extend the candidate beyond 26083 before publishing a trusted canonical dataset.
