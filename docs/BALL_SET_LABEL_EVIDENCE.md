# Ball-set label evidence and data readiness

**Status: multiple official equipment regimes are confirmed; the transition date and historical row-level coverage remain unresolved.** This document does not identify any numeric equipment-count field as a physical ball-set ID.

## 1. Authoritative evidence: the equipment regime changed or was described differently over time

### 1.1 Initial 2007 procedure described two formal sets

The State General Administration of Sport's “超级大乐透”开奖流程 article, published 2007-06-04 shortly after the game's first draw, states that the host/onsite audience selected one set from **two formal sets of draw balls** for that day's draw:

- https://www.sport.gov.cn/cpzx/n5649/c663435/content.html
- Published 2007-06-04; paragraph 2 of the procedure.

This is contemporaneous official evidence for a two-set procedure at launch.

### 1.2 Official material by 2018 describes three formal sets

The State General Administration of Sport article “全方位升级 体彩开奖场地的‘变与不变’” discusses the 2018 draw-hall upgrade and states that Super Lotto has three sets of formal draw balls, all kept by notaries:

- https://www.sport.gov.cn/n20001280/n20745751/n20767297/c21145964/content.html

A State General Administration of Sport article published 2020-01-03 independently confirms that three sets are held by notaries and that a host/guest draws the set index before a draw:

- https://www.sport.gov.cn/cpzx/n5651/c939578/content.html

The official China Sports Lottery 2019 Social Responsibility Report also describes three sets and their inspection/handling requirements:

- https://www.sport.gov.cn/n315/n20067006/c20260981/part/20260998.pdf
- Printed page 49, section “体彩彩票乐透摇奖球”.

**The exact transition date, the reason for the change, and whether set identities were carried forward or renumbered are not established by these sources.** Do not infer them. The transition occurred after the documented 2007 two-set procedure and no later than the 2018 three-set description, but its exact effective date remains unresolved.

### 1.3 Individual official draw announcements can publish the set index

The following Guangdong Sports Lottery draw-announcement pages explicitly state “本期使用第X套摇奖球”:

| Draw | Date | Officially stated index | Source |
|---|---|---:|---|
| 26104 | 2026-09-12 | 2 | https://www.gdlottery.cn/f_html/kjgg/P085_26104.html |
| 26106 | 2026-09-16 | 3 | https://gdlottery.cn/f_html/kjgg/P085_26106.html |
| 26110 | 2026-09-26 | 1 | https://www.gdlottery.cn/f_html/kjgg/P085_26110.html |

These examples prove that explicit per-draw indices are published in at least some official provincial result records. They do not prove complete historical coverage or establish that an index has the same physical identity across equipment regimes.

## 2. Consequences for the historical data model

A single timeless three-class label is not valid for the entire 2007–present dataset based on current evidence.

The evidence ledger must distinguish:
- equipment regime (for example, documented two-set regime, documented three-set regime, unresolved transition/unknown);
- the official per-draw set index within that regime;
- whether the physical identity is known to continue across a regime transition.

Do not assume that “set 1” in the two-set period is the same physical equipment as “set 1” in the three-set period. Only explicit official continuity/renumbering evidence can establish that mapping.

The 2007 source documents the two-set procedure at launch; official material documents a three-set regime by 2018. They do not establish the exact effective date of the transition. This interval is a required research item, not a date to be guessed.

## 3. What the repository currently establishes

The canonical ingestion schema retains the upstream `lotteryEquipmentCount` value as `source_equipment_count` and `lotteryUnsortDrawresult` as `source_unsort_drawresult`. These are raw source fields, not normalized claims about physical ball-set identity or actual draw sequence.

The legacy candidate audit reports 2,336 rows with equipment code 1, 2, or 3 and 565 rows with code 0/unknown. It also reports 560 missing draw-order values. These counts describe a derived legacy candidate only. The candidate's equipment metadata has not been independently reconciled against immutable official per-draw announcements and must not be used as verified ball-set labels.

The independently cross-checked PickWise snapshot corroborates selected numbers and dates for its overlap with the legacy candidate; it does not validate equipment or physical ball-set metadata.

The canonical official history collector currently consumes draw number, draw date, and selected-number result; it does not yet archive and parse the explicit “本期使用第X套摇奖球” field from per-draw official announcements.

## 4. Required archival coverage and regime audit

1. Enumerate every draw ID in the frozen 2,949-row canonical dataset.
2. Resolve each draw to an official national or provincial result-announcement URL. Preserve exact HTML/PDF response bytes, retrieval timestamp, SHA-256, and parser version.
3. Extract a set index only when the official per-draw source explicitly states “本期使用第X套摇奖球”. A search snippet is discovery evidence only, not an archived row-level source.
4. Find authoritative evidence for the two-set to three-set transition date, including any equipment replacement, renumbering, or continuity statement. If no exact date can be established, retain an unresolved regime interval and exclude it from cross-regime identity claims.
5. Assign separate statuses: `verified_two_set_regime_index_1/2`, `verified_three_set_regime_index_1/2/3`, `unknown_regime`, `missing_official_label`, `conflicting_official_sources`, and `unavailable_record`.
6. Publish a row-level map with draw ID, draw date, regime ID, official index, source URL/hash, parser version, and extraction evidence.
7. Report coverage by calendar year, regime, and source domain; include missingness, conflicts, first/last verified draw per index, longest gaps, and denominators.
8. Manually verify a stratified sample and every conflict against archived source bytes. Independent reviewers must reproduce the mapping without inspecting drawn-number patterns.

Do not map `source_equipment_count` to ball-set identity, even if values happen to be 1/2/3. Do not infer from adjacent draws, draw order, or number patterns.

## 5. Modeling eligibility and product consequence

Do not train three timeless historical models by simply grouping every historical “set 1/2/3” index together. Before fitting, establish the regime boundary and whether identities are continuous. Otherwise, treat regimes as distinct conditional populations and preregister which regime has enough verified history for each model slot.

Do not set minimum sample sizes after seeing model performance. Eligibility must consider:
- minimum number of earlier verified labeled draws at every evaluated target;
- temporal coverage and regime stability;
- effective sample size;
- optimizer convergence and finite normalized probabilities;
- calibration and uncertainty width;
- performance relative to pooled and uniform baselines.

If one or more slots are ineligible, the N → 3N generator remains unavailable. Do not copy pooled output into a missing slot or combine unrelated equipment regimes to manufacture sample size.

## 6. Current decision

- Two formal sets are documented in the official 2007 launch-era procedure.
- Three formal sets are documented in official material by 2019.
- The transition date and physical identity continuity are not yet established.
- Explicit per-draw set indices are demonstrably published in some later official result announcements.
- Complete historical per-draw coverage and reproducible row-level mapping are not yet established.
- `source_equipment_count` remains raw metadata and must not be used as a ball-set label.
- LOT-053 Stage 0 remains incomplete; a timeless three-way historical partition is not approved.
- LOT-051 must exclude all equipment/ball-set fields from its confirmatory feature set.
- N → 3N remains a future gated behavior, not a currently available predictor.

The blocker is now specifically historical regime reconstruction, identity continuity, and row-level source coverage. It does not prevent continued development of the pooled model.
