# Versioned Super Lotto prize rules

**Important:** This registry versions published prize match patterns and fixed
prize schedules. It is not a complete prize calculator. Floating awards,
pool carry-over, risk-control adjustments, sales totals, winner counts, and
promotion overlays require draw-specific official data and separate logic.

## Evidence-backed effective boundaries

The registry currently supports three evidenced rulesets:

- `dlt_2014_from_14052`: draws 14052–19018; effective 2014-05-05.
- `dlt_2019_from_19019`: draws 19019–26013; effective from draw 19019 in February 2019.
- `dlt_2026_from_26014`: draw 26014 onward; effective 2026-02-02.

Draws before 14052 deliberately raise `UnsupportedRulesetError`. The game had
earlier rule changes (including 2009 and 2013); this repository has not yet
verified their exact effective draw boundaries and complete prize schedules.
It is safer to fail closed than apply a later rule to early historical records.

Sources:
- [2014 Ministry of Finance rule approval](https://www.mof.gov.cn/tzgg/201404/t20140421_1069584.htm)
- [2014 effective notice: draw 14052](https://yntc8.cn/news/2014042229140.html)
- [2019 rule change and effective issue 19019](https://society.yunnan.cn/system/2019/02/28/030214030.shtml)
- [2019 rule implementation summary](https://www.nmtc.com.cn/gyzl/17631.html)
- [2026 official rules PDF](https://static.sporttery.cn/res_1_0/cmsv2/upload/docfile/202601/1511220935li.pdf)
- [2026 official announcement: revised rules from draw 26014](https://www.sporttery.cn/digitallottery/cjdlt/20260205/10052315.html)

## Prize match patterns

Here `a+b` means matched front-zone numbers plus matched back-zone numbers.

| Tier | 2014 rules (14052–19018) | 2019 rules (19019–26013) | 2026 rules (26014 onward) |
|---|---|---|---|
| 1 | 5+2 | 5+2 | 5+2 |
| 2 | 5+1 | 5+1 | 5+1 |
| 3 | 5+0 or 4+2 | 5+0 | 5+0 or 4+2 |
| 4 | 4+1 or 3+2 | 4+2 | 4+1 |
| 5 | 4+0 or 3+1 or 2+2 | 4+1 | 4+0 or 3+2 |
| 6 | 3+0 or 1+2 or 2+1 or 0+2 | 3+2 | 3+1 or 2+2 |
| 7 | — | 4+0 | 3+0 or 2+1 or 1+2 or 0+2 |
| 8 | — | 3+1 or 2+2 | — |
| 9 | — | 3+0 or 1+2 or 2+1 or 0+2 | — |

## Fixed prizes and additional betting

All fixed amounts are yuan per basic winning bet, before any independent
promotion overlay.

| Tier | 2014 fixed amount | 2019 fixed amount | 2026 below ¥800m | 2026 at/above ¥800m |
|---|---:|---:|---:|---:|
| 1 | Floating | Floating | Floating | Floating |
| 2 | Floating | Floating | Floating | Floating |
| 3 | Floating | 10,000 | 5,000 | 6,666 |
| 4 | 200 | 3,000 | 300 | 380 |
| 5 | 10 | 300 | 150 | 200 |
| 6 | 5 | 200 | 15 | 18 |
| 7 | — | 100 | 5 | 7 |
| 8 | — | 15 | — | — |
| 9 | — | 5 | — | — |

Additional award multipliers:
- 2014 rules: floating tiers 1–3 receive 60% of the corresponding basic-bet
  prize; fixed tiers 4–5 receive 50%; tier 6 has no additional award.
- 2019 rules: additional betting participates only in floating tiers 1–2,
  with an 80% multiplier.
- 2026 rules: additional betting participates only in floating tiers 1–2,
  with an 80% multiplier.

The 2026 rules set a ¥800 million jackpot threshold for fixed-prize upgrades.
For first and second prizes, the module records the published ¥5 million
per-ticket cap and ¥100 million per-tier single-draw total cap. The module
deliberately returns `None` for floating prize amounts instead of inventing
a value.

## Promotions and operational changes are separate

Promotional campaigns are not part of the base ruleset. For example, the
official 2023 campaign was a separate limited-time overlay; the 2026 campaign
also had independent eligibility and bonus conditions. Record these with
separate effective periods and sources.

The 2023 change to sales cutoff and broadcast time is operational metadata,
not a prize-rule version. It must not be treated as a new prize tier or payout
schedule.

## API

```python
from lottery.rules import ruleset_for_draw

rules = ruleset_for_draw("26014")
tier = rules.tier_for_hits(front_hits=4, back_hits=2)  # 3
fixed = rules.fixed_prize_yuan(3, jackpot_yuan="800000000")
```

For draw IDs before 14052, `ruleset_for_draw` raises
`UnsupportedRulesetError` until the 2007–2014 historical rules are
independently verified. Do not catch this exception and silently substitute
the 2014 rules.

## Limitations and data policy

- Ruleset selection is by draw ID, not guessed publication date.
- Do not assign a ruleset to a historical prize row if its draw identifier is
  missing or unresolved.
- Do not recalculate or overwrite original source prize labels or amounts.
- Floating award formulas, minimum award rules, total-payout risk control,
  tax, and promotion eligibility are not calculated by this registry.
- The 2007–2014 rules remain an explicit gap; candidate prize rows in that
  period must not be normalized with the 2014, 2019, or 2026 schedules.

## Why the pre-2014 range is blocked

The checked-in candidate prize file includes a 07001 row labelled
`三等奖` with a per-bet amount of ¥24,466 and a separate
`三等奖(追加)` row at ¥14,679. This candidate-only observation is not proof
of the official 2007 rules, but it is inconsistent with blindly applying the
2019 fixed ¥10,000 third-tier schedule and 80% additional multiplier. It is a
concrete reason to keep 07001 and other pre-14052 draws unsupported until
official historical rules and effective boundaries are recovered.

Source file: `data/candidates/legacy_prizes_part_01.jsonl`; source provenance
is the legacy-clean transformation and remains unverified.
