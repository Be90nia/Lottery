# Versioned Super Lotto prize rules

**Important:** This registry versions published prize match patterns, fixed
prize schedules, and additional-bet multipliers. It is not a complete prize
calculator. Floating awards, pool carry-over, risk-control adjustments, sales
totals, winner counts, and promotion overlays require draw-specific official
data and separate logic.

## Evidence-backed effective boundaries

The registry currently supports five rulesets:

- `dlt_2009_from_09121`: draws 09121–13144; new rules started with draw 09121
  (sales opened 2009-10-14; draw held 2009-10-17).
- `dlt_2013_from_13145`: draws 13145–14051; funding composition changed from
  draw 13145 (reported sales start 2013-12-09).
- `dlt_2014_from_14052`: draws 14052–19018; effective 2014-05-05.
- `dlt_2019_from_19019`: draws 19019–26013; effective from draw 19019 in
  February 2019.
- `dlt_2026_from_26014`: draw 26014 onward; effective 2026-02-02.

Draws before 09121 deliberately raise `UnsupportedRulesetError`. The
pre-2009 prize rules are not yet independently verified, so the registry does
not guess a schedule for 2007–09120.

Sources:
- [2009 Ministry of Finance approval (财办综〔2009〕68号)](https://zhs.mof.gov.cn/zhengcefabu/201811/t20181122_3073538.htm)
- [Contemporaneous 2009 draw 09121 result and tier schedule](https://www.js-lottery.com/cms/post-2935.html)
- [2013 Ministry of Finance funding-ratio approval and attached rules](https://zhs.mof.gov.cn/zhengcefabu/201312/t20131219_1026921.htm)
- [2013 reported effective boundary: draw 13145](https://sports.sina.com.cn/l/2026-01-30/doc-inhkacxm7033487.shtml)
- [2014 Ministry of Finance rule approval](https://www.mof.gov.cn/tzgg/201404/t20140421_1069584.htm)
- [2014 effective notice: draw 14052](https://yntc8.cn/news/2014042229140.html)
- [2019 rule change and effective issue 19019](https://society.yunnan.cn/system/2019/02/28/030214030.shtml)
- [2019 rule implementation summary](https://www.nmtc.com.cn/gyzl/17631.html)
- [2026 official rules PDF](https://static.sporttery.cn/res_1_0/cmsv2/upload/docfile/202601/1511220935li.pdf)
- [2026 official announcement: revised rules from draw 26014](https://www.sporttery.cn/digitallottery/cjdlt/20260205/10052315.html)

## Prize match patterns

Here `a+b` means matched front-zone numbers plus matched back-zone numbers.

| Tier | 2009/2013 (09121–14051) | 2014 (14052–19018) | 2019 (19019–26013) | 2026 (26014 onward) |
|---|---|---|---|---|
| 1 | 5+2 | 5+2 | 5+2 | 5+2 |
| 2 | 5+1 | 5+1 | 5+1 | 5+1 |
| 3 | 5+0 | 5+0 or 4+2 | 5+0 | 5+0 or 4+2 |
| 4 | 4+2 | 4+1 or 3+2 | 4+2 | 4+1 |
| 5 | 4+1 | 4+0 or 3+1 or 2+2 | 4+1 | 4+0 or 3+2 |
| 6 | 4+0 or 3+2 | 3+0 or 1+2 or 2+1 or 0+2 | 3+2 | 3+1 or 2+2 |
| 7 | 3+1 or 2+2 | — | 4+0 | 3+0 or 2+1 or 1+2 or 0+2 |
| 8 | 3+0 or 1+2 or 2+1 or 0+2 | — | 3+1 or 2+2 | — |
| 9 | — | — | 3+0 or 1+2 or 2+1 or 0+2 | — |

## Fixed prizes and additional betting

All fixed amounts are yuan per basic winning bet, before any independent
promotion overlay.

| Tier | 2009/2013 fixed | 2014 fixed | 2019 fixed | 2026 below ¥800m | 2026 at/above ¥800m |
|---|---:|---:|---:|---:|---:|
| 1 | Floating | Floating | Floating | Floating | Floating |
| 2 | Floating | Floating | Floating | Floating | Floating |
| 3 | Floating | Floating | 10,000 | 5,000 | 6,666 |
| 4 | 3,000 | 200 | 3,000 | 300 | 380 |
| 5 | 600 | 10 | 300 | 150 | 200 |
| 6 | 100 | 5 | 200 | 15 | 18 |
| 7 | 10 | — | 100 | 5 | 7 |
| 8 | 5 | — | 15 | — | — |
| 9 | — | — | 5 | — | — |

Additional award multipliers:
- 2009 and 2013 rules: floating tiers 1–3 receive 60% of the corresponding
  basic-bet prize; fixed tiers 4–7 receive 50%; tier 8 has no additional award.
- 2014 rules: floating tiers 1–3 receive 60%; fixed tiers 4–5 receive 50%;
  tier 6 has no additional award.
- 2019 rules: additional betting participates only in floating tiers 1–2,
  with an 80% multiplier.
- 2026 rules: additional betting participates only in floating tiers 1–2,
  with an 80% multiplier.

The 2013 change primarily altered funding composition (51% prize, 14% issue
expense, 35% public welfare; the prize component was divided into 49% current
prize and 2% adjustment fund). It did not create a new match-pattern tier
schedule relative to the 2009 eight-tier version.

The 2026 rules set a ¥800 million jackpot threshold for fixed-prize upgrades.
For first and second prizes, the module records the published ¥5 million
per-ticket cap and ¥100 million per-tier single-draw total cap. Floating
prize amounts are deliberately returned as `None`.

## Promotions and operational changes are separate

Promotional campaigns are not part of the base ruleset. Record them as
separately sourced overlays with their own effective periods and eligibility.
The 2023 change to sales cutoff and broadcast time is operational metadata,
not a prize-rule version.

## API

```python
from lottery.rules import ruleset_for_draw

rules = ruleset_for_draw("26014")
tier = rules.tier_for_hits(front_hits=4, back_hits=2)  # 3
fixed = rules.fixed_prize_yuan(3, jackpot_yuan="800000000")
```

For draw IDs before 09121, `ruleset_for_draw` raises
`UnsupportedRulesetError` until the pre-2009 historical rules are verified.
Do not catch this exception and silently substitute the 2009 rules.

## Limitations and data policy

- Ruleset selection is by draw ID, not guessed publication date.
- The 2013 effective draw boundary is supported by the Ministry of Finance
  approval plus a retrospective source reporting the 13145 implementation;
  retain this provenance distinction in downstream reports.
- Do not assign a ruleset to a historical prize row if its draw identifier is
  missing or unresolved.
- Do not recalculate or overwrite original source prize labels or amounts.
- Floating award formulas, minimum award rules, total-payout risk control,
  tax, and promotion eligibility are not calculated by this registry.
- The pre-09121 rules remain an explicit gap; candidate prize rows in that
  period must not be normalized with the later schedules.
