# Data Sources and Ingestion Status

## Primary candidate: China Sports Lottery public history API

- Endpoint: `https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry`
- Product parameter: `gameNo=85` (Super Lotto / 大乐透)
- Other parameters used by the collector: `provinceId=0`, `pageSize=100`, `isVerify=1`, `pageNo=N`.
- Expected response path: `value.list`.
- Pagination metadata recognized when present on page 1: positive integer `value.total` and `value.totalPage`.
- Fields currently consumed: `lotteryDrawNum`, `lotteryDrawTime`, `lotteryDrawResult`; uncertain fields remain raw evidence.

The endpoint and field names are corroborated by multiple public implementations and technical references, but this repository's runtime collector must still verify live availability, pagination completeness, and field semantics before a dataset is promoted to a trusted release. The web research interface could not directly retrieve the API response during initial setup.

## Append-only publication requires a raw-page pagination attestation

Complete per-page sidecars do **not** prove that the source returned the complete
history. The append-only gate therefore requires all of the following:

- `source_completeness_verified: true` and a
  `source_completeness_attestation` object with schema
  `sporttery-pagination-attestation-v1`.
- Source-reported total records and total pages, page size, and JSON Pointer
  paths into page 1's exact raw response for both totals.
- A contiguous page inventory from 1 through the source-reported final page,
  with each raw filename, SHA-256, and parsed record count.
- A matching raw response file and sidecar for every page. The gate re-hashes
  each byte stream, verifies the exact official endpoint/query and one fetch
  run, parses each page again, checks full/terminal page counts against the
  source totals, rejects duplicate draw IDs, and compares the reconstructed
  rows with the candidate dataset.
- The CLI requires `--snapshots-dir`; a manifest boolean alone is never
  sufficient.

The attestation object has this exact shape (values below are illustrative;
the JSON Pointer paths must resolve in the actual page-1 response):

```json
{
  "schema": "sporttery-pagination-attestation-v1",
  "source_total_records": 3,
  "source_total_pages": 1,
  "page_size": 100,
  "metadata_page_no": 1,
  "total_records_pointer": "/value/total",
  "total_pages_pointer": "/value/totalPage",
  "pages": [
    {
      "page_no": 1,
      "raw_file": "page-00001-<sha-prefix>.json",
      "sha256": "<64 lowercase hex characters>",
      "records": 3
    }
  ]
}
```

The offline importer emits this attestation only when page 1 contains both
positive integer pagination fields and the values reconcile with the exact
raw-page inventory, expected full/terminal page counts, and deduplicated draw
IDs. Missing metadata leaves `source_completeness_verified: false`; malformed
or inconsistent totals fail closed. Do not flip the boolean manually. The
current hosted-runner probe has not yet produced a live successful response,
so this code path is covered by deterministic fixtures but not yet verified
against a fresh upstream response. The gate does not cryptographically
authenticate the upstream operator or prove that the upstream source itself
is authoritative.

## Preservation and trust

The collector archives exact response bytes before parsing and writes a sidecar manifest containing retrieval time, URL, HTTP status, content type, SHA-256, and parser version. A parse failure does not silently skip a row. Conflicting duplicate draw identifiers stop the run.

## Known limitations

- The collector currently uses `lotteryDrawResult` for the selected numbers and sorts each zone for canonical comparison.
- It intentionally does not infer draw order, equipment, ball-set, prize tiers, or promotion details.
- When page 1 provides valid `value.total` and `value.totalPage`, the collector fetches exactly that many pages and verifies each page's expected record count. Otherwise it falls back to empty/short terminal-page detection; that fallback never proves completeness. An empty first page is treated as a source/availability failure. If `--max-pages` is reached while the last page is full, the collector fails closed and does not publish normalized output.
- The repository contains a pinned 2,949-row candidate snapshot for reproducible MVP runs, with trust status `manifest_complete_not_officially_authenticated`. It is not a newly fetched canonical dataset. Live raw snapshots and generated canonical candidates remain run-scoped artifacts and are not committed by default.

## References

- Public endpoint usage example: https://zelvan.cn/projects/dlt-spider/
- Example showing `gameNo=85` and `lotteryDrawNum` / `lotteryDrawResult`: https://github.com/Lucasyao1985/lottery-skills/blob/main/daletou/scripts/dlt.py
- Additional endpoint example: https://github.com/FranklinDX3906/Lottery/blob/master/data/numbers_get.py

These are corroborating technical examples, not substitutes for the official source itself.

## Network access observation (2026-11-17)

A read-only one-page probe from GitHub Actions using the documented endpoint, mobile browser headers, and no `termLimits` parameter received HTTP 567 after three attempts. The response was reported by urllib as `HTTP Error 567: Unknown Status`; no JSON payload was returned, so no official sample was parsed.

Independent recent technical documentation for Sporttery's API host reports Tencent Cloud EdgeOne WAF responses of HTTP 403/567 and rejection of datacenter egress IPs. This is consistent with the observed GitHub-hosted runner failure. We will not attempt to evade this access control with an unapproved relay. Live verification must use an authorized access path or user-provided official response snapshots.

References:
- https://github.com/Johnserf-Seed/SportteryAPI/blob/main/README.zh-CN.md
- https://github.com/Johnserf-Seed/SportteryAPI/blob/main/src/upstream.ts


## Independent historical CSV snapshot

On 2026-11-18, a second maintained dataset was retrieved from [cs4745/PickWise](https://github.com/cs4745/PickWise), file `data/dlt.csv`, at source commit `2f6f125e8f5f3c23460ae4ba9d60a73531c46dc9`. The source repository includes an MIT license; its license notice is retained in `data/candidates/PICKWISE_ATTRIBUTION.md`.

The source's accompanying `data/validation.json` reports 2,948 DLT records through issue 26130, 2,948 records checked against 500彩票网, and zero reported conflicts. These are source-reported validation claims, not our independent re-performance of the 500彩票网 check.

Our direct comparison against the imported 2,901-record legacy candidate found:
- 2,901 overlapping draw IDs;
- 2,901 exact matches across draw date, front numbers, and back numbers;
- 0 mismatches;
- 0 legacy-only IDs;
- 47 additional IDs in the independent snapshot, from 26084 through 26130.

This is a strong independent consistency check for the selected-number and date fields in the overlapping period. It does not validate legacy prize rows, promotion flags, equipment/ball-set labels, or draw-order metadata. The independent snapshot ends at 26130; it does not contain 26131.

The preserved CSV is a secondary source snapshot, not a replacement for immutable official API response bodies. Re-run `python scripts/reconcile_sources.py` to reproduce the overlap check. Do not merge its 47 additional records into the canonical dataset until the official-source provenance and issue 26131 boundary are resolved.

## Offline raw-snapshot import

When the API cannot be reached from an authorized runtime, raw JSON response files obtained through an authorized channel can be placed in a directory and parsed without making network requests:

```bash
python scripts/fetch_history.py \
  --snapshots-dir data/raw/user-supplied \
  --require-manifests \
  --output data/processed/from-snapshots.jsonl
```

The importer reads each `*.json` response snapshot, excludes sidecar files, recomputes SHA-256 from exact bytes, checks any matching `<snapshot-stem>.manifest.json`, rejects hash mismatches and conflicting duplicate draw IDs, validates the combined chronological dataset, and writes an output JSONL plus an output manifest containing input hashes and the output hash. Raw inputs are never modified.

A complete sidecar must identify `Sporttery public historical draw API`, use the exact HTTPS API host/path with `gameNo=85`, include a timezone-aware ISO `retrieved_at`, `http_status=200`, the matching `sha256`, and the matching `raw_file`. `--require-manifests` rejects missing or incomplete sidecars; without it, the import may proceed but is explicitly marked `candidate_unverified`. Even a complete sidecar is not a cryptographic signature or proof that the endpoint is authoritative. It does not establish the physical meaning of `lotteryUnsortDrawresult` or `lotteryEquipmentCount`.
