# Early 2007 additional-prize row audit

**Snapshot:** 2026-11-18 official API archive  
**Status:** six consecutive draws have confirmed source-structure conflicts; quarantine applies to the draw's prize rows pending adjudication.  
**Scope:** issues 07006–07011. This is a source reconciliation finding, not evidence of draw manipulation.

## Finding

For each of issues 07006–07011, the archived API contains three rows with an empty `group` field and labels `三等奖(追加)`, `四等奖(追加)`, and `五等奖(追加)`. The fourth- and fifth-prize additional rows repeat the same unit amount and winner count as the corresponding basic-prize rows in that same draw.

The contemporaneous Jiangsu Sports Lottery result pages separately list the main-game basic prize table and an additional-bet table. In all six pages, the additional-bet table lists only first, second, and third prize; it does not list fourth- or fifth-prize additional awards. This is a repeated structural discrepancy, not a one-draw anomaly.

| Draw | API 4th additional | API 4th basic | API 5th additional | API 5th basic | Official additional table |
|---|---:|---:|---:|---:|---|
| 07006 | ¥3,000 × 42 | ¥3,000 × 42 | ¥500 × 814 | ¥500 × 814 | 1st: 1; 2nd: 0; 3rd: 1 |
| 07007 | ¥3,000 × 94 | ¥3,000 × 94 | ¥500 × 993 | ¥500 × 993 | 1st: 0; 2nd: 0; 3rd: 2 |
| 07008 | ¥3,000 × 92 | ¥3,000 × 92 | ¥500 × 2,581 | ¥500 × 2,581 | 1st: 0; 2nd: 0; 3rd: 6 |
| 07009 | ¥3,000 × 39 | ¥3,000 × 39 | ¥500 × 861 | ¥500 × 861 | 1st: 0; 2nd: 2; 3rd: 4 |
| 07010 | ¥3,000 × 43 | ¥3,000 × 43 | ¥500 × 981 | ¥500 × 981 | 1st: 0; 2nd: 2; 3rd: 6 |
| 07011 | ¥3,000 × 48 | ¥3,000 × 48 | ¥500 × 750 | ¥500 × 750 | 1st: 0; 2nd: 0; 3rd: 5 |

The official third-prize additional amounts also agree with the API for 07006, 07007, 07009, 07010, and 07011. Issue 07008 is a separate direct value conflict: API ¥4,528 × 6 versus the Jiangsu announcement ¥4,582 × 6. The fourth/fifth rows are not justified by the published additional-bet tables in any of these six issues.

## Primary contemporaneous sources

All six are Jiangsu Sports Lottery result announcements:

- [Issue 07006](https://www.js-lottery.com/cms/post-2573.html), published 2007-06-11.
- [Issue 07007](https://www.js-lottery.com/cms/post-2574.html), published 2007-06-13.
- [Issue 07008](https://www.js-lottery.com/cms/post-2575.html), published 2007-06-16.
- [Issue 07009](https://www.js-lottery.com/cms/post-2576.html), published 2007-06-18.
- [Issue 07010](https://www.js-lottery.com/cms/post-2577.html), published 2007-06-20.
- [Issue 07011](https://www.js-lottery.com/cms/post-2578.html), published 2007-06-23.

The API raw rows were read from the byte-preserved 2026-11-18 archive. The source-level fields include `awardType`, `group`, `sort`, `prizeLevel`, `stakeAmount`, `stakeCount`, and `totalPrizeamount`. In these additional rows, `group` is empty and `sort` is 80/100 for fourth/fifth prize. No source fields were rewritten.

## Interpretation and handling

1. Add issues 07006–07011 to the minimum known prize-source quarantine set. Exclude their prize rows from payout calculations, prize-model targets, and prize-derived features until adjudicated.
2. Preserve all raw API rows and contemporaneous provincial announcements. Do not overwrite API values with provincial values automatically.
3. Keep draw number/date and selected-number trust separate. This prize-table conflict does not itself invalidate the draw result numbers.
4. Do not infer intent, fraud, or a manipulated draw from a data-source mapping discrepancy.
5. Issues 07001–07005 show the same three-row API shape in the raw archive, including repeated fixed fourth/fifth additional values. They remain unconfirmed leads until contemporaneous detailed result announcements are independently checked; shape similarity alone is not sufficient to quarantine them as confirmed conflicts.

## Next audit

Continue backward through 07001–07005 and forward beyond 07011 using contemporaneous detailed provincial announcements. Then inspect whether the same empty-`group` / `sort` 60/80/100 pattern persists in later rule eras. Any expansion of the quarantine list must be supported by a draw-specific source comparison.


## Additional confirmed issue 07005

A separate contemporaneous Jiangsu Sports Lottery announcement for issue 07005
shows the same discrepancy:

- API `四等奖(追加)`: ¥3,000 × 57; basic fourth prize is also ¥3,000 × 57.
- API `五等奖(追加)`: ¥500 × 1,726; basic fifth prize is also ¥500 × 1,726.
- The provincial main-game additional-bet table lists first prize 0, second
  prize 2, and third prize 24; it does not list fourth- or fifth-prize
  additional awards.

Source: [Jiangsu Sports Lottery, issue 07005](https://www.js-lottery.com/cms/post-2572.html),
published 2007-06-09. Thus the confirmed early-era sequence now begins at
07005 and runs continuously through 07011. Issues 07001–07004 remain
unconfirmed leads.
