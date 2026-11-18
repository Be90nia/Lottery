# Prize row reconciliation

The candidate prize archive contains 33,098 rows across 2,901 draw IDs. The
audit preserves every original label, amount, winner count, total, and source
identifier. It does not rewrite or normalize source accounting fields.

## Award label classes

The observed 25 labels are classified without changing their original text:

- `base_award`: the ordinary tier row (一等奖 through 九等奖).
- `additional_bet`: tier labels ending in `(追加)`.
- `promotion_overlay`: labels containing `派奖`, including basic/additional
  campaign rows.
- `side_game`: labels explicitly naming 附加玩法 or 幸运彩.
- `unknown`: labels not covered by the above rules; these remain visible for
  review rather than being guessed.

## Additional-bet reconciliation

For each additional-bet row, the audit joins the same draw and prize tier's
base row, selects the effective ruleset by draw ID, and checks:

1. The ruleset authorizes an additional award for that tier.
2. Additional winners do not exceed base winners.
3. If both unit amounts are present, the additional unit amount equals
   `floor(base unit amount × published multiplier)`.

The multiplier is era-specific: 2007 floating tiers 60%; 2009/2013 floating
tiers 60% and eligible fixed tiers 50%; 2014 floating tiers 60% and eligible
fixed tiers 50%; 2019/2026 floating tiers 80%. A fixed tier with no additional
award under its effective ruleset is reported as unexpected. Missing amounts
are marked unscorable, not imputed.

## Known candidate discrepancy: draw 07001

The legacy candidate contains:
- `四等奖(追加)`: 50 winners at ¥3,000 each;
- `五等奖(追加)`: 682 winners at ¥500 each.

The contemporaneous 2007 launch-rule summary says additional betting
participates only in floating tiers. The official Jiangsu provincial result
for draw 07006 likewise lists additional results only for first, second, and
third prizes. A third-party result page for 07001 lists additional results
only for first, second, and third prizes, consistent with the launch rule.

Sources:
- [2007 launch-rule summary](https://news.sohu.com/20070501/n249819058.shtml)
- [Official Jiangsu draw 07006 result](https://www.js-lottery.com/cms/post-2573.html)
- [Third-party 07001 result detail](https://cp.china-ssq.net/dlt/info/07001)

This is a candidate-source discrepancy, not proof that the official payout was
wrong. The original primary 07001 result snapshot has not yet been archived.
The audit reports these 2007 fixed-tier additional rows as unexpected and
never deletes or repairs them automatically.

## Promotion accounting

Promotion rows are kept separate from ordinary `unit amount × winner count`
checks. In the previous audit, 147 rows had a zero unit amount and positive
total payout; their labels were campaign awards such as `三等奖派奖`.
These are reported as promotion totals, not ordinary accounting mismatches.
The audit still preserves the raw zero amount and total.

## Reproduction

```bash
python scripts/validate_legacy_prizes.py \
  --output prize-reconciliation.json
```

The report includes SHA-256 and byte size for each input file, label/ruleset
counts, all additional-award discrepancies, promotion aggregates, missing
amount counts, and ordinary amount-total inconsistencies. CI archives the
machine-readable report as a workflow artifact.

## Limitations

- The legacy prize rows are derived from an unverified legacy-clean source,
  not a complete set of immutable official response snapshots.
- A match against a published multiplier is an internal consistency check,
  not source authentication.
- Promotions, side games, and special awards may have their own eligibility
  and settlement rules; do not fold them into base prize calculations.
