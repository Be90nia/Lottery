# Cross-check: Sporttery API prize rows vs provincial result announcements

**Status: confirmed source conflict; affected prize rows are quarantined.**
This report compares the archived API snapshot from 2026-11-18 with
contemporaneous result announcements published by the Jiangsu Sports Lottery
administration. The provincial pages are independent published records; the
API archive is preserved byte-for-byte with page manifests.

## Why the previous reconciliation must be interpreted narrowly

The earlier 33,098/33,098 exact row reconciliation compared the legacy-clean
candidate with the archived API snapshot. The legacy cleaner reads the same
upstream-shaped `prizeLevelList` fields (`prizeLevel`, `stakeAmount`,
`stakeCount`, `totalPrizeamount`, `lotteryCondition`) and drops other
identity fields. The legacy raw input is unavailable, so exact equality does
not prove independent source corroboration. It proves only that the candidate
and the archived API representation agree on displayed values.

The archived API itself conflicts with contemporaneous provincial result
announcements for several known draws. Therefore the earlier reconciliation
must not be described as proof that the legacy prize values are correct.

## Confirmed examples

### Issue 17052 — second-prize amount conflict

The archived API snapshot records the second-prize row as:

- label: `二等奖`
- unit amount: ¥1,551,723
- winners: 93
- total: ¥144,310,239

The Jiangsu Sports Lottery announcement reports second prize as ¥81,082 for
93 winners, total ¥7,540,626. The API value ¥1,551,723 is the same amount
shown on that announcement for the first-prize promotion row, not the
second-prize row.

Source: [Jiangsu Sports Lottery, issue 17052](https://www.js-lottery.com/cms/post-77436.html),
published 2017-05-08; see the prize table around lines 91–98 in the page.

### Issue 17062 — multiple amount and winner-count conflicts

The archived API snapshot records, among others:

| Label | API unit amount | API winners |
|---|---:|---:|
| 二等奖 | ¥893,219 | 58 |
| 二等奖(追加) | ¥714,575 | 19 |
| 三等奖 | ¥10,000 | 82 |
| 四等奖 | ¥300 | 12,294 |
| 五等奖 | ¥100 | 25,671 |

The Jiangsu announcement reports:

| Prize | Published unit amount | Published winners |
|---|---:|---:|
| 二等奖基本 | ¥191,426 | 57 |
| 二等奖追加 | ¥114,855 | 19 |
| 三等奖基本 | ¥8,612 | 467 |
| 三等奖追加 | ¥5,167 | 207 |
| 四等奖基本 | ¥200 | 22,123 |
| 四等奖追加 | ¥100 | 10,096 |
| 五等奖基本 | ¥10 | 430,836 |
| 五等奖追加 | ¥5 | 210,646 |

Source: [Jiangsu Sports Lottery, issue 17062](https://www.js-lottery.com/cms/post-77775.html),
published 2017-05-31; see the prize table around lines 91–104.

### Issue 17063 — repeated API rows conflict with the next official result

In the archived API snapshot, the second- through sixth-prize values and
winner counts for issues 17062 and 17063 are repeated across multiple rows.
The Jiangsu issue-17063 announcement instead reports:

- second prize: ¥24,867 / 281 winners; additional ¥14,920 / 106 winners;
- third prize: ¥1,500 / 2,276 winners; additional ¥900 / 949 winners;
- fourth prize: ¥200 / 71,646 winners; additional ¥100 / 29,780 winners;
- fifth prize: ¥10 / 1,010,516 winners; additional ¥5 / 424,755 winners;
- sixth prize: ¥5 / 7,594,536 winners.

Source: [Jiangsu Sports Lottery, issue 17063](https://www.js-lottery.com/cms/post-77825.html),
published 2017-06-03; see the prize table around lines 89–102.

This is not a small rounding difference. The API values for these rows must
not be used as trusted payout observations until the upstream mapping and
historical announcement discrepancy are resolved.

### Issue 07008 — API contains additional rows not present in the official main-game announcement

The archived API snapshot contains `四等奖(追加)` at ¥3,000 for 92
winners and `五等奖(追加)` at ¥500 for 2,581 winners. These values duplicate
the basic fourth- and fifth-prize rows in the same API draw.

The Jiangsu announcement separately lists the main-game basic prizes and says
the only main-game additional-bet winners were six third-prize winners at
¥4,582. It does not list fourth- or fifth-prize additional winners. The page
also separately identifies an "附加玩法" result, which must not be conflated
with additional betting on the main game.

Source: [Jiangsu Sports Lottery, issue 07008](https://www.js-lottery.com/cms/post-2575.html),
published 2007-06-16; see the main-game prize table around lines 95–114 and
the separate side-game section beginning around line 118.

This supports quarantining the API's 07008 additional rows and is consistent
with the broader finding that 2007 early-era fixed-tier additional rows need
source-level review.

### Issue 17045 — promotion overlay is not represented cleanly

The Jiangsu announcement separates basic awards, promotion awards, and
additional-bet awards. For example, fourth prize has 20,110 basic winners at
¥200, plus 11,473 promotion winners at ¥100, plus 11,473 additional winners
at ¥100. Fifth and sixth prize also contain separately listed promotion
rows.

The archived API list instead has only one `四等奖(追加)` row at ¥100 for
11,473 winners and one `五等奖(追加)` row at ¥5 for 216,069 winners; its
fifth-prize base row is ¥100, while the provincial announcement reports
¥10. The API does not preserve the full three-way row structure shown in the
provincial announcement.

Source: [Jiangsu Sports Lottery, issue 17045](https://www.js-lottery.com/cms/post-77220.html),
published 2017-04-22; see the prize table around lines 89–105.

## Nearby control: issue 17061 matches

The immediately preceding issue 17061 provides a useful control. The API
snapshot's second prize (¥65,013 / 116 winners), second-prize additional
(¥39,007 / 53), third prize (¥3,223 / 878), fourth prize (¥200 / 39,951),
fifth prize (¥10 / 712,112), and sixth prize (¥5 / 5,988,421) match the
Jiangsu announcement's corresponding figures exactly. This shows the
17062–17063 conflicts are not explained by a blanket formatting or rounding
difference affecting every draw in that neighborhood.

Source: [Jiangsu Sports Lottery, issue 17061](https://www.js-lottery.com/cms/post-77749.html),
published 2017-05-29; see the prize table around lines 89–102.

## Consequences and handling

1. Keep the raw API archive unchanged. It is evidence of what that API returned,
   not proof that every returned historical payout value is correct.
2. Keep the legacy prize candidate unchanged as a candidate. Do not promote
   its values to trusted payout truth merely because they match the API export.
3. Quarantine at least issues 17045, 17052, 17062, and 17063 from payout
   calculations, prize-model targets, and any training feature derived from
   these prize fields.
4. Expand the cross-source audit to adjacent issues and other historical
   campaign periods. Do not assume the four examples are the complete affected
   set.
5. Prefer source-preserving records and preserve the provenance of every
   competing source. Do not silently overwrite one source with another.
6. The selected-number/date dataset is a separate concern: these prize conflicts
   do not by themselves invalidate the draw-number fields or the independent
   selected-number cross-check.

## Next verification gate

Before prize data can be marked trusted, reconcile the full per-draw award
table against an independent contemporaneous result source or a verifiable
official central archive, including promotion overlays and additional-bet
rows. Where sources disagree, preserve both values and mark the draw/field
unresolved. No automatic repair is authorized by this report.


## Expanded early-era audit: issues 07006–07011

A draw-by-draw comparison of the archived API rows with six contemporaneous
Jiangsu Sports Lottery result announcements found a repeated structural
discrepancy. In every issue from 07006 through 07011, the API's fourth- and
fifth-prize additional rows duplicate the same unit amounts and winner counts
as the corresponding basic rows. The provincial main-game additional-bet
tables list first, second, and third prize only; they do not list fourth- or
fifth-prize additional awards.

For 07006, 07007, 07009, 07010, and 07011, the API third-prize additional
amount/count also matches the provincial announcement. For 07008, the API
reports ¥4,528 × 6 while the provincial announcement reports ¥4,582 × 6.
The per-draw comparisons and exact values are recorded in
[EARLY_2007_ADDITIONAL_PRIZE_AUDIT_2026-11-18.md](EARLY_2007_ADDITIONAL_PRIZE_AUDIT_2026-11-18.md).

Issues 07006–07011 have therefore been added to the minimum known quarantine
set. This is a conservative draw-level exclusion while the source rows are
adjudicated; it does not mean the basic-prize rows in every one of those draws
are themselves proven wrong. Issues 07001–07005 show a similar API row shape
but remain unconfirmed leads, not confirmed conflicts.
