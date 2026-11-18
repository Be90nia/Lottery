# Versioned Super Lotto prize rules

**Important:** This module versions the prize-tier match patterns and published
fixed-prize schedules. It is not a complete prize calculator. Floating awards,
pool carry-over, risk-control adjustments, sales totals, winner counts, and
promotion overlays require draw-specific official data and separate logic.

## Effective boundary

The official China Sports Lottery announcement states that the revised rules
began with draw **26014 on 2026-02-02**. The repository therefore selects:

- `dlt_pre_26014` for draws through 26013;
- `dlt_2026_from_26014` beginning with draw 26014.

The older official rules page describes nine prize tiers. The 2026 official
rules PDF describes seven tiers. The announcement confirms the 26014 effective
draw boundary.

Sources:
- [Official announcement: revised rules implemented from draw 26014](https://www.sporttery.cn/digitallottery/cjdlt/20260205/10052315.html)
- [Official 2026 Super Lotto rules PDF](https://static.sporttery.cn/res_1_0/cmsv2/upload/docfile/202601/1511220935li.pdf)
- [Official legacy rules page](https://m.sporttery.cn/bzzx/20210207/3002858.html?gid=5)

## Prize match patterns

| Tier | Legacy rules through 26013 | 2026 rules from 26014 |
|---|---|---|
| 1 | 5+2 | 5+2 |
| 2 | 5+1 | 5+1 |
| 3 | 5+0 | 5+0 or 4+2 |
| 4 | 4+2 | 4+1 |
| 5 | 4+1 | 4+0 or 3+2 |
| 6 | 3+2 | 3+1 or 2+2 |
| 7 | 4+0 | 3+0 or 2+1 or 1+2 or 0+2 |
| 8 | 3+1 or 2+2 | — |
| 9 | 3+0 or 1+2 or 2+1 or 0+2 | — |

Here `a+b` means the number of matched front-zone numbers plus matched
back-zone numbers. The tier classifier returns the single highest applicable
tier according to the published mutually exclusive patterns.

## Fixed prizes

All amounts below are yuan per basic winning bet, before any independent
promotion overlay.

| Tier | Legacy fixed amount | 2026 jackpot below ¥800m | 2026 jackpot at/above ¥800m |
|---|---:|---:|---:|
| 1 | Floating | Floating | Floating |
| 2 | Floating | Floating | Floating |
| 3 | 10,000 | 5,000 | 6,666 |
| 4 | 3,000 | 300 | 380 |
| 5 | 300 | 150 | 200 |
| 6 | 200 | 15 | 18 |
| 7 | 100 | 5 | 7 |
| 8 | 15 | — | — |
| 9 | 5 | — | — |

The 2026 rules set a ¥800 million jackpot threshold for fixed-prize upgrades.
For first and second prizes, the module records the published ¥5 million
per-ticket cap and ¥100 million per-tier single-draw total cap. The additional
bet multiplier for floating tiers 1 and 2 is 0.8. The module deliberately
returns `None` for floating prize amounts instead of inventing a value.

## Promotions are separate

Promotional campaigns are not part of the base ruleset. For example, the
official 2026 campaign began with draw 26050 (2026-05-09), ran for an expected
15 draws, and applied separate extra-award conditions. It must be represented
as a separately sourced promotion overlay, not folded into the base fixed
prize table:
[official 2026 promotion announcement](https://www.sporttery.cn/jczx/ggtz/20260428/10053458.html).

## API

```python
from lottery.rules import ruleset_for_draw

rules = ruleset_for_draw("26014")
tier = rules.tier_for_hits(front_hits=4, back_hits=2)  # 3
fixed = rules.fixed_prize_yuan(3, jackpot_yuan="800000000")  # Decimal("6666")
```

## Limitations and data policy

- The legacy ruleset is identified as the pre-26014 version; this module does
  not claim a verified first-ever effective date for the legacy rule.
- Rule version selection is based on draw ID, not a guessed publication date.
- Do not assign a ruleset to a historical prize row if its draw identifier is
  missing or unresolved.
- Do not recalculate or overwrite original source prize labels or amounts.
- This module does not implement floating prize distribution, minimum award
  rules, total-payout risk control, tax, or promotion eligibility.
- Historical prize rows in the candidate dataset retain their own provenance
  and require separate reconciliation before accounting conclusions.
