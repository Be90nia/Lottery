# Legacy prize-row audit

**Status:** exploratory audit of candidate data only. The rows originate from a
legacy-clean transformation and are not yet reconciled to immutable official
raw responses. This report describes field structure and candidate
inconsistencies; it does not certify historical payouts.

## Scope and method

`scripts/validate_legacy_prizes.py` reads all
`data/candidates/legacy_prizes_part_*.jsonl` files and preserves source
labels/values. It checks required fields, duplicate draw/label keys, decimal
validity, amount × winner-count consistency where that equation is meaningful,
ruleset coverage, and base/additional award pairing.

Labels are classified without rewriting them:
- `base_award`: ordinary prize tiers.
- `additional_bet`: explicit `(追加)` tiers.
- `promotion_overlay`: labels containing `派奖`.
- `side_game`: side-game labels such as `附加玩法`.
- `unknown`: anything not covered by the observed conventions.

Promotion rows are deliberately excluded from ordinary
`unit amount × winner count = total` arithmetic. The source often records a
zero unit amount while providing a positive aggregate promotion total. This
must not be interpreted as zero payout or silently imputed as a per-winner
amount.

## Candidate-data snapshot findings

The CI audit covers 33,098 prize rows across 2,901 draw IDs. All rows map to
one of the six currently implemented draw-era rulesets. The source labels
include ordinary base tiers, explicit additional-bet tiers, and promotion
overlays.

The candidate contains 1,327 promotion rows across 141 draw IDs, spanning
draw-ID prefixes 21 through 26 (2021–2026). Distribution:

| Draw prefix | Draw IDs | Promotion rows | Zero-unit-amount rows with positive total |
|---|---:|---:|---:|
| 21 | 21 | 215 | 0 |
| 22 | 29 | 283 | 0 |
| 23 | 21 | 227 | 147 |
| 24 | 33 | 311 | 0 |
| 25 | 20 | 206 | 0 |
| 26 | 17 | 85 | 0 |
| **Total** | **141** | **1,327** | **147** |

All 147 zero-unit-amount/positive-total rows occur in 21 draws with prefix 23,
and comprise seven lower-tier promotion labels per draw. The unit amount is
zero in the candidate representation while aggregate totals are positive.
The audit reports this as a distinct promotion-field pattern, not an
amount-times-count error.

The report also preserves:
- promotion row counts by original label;
- zero-unit-amount/positive-total counts by original label;
- promotion total sums and per-prefix totals;
- ruleset coverage counts;
- every additional-award mismatch and unmatched row (not only examples).

## Base/additional reconciliation

For each explicit `(追加)` row, the audit pairs the same draw and tier's base
row and selects the effective ruleset by draw ID. It checks:
- whether the ruleset permits additional awards for that tier;
- whether additional winners exceed base winners;
- whether both unit amounts are available;
- whether the additional unit amount matches the published multiplier,
  rounded down to whole yuan.

A mismatch is a candidate-data inconsistency, not proof of an official payout
error. Floating-prize amounts and rounding require source-specific scrutiny;
the current multiplier check is a screening rule, not a full official
settlement engine.

## Known early-era issue

The candidate contains `四等奖(追加)` and `五等奖(追加)` rows for draw
07001. The reconstructed 2007 launch rules allow additional betting only on
floating tiers 1–3. A contemporaneous official Jiangsu result for draw 07006
shows additional results only for tiers 1–3. Do not delete or normalize the
07001 candidate rows until their original source is recovered and reconciled.

References:
- [Contemporaneous 2007 launch-rule coverage](https://news.sohu.com/20070501/n249819058.shtml)
- [Official Jiangsu result for draw 07006](https://www.js-lottery.com/cms/post-2573.html)
- [Versioned prize rules and source-quality notes](PRIZE_RULES.md)
- [Data provenance specification](DATA_SPEC.md)

## Next gates

1. Obtain official immutable raw prize snapshots and verify each candidate
   source field's semantics.
2. Reconcile promotion campaign eligibility, tier conditions, and aggregate
   totals against the official per-draw pages/rules.
3. Resolve the 07001 extra fixed-tier rows using the original source record.
4. Only then build a complete prize calculator; floating awards, taxes,
   pool carry-over, and campaign-specific caps must remain separate modules.
