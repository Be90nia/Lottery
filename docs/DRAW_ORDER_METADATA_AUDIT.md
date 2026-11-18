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

All 2,341 non-null front/back order pairs are structurally valid permutations of the selected numbers. In addition, seven exact row-level matches to official provincial announcements now validate the published order/equipment semantics for those specific records; the other 2,334 rows still lack direct official crosswalks.

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
2. Official provincial announcements explicitly label the corresponding values “本期出球顺序”; seven exact crosswalks confirm the legacy arrays match this published sequence for those rows. The precise operational timing semantics (e.g. whether the published sequence is exactly the mechanical extraction sequence) still require a technical description.
3. Six exact official row crosswalks confirm that equipment codes 1, 2, and 3 correspond to “第1/2/3套摇奖球” for those records. Treat this as a numbered draw-ball set, not as a machine identifier. The remaining historical rows still require row-level reconciliation.
4. A permutation check cannot detect a consistently reordered, sorted, display-derived, or otherwise semantically misinterpreted sequence.

### Original project API lineage

The upstream project is `rbk64513-debug/dlt-analysis`. Its `vite.config.ts` at source revision `af6e5f656ed9ef80ce8a9f6afc3e97f07656a728` defines the official Sporttery history endpoint:

`https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry?gameNo=85&provinceId=0&pageSize=100&isVerify=1&termLimits=0&pageNo=`

Its `fetchPage` function retrieves the raw `value.list` records, and `cleanRec` reads:
- `lotteryDrawResult` for the selected-number set;
- `lotteryUnsortDrawresult` for the seven-value order array (only when exactly seven values are present);
- `lotteryEquipmentCount` for the numeric equipment code (falling back to zero).

Source code: https://github.com/rbk64513-debug/dlt-analysis/blob/af6e5f656ed9ef80ce8a9f6afc3e97f07656a728/vite.config.ts

This materially improves source lineage: the legacy order/equipment values were derived from fields returned by the official Sporttery history API, rather than invented by the local analysis code. It still does not provide the original per-page response bodies, retrieval timestamps, response hashes, or a row-to-response manifest. The 16 official provincial-announcement crosswalks independently confirm the transformed values for those specific draws; they do not certify every row in the 2,341-record candidate.

## Research decision

**Do not yet run confirmatory position-by-number or equipment-stratified tests across the full legacy dataset.** Seven exact crosswalks establish the published field meanings for those records, but they are not a substitute for validating the remaining 2,334 rows or defining a representative eligible period.

Before full-history inference:

1. Continue obtaining authorized official announcement/raw-response evidence across the remaining historical eras, with special attention to the 2011–2016 onset/coverage boundary.
2. Reconcile each candidate row to a direct official record where available, recording draw ID, official URL, retrieved timestamp, raw-page/snapshot hash when bytes can be archived, parser version, and exact order/equipment values. Mark rows without direct evidence as unverified rather than silently inheriting trust from the seven samples.
3. Confirm the precise operational timing semantics of “本期出球顺序” and the ball-set code mapping from authoritative technical documentation if available.
4. Define the eligible period and missingness mechanism before testing. Do not impute missing order or equipment values.
5. Predeclare the position-by-number test family, legal without-replacement null, Holm correction, and later untouched confirmation period.

## Reproducibility

The structural counts above were recomputed from the committed candidate JSONL blob. The source transformation was inspected at the upstream `scripts/clean_dlt.py` revision available on 2026-11-18. Neither source inspection establishes official authenticity of the legacy raw data.


### Stratified random audit sample

A second sample was selected independently of the convenience crosswalks to reduce selection bias. From the original candidate blob `bde880c7272f70b4e558ee01b58c63c1e65e632c`, one order-bearing row with a nonzero equipment code was selected per year (2011–2026), excluding the original 16 convenience crosswalks. Selection used sorted draw IDs, xorshift32, and seed `20261118`.

| Year | Selected draw | Official DLT page located in this pass? | Result |
|---|---:|---|---|
| 2011 | 11038 | No | No DLT order page located; search results were not a matching DLT announcement |
| 2012 | 12120 | No | No official DLT announcement URL located |
| 2013 | 13071 | No | Search result was a 排列5 announcement, not DLT |
| 2014 | 14128 | No | No official DLT announcement URL located |
| 2015 | 15138 | No | No official DLT announcement URL located |
| 2016 | 16029 | No | No official DLT announcement URL located |
| 2017 | 17153 | Yes | Exact match |
| 2018 | 18070 | No | No official DLT announcement URL located |
| 2019 | 19011 | No | No official DLT announcement URL located |
| 2020 | 20075 | Yes | Exact match |
| 2021 | 21010 | Yes | Exact match |
| 2022 | 22034 | Yes | Exact match |
| 2023 | 23048 | No | Search result was a 7星彩 announcement, not DLT |
| 2024 | 24093 | Yes | Exact match |
| 2025 | 25006 | No | No official DLT announcement URL located |
| 2026 | 26025 | No | No official DLT announcement URL located |

All five official pages located for this random sample matched the candidate exactly on date, selected numbers, draw order, and equipment set. The other eleven are **unverified due to source discovery/availability**, not mismatches. Because official-page availability is incomplete and may be non-random, 5/5 matches among located pages cannot be used as an unbiased estimate of the full-dataset error rate. The random selection recipe and IDs are stored in the machine-readable registry's `source_selection` block.

### Machine-readable crosswalk registry

The thirteen manually transcribed official-page crosswalks are recorded in `data/metadata_verification/official_order_crosswalks_20261118.json`. Run:

```bash
python scripts/verify_official_order_crosswalks.py \
  --candidate data/candidates/legacy_draws.jsonl \
  --crosswalks data/metadata_verification/official_order_crosswalks_20261118.json
```

The verifier compares draw ID, date, sorted numbers, front/back order, and equipment-set code. CI runs the same check. This makes the transcription and legacy-row match reproducible, but it does not cryptographically authenticate the linked web pages: raw HTML/HTTP bytes are not archived in the registry, and the sample remains purposive rather than representative.

## Ingestion hardening follow-up (2026-11-18)

The live-source parser now retains the upstream `lotteryUnsortDrawresult` value and `lotteryEquipmentCount` value in separately named source fields in the parsed JSONL output. These fields are preserved as source metadata and are not normalized into verified equipment/ball-set identities. The exact response bytes and SHA-256 snapshots remain the authoritative evidence.

The parser rejects a non-string, non-null `lotteryUnsortDrawresult` rather than coercing it silently. Duplicate draw IDs repeated across pages must now agree not only on draw date, selected numbers, and parsed order, but also on the retained source order string and equipment metadata. Conflicting source metadata therefore fails ingestion instead of being silently discarded.

Unit tests cover source metadata retention, malformed order-field types, and conflicting equipment metadata on duplicate records. These tests validate parser behavior only; they do not replace a successful authorized live-source capture or row-level historical reconciliation.


## Official regional-source cross-check (2026-11-18)

A targeted search found a useful primary-source cross-check on the official Chongqing Sports Lottery Center website. The site's institutional page identifies the publisher as the Chongqing Sports Lottery Management Center, a public institution under the Chongqing Municipal Sports Bureau, and identifies `www.cqtcw.net` as its official website:
- https://www.cqtcw.net/h5/aritcle/1343894432881582080/h5/content_1343894432881582080.html

### Exact row-level matches: 2017 and 2026

The official Jiangsu, Guangdong, and Chongqing provincial Sports Lottery Center announcements explicitly publish “本期出球顺序” and “本期使用第N套摇奖球”. The official-site identity is visible in the site footers; the Jiangsu announcement footer states “江苏省体育彩票管理中心版权所有”, while the Chongqing institutional page identifies the Chongqing Sports Lottery Management Center as a public institution under the Chongqing Municipal Sports Bureau.

Twenty-one records were cross-checked against the repository's legacy candidate blob. In every case, the sorted numbers, front/back order arrays, and equipment code match the official announcement exactly:

| Draw | Official date | Official front draw order | Official back draw order | Ball set | Legacy row |
|---|---|---|---|---:|---|
| 17045 | 2017-04-22 | 21, 08, 35, 01, 11 | 09, 12 | 2 | Exact match |
| 17052 | 2017-05-08 | 24, 28, 33, 19, 03 | 12, 04 | 3 | Exact match |
| 17061 | 2017-05-29 | 23, 10, 25, 19, 30 | 04, 02 | 1 | Exact match |
| 17062 | 2017-05-31 | 06, 08, 01, 28, 04 | 12, 08 | 2 | Exact match |
| 17063 | 2017-06-03 | 29, 21, 18, 22, 24 | 05, 11 | 2 | Exact match |
| 17145 | 2017-12-11 | 04, 18, 19, 17, 07 | 10, 03 | 2 | Exact match |
| 17153 | 2017-12-30 | 01, 26, 24, 09, 34 | 09, 12 | 1 | Exact match |
| 18001 | 2018-01-01 | 13, 35, 01, 25, 22 | 03, 04 | 1 | Exact match |
| 19001 | 2019-01-02 | 28, 23, 26, 06, 18 | 03, 12 | 1 | Exact match |
| 20001 | 2020-01-01 | 26, 34, 17, 32, 25 | 04, 07 | 1 | Exact match |
| 20075 | 2020-08-12 | 21, 10, 35, 02, 09 | 07, 01 | 2 | Exact match |
| 21010 | 2021-01-23 | 01, 34, 22, 05, 16 | 08, 11 | 3 | Exact match |
| 22001 | 2022-01-01 | 19, 29, 08, 11, 22 | 03, 11 | 3 | Exact match |
| 22034 | 2022-03-30 | 02, 24, 28, 27, 10 | 07, 06 | 1 | Exact match |
| 23001 | 2023-01-02 | 19, 27, 18, 24, 34 | 12, 11 | 3 | Exact match |
| 24001 | 2024-01-01 | 17, 03, 09, 35, 26 | 07, 02 | 3 | Exact match |
| 24093 | 2024-08-12 | 16, 29, 28, 26, 24 | 08, 12 | 3 | Exact match |
| 25001 | 2025-01-01 | 16, 17, 27, 08, 05 | 07, 04 | 2 | Exact match |
| 25100 | 2025-09-01 | 32, 34, 26, 28, 35 | 02, 07 | 1 | Exact match |
| 25112 | 2025-09-29 | 23, 03, 21, 04, 24 | 09, 12 | 3 | Exact match |
| 26083 | 2026-07-25 | 15, 16, 23, 26, 14 | 09, 07 | 3 | Exact match |

Official announcements:
- 17045: https://www.js-lottery.com/cms/post-77220.html
- 17052: https://www.js-lottery.com/cms/post-77436.html
- 17061: https://www.js-lottery.com/cms/post-77749.html
- 17062: https://www.js-lottery.com/cms/post-77775.html
- 17063: https://www.js-lottery.com/cms/post-77825.html
- 17145: https://www.js-lottery.com/cms/post-80978.html
- 17153: https://www.js-lottery.com/cms/post-81240.html
- 18001: https://www.js-lottery.com/cms/post-81256.html
- 19001: https://www.js-lottery.com/cms/post-86432.html
- 20001: https://www.js-lottery.com/cms/post-89613.html
- 20075: https://www.js-lottery.com/cms/post-91093.html
- 21010: https://www.js-lottery.com/cms/post-92380.html
- 22001: https://www.js-lottery.com/cms/post-133442.html
- 22034: https://www.js-lottery.com/cms/post-134150.html
- 23001: https://www.js-lottery.com/cms/post-137213.html
- 24001: https://api.js-lottery.com/cms/post-140462.html
- 24093: https://api.js-lottery.com/cms/post-142296.html
- 25001: https://api.js-lottery.com/cms/post-143433.html
- 25100: https://www.gdlottery.cn/f_html/kjgg_pdf_bak/P085_25100.pdf
- 25112: https://www.gdlottery.cn/f_html/kjgg_pdf_bak/P085_25112.pdf
- 26083: https://www.cqtcw.net/h5/aritcle/1534974555978928128/h5/content_1534974555978928128.html

For example, draw 17045's official result is `01 08 11 21 35 / 09 12`, its published draw order is `21 08 35 01 11 / 09 12`, and it used ball set 2. The candidate row has `front_draw_order=[21,8,35,1,11]`, `back_draw_order=[9,12]`, and `equipment_code_legacy=2`. The same exact correspondence holds for the other four rows.

This is now more than a structural plausibility check: it is twenty-one direct row-level crosswalks spanning 2017–2026 (including official Jiangsu, Guangdong, and Chongqing sources), and covering equipment codes 1, 2, and 3. It supports interpreting the order arrays as the official published draw-order sequence and the equipment code as the numbered draw-ball set for these records. However, this is a purposive/convenience sample assembled from searchable official announcements and adjacent issue links, not a random or representative sample; it cannot estimate the error rate of the remaining rows. It still does not prove that all 2,341 legacy rows were faithfully copied, nor does it define every operational detail of the physical extraction sequence.

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
