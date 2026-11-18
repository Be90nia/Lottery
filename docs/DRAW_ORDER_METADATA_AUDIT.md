# Draw-order and equipment metadata audit

Audit date: 2026-11-18

## Scope

This audit inspects the checked-in `data/candidates/legacy_draws.jsonl` and the original cleaning script from the source repository. The dataset remains `candidate_unverified`; this is a provenance/coverage audit, not a statistical test of lottery fairness or predictability.

## Findings

The candidate contains 2,901 draws (07001–26083). Its structural counts are:

| Field | Present | Missing | Interpretation |
|---|---:|---:|---|
| `front_draw_order` | 2,341 | 560 | Imported from legacy `order[:5]` |
| `back_draw_order` | 2,341 | 560 | Imported from legacy `order[5:]` |
| legacy equipment code | 2,336 nonzero | 565 zero/unknown | Imported from `lotteryEquipmentCount` |

All 2,341 non-null front/back order pairs are structurally valid permutations of the selected numbers. This only proves internal consistency, not that the upstream field's semantics or values are authentic.

### Calendar coverage of order metadata

| Year | Draws | Order present |
|---|---:|---:|
| 2007 | 93 | 0 |
| 2008 | 154 | 0 |
| 2009 | 153 | 0 |
| 2010 | 153 | 0 |
| 2011 | 154 | 149 |
| 2012 | 154 | 153 |
| 2013 | 153 | 153 |
| 2014 | 154 | 154 |
| 2015 | 153 | 153 |
| 2016 | 154 | 153 |
| 2017 | 153 | 153 |
| 2018 | 154 | 154 |
| 2019 | 150 | 150 |
| 2020 | 134 | 134 |
| 2021 | 150 | 150 |
| 2022 | 150 | 150 |
| 2023 | 150 | 150 |
| 2024 | 152 | 152 |
| 2025 | 150 | 150 |
| 2026 (through 26083) | 83 | 83 |

Order metadata is entirely absent for 2007–2010 and nearly complete from 2011 onward. Any position analysis on this candidate would therefore have a strong era-coverage boundary and cannot be generalized to the full historical period without careful qualification.

## Upstream transformation evidence

The source repository's `scripts/clean_dlt.py` reads `data/dlt_history_raw.json` and sets:

- `order` from `lotteryUnsortDrawresult` when that field splits into seven values;
- `equip` from `lotteryEquipmentCount` (falling back to zero).

It then writes these into `dlt_clean.json`. The current imported JSONL retains only the derived values and assigns every row the same provenance identifier, `legacy-clean-blob:bde880c7272f70b4e558ee01b58c63c1e65e632c`.

The raw `dlt_history_raw.json` file and its per-record source evidence are not present in this repository. Consequently:

1. We can trace the transformation logic, but cannot independently compare each order/equipment value with the raw source payload.
2. The name `lotteryUnsortDrawresult` and the legacy comment “出球顺序” suggest an unsorted/draw-order field, but this audit does not treat that naming/comment as authoritative proof of the physical extraction sequence.
3. `lotteryEquipmentCount` is a source field whose exact semantics and code-to-equipment mapping still require official documentation or raw source corroboration. Do not relabel it as a verified machine identifier or ball-set identifier.
4. A permutation check cannot detect a consistently reordered, sorted, display-derived, or otherwise semantically misinterpreted sequence.

## Research decision

**Do not yet run confirmatory “fifth ball” tests, interpret number 19 at position five, or stratify by equipment code.** The available evidence is adequate to define a targeted verification task, not to support a claim of positional bias.

Before inferential analysis:

1. Obtain an authorized copy of the original raw response records or immutable official API snapshots for a sample spanning the full period, including representative records with and without order metadata.
2. Confirm the official meanings and ordering semantics of `lotteryUnsortDrawresult` and `lotteryEquipmentCount`; establish whether the five front values are emitted sequentially and whether zone boundaries are unambiguous.
3. Reconcile raw values to the imported candidate row-by-row, recording source URL, retrieval timestamp, response hash, parser version, and draw ID.
4. Define the eligible period and missingness mechanism before testing. Do not impute missing order or equipment values.
5. Predeclare the position-by-number test family and use a legal without-replacement null plus Holm correction. Reserve a later untouched period for independent confirmation.

## Reproducibility

The structural counts above were recomputed from the committed candidate JSONL blob. The source transformation was inspected at the upstream `scripts/clean_dlt.py` revision available on 2026-11-18. Neither source inspection establishes official authenticity of the legacy raw data.


## Ingestion hardening follow-up (2026-11-18)

The live-source parser now retains the upstream `lotteryUnsortDrawresult` value and `lotteryEquipmentCount` value in separately named source fields in the parsed JSONL output. These fields are preserved as source metadata and are not normalized into verified equipment/ball-set identities. The exact response bytes and SHA-256 snapshots remain the authoritative evidence.

The parser rejects a non-string, non-null `lotteryUnsortDrawresult` rather than coercing it silently. Duplicate draw IDs repeated across pages must now agree not only on draw date, selected numbers, and parsed order, but also on the retained source order string and equipment metadata. Conflicting source metadata therefore fails ingestion instead of being silently discarded.

Unit tests cover source metadata retention, malformed order-field types, and conflicting equipment metadata on duplicate records. These tests validate parser behavior only; they do not replace a successful authorized live-source capture or row-level historical reconciliation.


## Official regional-source cross-check (2026-11-18)

A targeted search found a useful primary-source cross-check on the official Chongqing Sports Lottery Center website. The site's institutional page identifies the publisher as the Chongqing Sports Lottery Management Center, a public institution under the Chongqing Municipal Sports Bureau, and identifies `www.cqtcw.net` as its official website:
- https://www.cqtcw.net/h5/aritcle/1343894432881582080/h5/content_1343894432881582080.html

### Exact row-level matches: 2017 and 2026

The official Jiangsu Sports Lottery Center and Chongqing Sports Lottery Center announcements explicitly publish “本期出球顺序” and “本期使用第N套摇奖球”. The official-site identity is visible in the site footers; the Jiangsu announcement footer states “江苏省体育彩票管理中心版权所有”, while the Chongqing institutional page identifies the Chongqing Sports Lottery Management Center as a public institution under the Chongqing Municipal Sports Bureau.

Six records were cross-checked against the repository's legacy candidate blob. In every case, the sorted numbers, front/back order arrays, and equipment code match the official announcement exactly:

| Draw | Official date | Official front draw order | Official back draw order | Ball set | Legacy row |
|---|---|---|---|---:|---|
| 17045 | 2017-04-22 | 21, 08, 35, 01, 11 | 09, 12 | 2 | Exact match |
| 17052 | 2017-05-08 | 24, 28, 33, 19, 03 | 12, 04 | 3 | Exact match |
| 17062 | 2017-05-31 | 06, 08, 01, 28, 04 | 12, 08 | 2 | Exact match |
| 17145 | 2017-12-11 | 04, 18, 19, 17, 07 | 10, 03 | 2 | Exact match |
| 20001 | 2020-01-01 | 26, 34, 17, 32, 25 | 04, 07 | 1 | Exact match |
| 26083 | 2026-07-25 | 15, 16, 23, 26, 14 | 09, 07 | 3 | Exact match |

Official announcements:
- 17045: https://www.js-lottery.com/cms/post-77220.html
- 17052: https://www.js-lottery.com/cms/post-77436.html
- 17062: https://www.js-lottery.com/cms/post-77775.html
- 17145: https://www.js-lottery.com/cms/post-80978.html
- 20001: https://www.js-lottery.com/cms/post-89613.html
- 26083: https://www.cqtcw.net/h5/aritcle/1534974555978928128/h5/content_1534974555978928128.html

For example, draw 17045's official result is `01 08 11 21 35 / 09 12`, its published draw order is `21 08 35 01 11 / 09 12`, and it used ball set 2. The candidate row has `front_draw_order=[21,8,35,1,11]`, `back_draw_order=[9,12]`, and `equipment_code_legacy=2`. The same exact correspondence holds for the other four rows.

This is now more than a structural plausibility check: it is six direct row-level crosswalks spanning 2017, 2020, and 2026, and covering equipment codes 1, 2, and 3. It supports interpreting the order arrays as the official published draw-order sequence and the equipment code as the numbered draw-ball set for these records. It still does not prove that all 2,341 legacy rows were faithfully copied, nor does it define every operational detail of the physical extraction sequence.

### Independent recent examples

The official Chongqing center's announcements also expose the same concepts for recent draws:
- Draw 26131 (2026-11-16): published order `18 11 29 02 19 / 07 04`, sorted result `02 11 18 19 29 / 04 07`, and underlying `lotteryEquipmentCount=2`. The human-readable announcement labels the order “本期出球顺序” and the ball set “第2套摇奖球”: https://www.cqtcw.net/web/aritcle/1572008367349690368/web/content_1572008367349690368.htm
- Draw 26130 (2026-11-14): published order `27 29 11 07 01 / 06 02`, ball set “第1套摇奖球”: https://www.cqtcw.net/web/aritcle/1571283591360118784/web/content_1571283591360118784.htm
- Draw 26129 (2026-11-11): published order `02 12 14 33 17 / 08 07`, ball set “第2套摇奖球”: https://www.cqtcw.net/web/aritcle/1570814930926972928/web/content_1570814930926972928.htm

These examples establish that the regional center publicly labels the ordered values as draw order and the equipment field in terms of a numbered set of draw balls. They do not establish the physical timing convention (e.g. whether each listed value is the exact mechanical extraction instant sequence or a post-draw presentation sequence), nor do they establish that the historical legacy values for all 2,341 rows were copied faithfully.

### Revised LOT-044 decision

The earlier blanket statement that there was no official evidence for the field semantics is now too strong. The evidence supports a **partial semantic validation**:
1. For 26083, legacy order arrays and equipment code exactly match the official announcement's draw-order and ball-set fields.
2. For recent official announcements, the labels “本期出球顺序” and “本期使用第N套摇奖球” explicitly identify the intended published meanings.
3. The 2026-11-18 archived API snapshot still has blank order strings and zero equipment values; this is a source-endpoint coverage limitation, not evidence that the provincial announcement fields are invalid.
4. LOT-044 remains open for historical row-level reconciliation across the 2,341 legacy records, especially the 2011–2025 period, and for establishing the precise physical/operational meaning of “出球顺序” with an authoritative technical description.
5. Until those checks are complete, do not run confirmatory position/equipment inference across the full historical candidate. A future analysis may use only rows with a directly preserved official source record and a documented eligibility rule.
