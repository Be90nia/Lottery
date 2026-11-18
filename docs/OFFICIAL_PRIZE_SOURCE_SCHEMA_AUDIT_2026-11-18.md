# Official prize source-schema audit — 2026-11-18

This audit was computed directly from the 30 immutable raw API page snapshots in the incoming archive, not inferred from the legacy cleaner.

## Coverage

- Draw records: 2,949
- Prize objects: 33,530
- Every draw has a non-empty `prizeLevelList`
- Every prize object is a JSON object

## Field availability

| Field | Observation |
|---|---|
| `awardType` | Present and non-null in all 33,530 rows |
| `group` | Present and non-null in all 33,530 rows |
| `sort` | Present and non-null in all 33,530 rows |
| `prizeLevel` | Present and non-null in all 33,530 rows |
| `stakeAmount` | Present and non-null in all 33,530 rows |
| `stakeAmountFormat` | Present and non-null in all 33,530 rows |
| `stakeCount` | Present and non-null in all 33,530 rows |
| `totalPrizeamount` | Present and non-null in all 33,530 rows |
| `lotteryCondition` | Present in all rows; value is the empty string throughout |
| `prizeLevelNo` | Absent from all 33,530 rows |
| `relatedPrizeLevelNo` | Absent from all 33,530 rows |

For this API snapshot, the usable source identity tuple is therefore based on `awardType`, `group`, `sort`, and the original label. Do not design the importer around `prizeLevelNo` or `relatedPrizeLevelNo` as if they were populated.

## Award-type distribution

| awardType | Rows |
|---|---:|
| 0 | 32,203 |
| 1 | 1,327 |

The 1,327 rows with `awardType=1` occur in 141 draws:

| Draw year prefix | Draw count | Range |
|---|---:|---|
| 21 | 21 | 21039–21059 |
| 22 | 29 | 22040–22068 |
| 23 | 21 | 23039–23059 |
| 24 | 33 | 24030–24062 |
| 25 | 20 | 25038–25057 |
| 26 | 17 | 26050–26066 |

These rows carry explicit labels such as `三等奖派奖`, `四等奖派奖`, `一等奖基本派奖`, and `二等奖追加派奖`. They must remain separate from ordinary base/additional-bet rows. `awardType=1` is a source classification; this audit does not infer ticket-level promotion eligibility.

## Per-draw prize-list length

| Prize rows per draw | Draw count |
|---:|---:|
| 11 | 2,707 |
| 9 | 101 |
| 22 | 97 |
| 18 | 23 |
| 14 | 17 |
| 15 | 3 |
| 13 | 1 |

Variable list length is expected in the source. It reflects rule-era structure and extra promotion rows; it is not a reason to pad, truncate, or deduplicate the raw list.

## Structural transition at issue 26014

The raw API representation supports the already documented 2026 ruleset boundary:

- Issues 26001–26013 have 11 prize rows each.
- Starting at issue 26014, the ordinary baseline list has 9 rows: seven prize levels plus the two first-/second-prize additional rows.
- Promotion issues 26050–26066 have 14 rows each in this snapshot, with the promotion overlay represented as additional `awardType=1` objects.
- The 48 official-only draws added beyond the legacy archive (26084–26131) each have the 9-row baseline structure.

This is a source-schema observation, consistent with the official 26014 rules transition already documented in `PRIZE_RULE_ERAS.md`. It does not replace the published rule text or establish ticket-level eligibility.

## Data handling decisions

1. Preserve every raw prize object unchanged.
2. Retain `awardType`, `group`, and `sort` in normalized rows.
3. Never use `prizeLevel` alone as a unique row key.
4. Keep `awardType=1` promotion overlays separate from ordinary additional-bet awards.
5. Do not force every draw to a fixed prize-row count.
6. Keep formatted display amounts and normalized numeric representations separate; parse amounts with decimal arithmetic and preserve original strings.

## Reproducibility

Input archive: `data/incoming/dlt_official_raw.zip`

Archive SHA-256:
`e112babccdd387aa8cf54e7bba46e4162defac8284a9f9c3acb1f51f53b55c30`

The archive and per-page sidecar manifests are the provenance inputs for this audit. Their hashes establish byte integrity, not official digital-signature authentication.
