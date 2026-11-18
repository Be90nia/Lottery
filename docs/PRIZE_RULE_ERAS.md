# Prize-rule eras and promotion provenance

This file records only rules with a directly linked official source. It is separate from the number-frequency analysis: prize-rule changes affect payout accounting, not the 5-of-35 / 2-of-12 draw-space definition.

## Rule change effective from issue 26014

The official China Sports Lottery calculator states that the Super Lotto game rules changed starting with issue 26014, with sales beginning on 2026-01-31. An official article dated 2026-02-05 describes the new rules as having taken effect from issue 26014 (drawn 2026-02-02).

Known changes documented by the official source include:
- the prize structure was consolidated to seven prize levels;
- first- and second-prize amounts remain floating and depend on sales, pool balance, and winning counts;
- fixed prizes from third to seventh level increase when the prize pool reaches at least RMB 800 million;
- additional betting adds 80% of the corresponding basic-bet floating prize.

Sources:
- Official calculator and its rule-change note: https://m.lottery.gov.cn/mltsz/jsq/index.html
- Official article on the first two draws under the new rules: https://m.lottery.gov.cn/zx/zj/20260205/10052318.html
- Official current game rules: https://m.lottery.gov.cn/ksjz/m/yxgz_dlt/

Implementation rule: prize rows before and after issue 26014 must not be interpreted using one static tier mapping or fixed-prize table. The exact legacy mapping and effective-date table still needs an official archived pre-26014 rules source before prize rows are normalized.

## 2026 promotion: issues 26050–26066

The official 2026 promotion announcement specifies:
- promotion begins with issue 26050;
- a single ticket for a single draw must have a purchase amount of at least RMB 18 to qualify;
- eligible third-to-sixth prize wins receive a promotion amount equal to 50% of the corresponding per-ticket prize;
- eligible seventh-prize wins receive an additional amount equal to 100% of the corresponding per-ticket prize;
- the official end notice states that the RMB 880 million promotion funds were fully distributed by issue 26066 and the promotion ended with that issue.

Sources:
- Official promotion announcement (2026-04-30): https://m.lottery.gov.cn/xxgk/tzgg/dlttz/20260428/10053457.html
- Official promotion end notice (2026-06-15): https://m.lottery.gov.cn/xxgk/tzgg/dlttz/20260615/10054208.html

The legacy candidate's promotion flags identify the contiguous range 26050–26066, which agrees with the official 2026 promotion period. This agreement does not validate promotion flags in earlier years. Ticket-level eligibility cannot be reconstructed from draw-level flags alone; ticket purchase amount and multi-draw ticket semantics are required.

## Open questions

- Obtain an official archived rules document for the period before issue 26014.
- Reconcile legacy award-type rows and labels against the original API response fields.
- Model the RMB 18 threshold at the ticket-and-draw level, not at the draw level.
- Keep floating-prize pool calculations distinct from fixed-prize accounting.
