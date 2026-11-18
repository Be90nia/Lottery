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

## Source-backed examples of candidate field errors

The following comparisons are important because they show that a percentage
mismatch can be caused by the candidate transformation rather than a changed
game rule:

- Draw 17045, fifth prize: the official Jiangsu result reports basic ¥10 and
  additional ¥5. The legacy candidate reports basic ¥100 and additional ¥5.
  The additional row agrees with the 2014 50% multiplier; the candidate basic
  unit amount does not.
  [Official Jiangsu draw 17045](https://www.js-lottery.com/cms/post-77220.html)
- Draw 17052, second prize: the official Jiangsu result reports basic ¥81,082
  and additional ¥48,649. The legacy candidate records the basic amount as
  ¥1,551,723 while retaining the correct additional amount. The recorded
  basic value matches a separate first-prize promotion amount on that result
  page, suggesting a source-field mapping error.
  [Official Jiangsu draw 17052](https://www.js-lottery.com/cms/post-77436.html)
- Draw 16106, third prize: the legacy candidate records the additional unit
  amount as ¥266, equal to the additional winner count. A contemporaneous
  detailed result page reports ¥2,131 per additional winning bet. This is a
  secondary-source cross-check, not an official immutable source snapshot.
  [Detailed 16106 result](https://news.zgzcw.com/dlt/zx_193.shtml)
- Draw 17062: the official Jiangsu result reports second prize basic/additional
  as ¥191,426/¥114,855, third prize as ¥8,612/¥5,167, fourth prize as
  ¥200/¥100, and fifth prize as ¥10/¥5. The legacy candidate instead records
  values such as second prize ¥893,219/¥714,575 and third prize
  ¥10,000/¥3,000, with winner counts that do not match the official page.
  This is a clear multi-row candidate mapping failure.
  [Official Jiangsu draw 17062](https://www.js-lottery.com/cms/post-77775.html)
- Draw 26016, first prize: the official Jiangsu result reports basic ¥5,925,957
  and additional ¥4,740,766; draw 26029 reports basic ¥7,877,022 and additional
  ¥6,301,617. Both satisfy the 80% relationship within one yuan, but the
  displayed amounts do not establish one universal rounding mode. The audit
  therefore uses a conservative ±¥2 display-rounding tolerance for floating
  tiers only, and keeps exact multiplier checks for fixed tiers.
  [Official Jiangsu draw 26016](https://www.js-lottery.com/cms/post-146412.html)
  [Official Jiangsu draw 26029](https://api.js-lottery.com/cms/post-146636.html)

The candidate also contains 734 nonzero additional rows in fixed tiers 4 and
5 during the 2007 launch-era rules, which only authorized additional betting
for floating tiers 1–3. This is exactly two rows for each of the 367 draws in
the 07001–09120 interval. These rows are quarantined as candidate-label or
mapping anomalies, not deleted or rewritten.

The latest full candidate audit (before the additional 17062 fixture-only
test was added) paired 8,905 nonzero additional-award rows. Of these, 6,037
floating pairs fell within the ±¥2 display tolerance. Fourteen candidate
mismatches remained, and 734 additional rows were outside the 2007 ruleset's
authorized tiers. The 14 remaining mismatches include material amount
differences and impossible additional-winner counts concentrated in 07008,
16106, and the 17045–17063 window. These remain quarantined; no source values
were repaired.

## Base/additional reconciliation

For each explicit `(追加)` row, the audit pairs the same draw and tier's base
row and selects the effective ruleset by draw ID. It checks:
- whether the ruleset permits additional awards for that tier;
- whether additional winners exceed base winners;
- whether both unit amounts are available;
- whether the additional unit amount matches the published multiplier,
  rounded down to whole yuan. For floating tiers, published integer amounts
  may reflect independent rounding of underlying pool calculations, so the
  audit only flags differences greater than ¥2 from the exact multiplier
  relationship. This tolerance is a conservative screening allowance, not a
  published official rounding rule.

A mismatch is a candidate-data inconsistency, not proof of an official payout
error. The current multiplier check is a screening rule, not a full official
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
