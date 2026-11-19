# Official vs legacy prize reconciliation

## Scope and inputs

Compare the official lossless prize rows generated from the 2026-11-18 snapshot with the legacy candidate archive.

- Official: 2,949 draws / 33,530 prize rows.
- Legacy: 2,901 draws / 33,098 prize rows.
- Legacy source status: `candidate_unverified`.

This is a comparison of source representations and accounting values. Neither dataset is assumed correct merely because it is present.

## Matching contract

1. Primary partition key: draw ID.
2. Within each draw, compare rows as a **multiset**, preserving duplicate occurrences rather than converting them to sets.
3. Value comparison tuple: original tier label, unit amount, winner count, aggregate total, and condition.
4. Official formatted money strings are parsed as decimal values after removing grouping commas. No floating-point arithmetic is used.
5. Official source identity fields (including `awardType`, `group`, `prizeLevelNo`, `relatedPrizeLevelNo`, and `sort`) remain attached to the official row for investigation.
6. The legacy transformation dropped these source identity fields. Therefore even a complete value match is reported as `value_match_without_source_identity`, **not** as an exact source identity match.

## Per-draw statuses

- `value_match_without_source_identity`: all row values match as multisets, but source identity cannot be proven from legacy.
- `same_label_different_values`: both sides have unmatched rows and at least one label appears on both sides.
- `source_rows_differ`: both sides have unmatched rows but no shared label explains the difference.
- `source_row_present_only_official`: only official rows remain unmatched for this draw.
- `source_row_present_only_legacy`: only legacy rows remain unmatched for this draw.

Draws existing on only one side are counted separately as official-only or legacy-only draws. Row-level totals are also reported.

## Important interpretation limits

- A repeated raw prize fingerprint across draws is not a duplicate row; source occurrence identity includes draw and prize position.
- Matching labels and amounts does not restore missing legacy source identity.
- A difference is not automatically evidence of a source error, manipulation, or a ruleset change.
- Promotions, additional prizes, side games, and rule-era transitions require targeted source review; this script does not silently classify or repair them.
- Null amounts remain null. They are not converted to zero.
- The script compares reported values; it does not infer payout rules from `amount × count`.

## Acceptance policy

No automatic data repair or row deletion is performed. The reconciliation output is diagnostic evidence only.

Only rows with adequate source identity and separately reviewed rule semantics may be promoted into a validated accounting dataset. Since the legacy archive has lost source identity, a value match alone is insufficient for that promotion.
