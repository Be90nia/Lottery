# Official vs legacy prize reconciliation results — 2026-11-18

## Result

The reconciliation completed successfully in GitHub Actions run [#44256874609](https://github.com/Be90nia/Lottery/actions/runs/44256874609), using the official processed prize snapshot and all nine legacy prize JSONL parts.

| Measure | Result |
|---|---:|
| Official draws | 2,949 |
| Official prize rows | 33,530 |
| Legacy candidate draws | 2,901 |
| Legacy candidate prize rows | 33,098 |
| Draws present on both sides | 2,901 |
| Official-only draws | 48 |
| Legacy-only draws | 0 |
| Exact value-matched rows within overlapping draws | 33,098 |
| Official unmatched rows within overlapping draws | 0 |
| Legacy unmatched rows within overlapping draws | 0 |
| Rows in the 48 official-only draws | 432 |

The 48 official-only draw IDs are the contiguous range `26084`–`26131`. The legacy candidate ends at `26083`.

## What “exact value match” means

For every overlapping draw, the script compared the row multisets using:

- original prize label;
- unit amount, parsed as `Decimal` after removing display grouping commas;
- winner count;
- aggregate total, parsed as `Decimal`;
- original condition.

Duplicate occurrences were counted, not collapsed. Placeholder amounts such as `---` remain missing values, not numeric zero.

All 33,098 legacy rows match one official row on this complete value tuple. No unmatched rows remain on either side within the 2,901 overlapping draws.

## What this proves — and what it does not

This is strong evidence that the legacy candidate preserved the displayed prize labels and accounting values correctly for all draws it covers, when compared with this official API snapshot.

It does **not** prove source-identity equality. The legacy cleaner dropped upstream identity fields such as `awardType`, `group`, `prizeLevelNo`, `relatedPrizeLevelNo`, and `sort`. Therefore the result status is `value_match_without_source_identity`, not `exact_source_match`.

It also does not authenticate the draw process or prove that every published prize category has the same interpretation across all historical rulesets. Promotion rows, additional awards, and the historical rule boundaries still require semantic review against the official raw objects and the versioned prize rules.

## Consequences for the project

1. Do not “repair” or discard the 33,098 legacy prize rows merely because they were previously marked candidate-unverified; their displayed values now reconcile exactly to the official snapshot for the full overlapping period.
2. Keep the official 33,530-row lossless dataset as the preferred source representation because it retains raw prize objects, source identity fields, and snapshot provenance.
3. Treat draws `26084`–`26131` as official-only coverage added beyond the legacy archive.
4. Continue ruleset/promotion classification using the official source identity fields. Do not infer those identities from labels alone.

## Reproducibility

- Official input: `data/processed/prizes-20261118.jsonl`
- Legacy inputs: `data/candidates/legacy_prizes_part_01.jsonl` through `part_09.jsonl`
- Script: `scripts/reconcile_official_legacy_prizes.py`
- Workflow run: `44256874609`
- Workflow head commit: `c6e83aa574d1f788b00694390c9d83d1a6f27726`
- Workflow artifact: `lottery-research-reports` (contains the full JSON reconciliation report)
