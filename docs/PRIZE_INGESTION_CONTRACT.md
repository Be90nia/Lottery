# Official prize ingestion contract (LOT-049)

**Status:** implementation contract; not evidence that official raw prize snapshots have been obtained or reconciled.

This contract deliberately separates immutable source capture, lossless extraction, and interpretation. The existing `legacy_prizes_part_*.jsonl` files remain candidate-only and must never be rewritten in place.

## 1. Scope and non-goals

The importer consumes authorized, already-captured Sporttery history API response bodies. It does not bypass the upstream WAF, scrape alternative mirrors as if they were official, infer omitted fields, repair candidate amounts, or calculate final payouts.

The expected envelope is the same history response shape used by draw ingestion:

- top-level JSON object;
- `value.list` contains draw objects;
- each draw object may contain `prizeLevelList`.

The presence, completeness, and exact semantics of `prizeLevelList` must be verified against actual official response snapshots before this importer can be accepted. A draw with no prize list is a coverage gap, not a draw with zero prizes.

## 2. Input and provenance

Input directory contains exact response bytes as `*.json` and a matching `<stem>.manifest.json` sidecar. The importer runs offline.

Required sidecar fields:

| Field | Contract |
|---|---|
| `source` | `Sporttery public historical draw API` |
| `url` | HTTPS URL on `webapi.sporttery.cn`, expected history endpoint and `gameNo=85` |
| `retrieved_at` | timezone-aware ISO-8601 timestamp |
| `http_status` | integer 200 |
| `content_type` | response content type, retained verbatim |
| `sha256` | lowercase SHA-256 of exact raw response bytes |
| `parser_version` | version string |
| `raw_file` | exact sibling filename |

A sidecar is provenance metadata, not a cryptographic signature. Recompute the digest from bytes; never trust the sidecar digest alone. Missing or invalid manifests fail closed when `--require-manifests` is set. Do not synthesize retrieval times or source URLs.

## 3. Lossless output record

Write one JSONL record per prize object. Suggested stable envelope:

```json
{
  "record_schema": "sporttery-prize-raw/v1",
  "draw_id": "26029",
  "draw_date": "2026-03-xx",
  "source": {
    "source_name": "Sporttery public historical draw API",
    "source_url": "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry?gameNo=85",
    "retrieved_at": "2026-11-18T00:00:00+00:00",
    "http_status": 200,
    "content_type": "application/json",
    "snapshot_sha256": "<sha256 of exact response bytes>",
    "raw_file": "page-00001-<digest>.json",
    "parser_version": "..."
  },
  "source_position": {
    "draw_index": 0,
    "prize_index": 0
  },
  "raw_prize": {
    "prizeLevel": "一等奖",
    "stakeAmount": "...",
    "stakeCount": "...",
    "totalPrizeamount": "...",
    "lotteryCondition": "..."
  },
  "raw_prize_sha256": "<canonical JSON hash for duplicate diagnostics>",
  "row_id": "<hash of snapshot digest + draw ID + source positions>"
}
```

The example values are illustrative only; do not copy them into production data. The complete `raw_prize` object must be preserved, including unknown keys, nulls, numeric/string distinctions, and nested values. Do not coerce amounts, normalize labels, drop fields, or reinterpret identifiers in this layer.

The output envelope may add parser metadata, but it must not mutate the embedded source object. JSON serialization must preserve JSON value types. Exact source bytes remain the authoritative artifact; JSON object reserialization is not byte-preserving.

## 4. Identity and duplicate policy

There are two different concepts and they must not be conflated:

- **Occurrence identity:** `snapshot_sha256 + draw_id + draw_index + prize_index`. This identifies where an object appeared in a specific immutable response.
- **Content fingerprint:** SHA-256 of deterministic canonical JSON for the complete raw prize object. This is diagnostic only, not a unique business key.

Never use displayed label alone as a key. Do not silently deduplicate equal fingerprints: two identical objects may be distinct source occurrences. Emit duplicate-fingerprint groups to a quarantine/report file with every occurrence reference. Conflicting draw IDs or conflicting source records are also quarantined, never overwritten.

If a future official schema supplies stable row identifiers, preserve them exactly and document their observed scope before using them as a business key.

## 5. Coverage and failure semantics

The import report must include:

- input snapshot count, bytes, and SHA-256 for every input;
- parsed draw count and prize-object count;
- draw IDs with missing `prizeLevelList`;
- empty prize lists separately from missing lists;
- malformed list entries (non-object values);
- duplicate content-fingerprint groups and all occurrence references;
- duplicate/conflicting draw identities;
- source and parser versions;
- output file SHA-256 and record count;
- explicit trust status.

Fail the run on invalid JSON, malformed response envelope, invalid manifest/hash, missing required draw identity, or a non-object prize entry. Do not silently skip malformed rows. A missing `prizeLevelList` is recorded as a coverage gap; acceptance must fail if any in-scope draw lacks the list unless an independently documented source-version exception explains it.

No prize rows is not a successful empty import.

## 6. Derived interpretation is a separate stage

A later normalizer may derive fields only when their source mapping is explicit and tested. It must retain both source and derived values, for example:

- `source_prizeLevel` → derived display label (no rewrite of source);
- `source_stakeAmount` → parsed decimal amount plus currency/unit metadata;
- `source_stakeCount` → parsed count;
- `source_totalPrizeamount` → parsed aggregate amount;
- `awardType`, `prizeLevelNo`, `relatedPrizeLevelNo`, `sort`, `singleUnitBetPrizeDescr` → preserved verbatim; semantics remain unknown until documented from official evidence.

Base/additional/promotion classification must not be inferred solely from a label if official identifiers or campaign rules contradict it. Unknown values remain unknown. Monetary calculations use Decimal or integer minor units, never binary float.

## 7. CLI and output layout

Target command:

```bash
python scripts/ingest_prizes.py \
  --snapshots-dir data/raw/sporttery-prizes \
  --require-manifests \
  --output data/interim/official_prizes_raw.jsonl \
  --report data/interim/official_prizes_ingest_report.json
```

Raw snapshots remain immutable under `data/raw/`. Extracted raw prize records and reports belong under `data/interim/`. A canonical prize dataset must not be written or promoted by this command.

## 8. Required tests

1. Full raw object round-trip with unknown, nested, null, boolean, integer, and string fields.
2. Preserve missing optional keys as missing; do not insert nulls.
3. Reject invalid JSON, invalid envelope, non-object draw, and non-object prize item.
4. Reject missing/invalid manifest, wrong URL host/path/game number, non-200 status, naive timestamp, and SHA-256 mismatch.
5. Distinguish missing `prizeLevelList` from an explicitly empty list.
6. Emit all duplicate-fingerprint occurrences without dropping either row.
7. Ensure occurrence IDs differ for different positions/snapshots even when content fingerprints match.
8. Detect duplicate/conflicting draw IDs across snapshots; no last-write-wins behavior.
9. Deterministic output/report hashes for identical inputs and parser version.
10. Linux and Windows CI.
11. Regression: existing draw-only ingestion output and all existing tests remain unchanged.

## 9. Acceptance gates

LOT-049 can close only after code, tests, docs, and CI pass and at least one authorized official raw snapshot fixture demonstrates the actual prize schema. LOT-018 remains open until all candidate rows in scope are reconciled against immutable official snapshots, including the 07001 extra-tier labels, the 17045–17063 discrepancy window, and promotion campaign totals.

Even after importer acceptance, source capture coverage and accounting reconciliation are separate gates. An importer that faithfully preserves bad or incomplete source data does not certify the data as correct.
