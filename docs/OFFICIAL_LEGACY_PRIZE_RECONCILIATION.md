# Official vs legacy prize reconciliation plan

## Scope

Compare the newly archived official Sporttery snapshot (2,949 draws) against the existing legacy candidate prize archive (2,901 draw IDs / 33,098 rows).

This is a comparison of **source representations and accounting consistency**, not an assumption that either side is automatically correct.

## Required matching keys

1. Primary: draw ID.
2. Within a draw: preserve source occurrence position and source identifiers such as `prizeLevelNo`, `relatedPrizeLevelNo`, `awardType`, and `sort` when present.
3. Displayed `prizeLevel` is not a unique identity by itself because promotions and additional rows can reuse tier labels.

## Comparison classes

Each comparison must end in exactly one status:

- `exact_source_match`
- `source_row_present_only_official`
- `source_row_present_only_legacy`
- `same_label_different_source_identity`
- `same_identity_different_amount`
- `same_identity_different_winner_count`
- `same_identity_different_total`
- `promotion_or_side_game_not_comparable`
- `insufficient_source_fields`

No row is silently repaired.

## Official-side invariants

For every official draw:

- raw snapshot SHA-256 matches its sidecar;
- draw ID is unique across the 30 pages;
- `prizeLevelList` exists and is non-empty;
- every prize entry is an object;
- every prize object is preserved verbatim in the raw prize dataset.

## Legacy-side constraints

The existing candidate archive is not promoted to truth. Its own audit identifies 33,098 rows across 2,901 draw IDs and notes that source identifiers were dropped by the legacy cleaner.

Therefore, a legacy row that cannot be mapped unambiguously must remain `insufficient_source_fields`, not be forced into a match.

## Known investigation targets

- Draw 07001 fixed-tier additional rows.
- Candidate anomalies around 07008, 16106, 17045, 17052, 17062, 17063.
- Promotion rows with zero unit amount and positive aggregate payout.
- 2026 promotion issues 26050–26066.
- The 26014 seven-tier ruleset transition.

These are investigation targets, not pre-declared errors.

## Acceptance rule

Only `exact_source_match` and explicitly reviewed non-comparable rows may enter a validated accounting dataset.

All other differences remain in the reconciliation report and are available for rule/source review.
