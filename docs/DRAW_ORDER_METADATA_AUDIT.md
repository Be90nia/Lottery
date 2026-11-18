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
