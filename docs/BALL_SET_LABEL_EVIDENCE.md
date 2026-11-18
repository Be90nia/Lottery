# Ball-set label evidence and data readiness

**Status: three-set semantics confirmed; historical row-level coverage still blocked pending an archival audit.** This document does not identify any numeric equipment-count field as a physical ball-set ID.

## 1. What authoritative sources establish

### 1.1 Three formal physical sets exist

The State General Administration of Sport article “体彩品牌开放日：细节见证公信力” states that Super Lotto has three sets of formal draw balls, that all are kept by notaries, and that the set used on a given draw day is selected before the draw under notarial supervision:

- https://www.sport.gov.cn/n20001280/n20067608/n20067637/c27201503/content.html

The official China Sports Lottery 2019 Social Responsibility Report independently describes the three sets and their inspection/handling requirements:

- https://www.sport.gov.cn/n315/n20067006/c20260981/part/20260998.pdf
- Printed page 49, section “体彩彩票乐透摇奖球” (PDF page content around lines 1196–1208 in parsed text).

These sources confirm the physical three-set concept. They do not map historical draw IDs to a set.

### 1.2 Individual official draw announcements can publish the set used

The following Guangdong Sports Lottery draw-announcement pages explicitly state “本期使用第X套摇奖球”:

| Draw | Date | Officially stated set | Source |
|---|---|---:|---|
| 26104 | 2026-09-12 | 2 | https://www.gdlottery.cn/f_html/kjgg/P085_26104.html |
| 26106 | 2026-09-16 | 3 | https://gdlottery.cn/f_html/kjgg/P085_26106.html |
| 26110 | 2026-09-26 | 1 | https://gdlottery.cn/f_html/kjgg/P085_26110.html |

These examples establish that an explicit per-draw label is published in at least some provincial official result records. They are examples, not a complete coverage audit for the 2,949-row historical snapshot.

## 2. What the repository currently establishes

The canonical ingestion schema retains the upstream `lotteryEquipmentCount` value as `source_equipment_count` and `lotteryUnsortDrawresult` as `source_unsort_drawresult`. These are raw source fields, not normalized claims about physical ball-set identity or actual draw sequence.

The legacy candidate audit reports 2,336 rows with equipment code 1, 2, or 3 and 565 rows with code 0/unknown. It also reports 560 missing draw-order values. These counts describe a derived legacy candidate only. The candidate's equipment metadata has not been independently reconciled against immutable official per-draw announcements and must not be used as verified ball-set labels.

The independently cross-checked PickWise snapshot corroborates selected numbers and dates for its overlap with the legacy candidate; it does not validate equipment or physical ball-set metadata.

The canonical official history collector currently consumes draw number, draw date, and selected-number result; it does not yet archive and parse the explicit “本期使用第X套摇奖球” field from per-draw official announcements.

## 3. Required archival coverage audit

The next task is not to re-prove that three sets exist. It is to establish how completely and reproducibly official per-draw labels can be recovered.

1. Enumerate every draw ID in the frozen 2,949-row canonical dataset.
2. Resolve each draw to an official national or provincial result-announcement URL. Record the selected authority/domain and the exact source URL.
3. Preserve the exact HTML/PDF response bytes, retrieval timestamp, SHA-256, and parser version. A search snippet is discovery evidence only, not an archived row-level source.
4. Extract a set label only when the official per-draw source explicitly states “本期使用第1/2/3套摇奖球”. Do not infer from adjacent draws or other fields.
5. Assign distinct statuses: `verified_set_1`, `verified_set_2`, `verified_set_3`, `missing_official_label`, `conflicting_official_sources`, and `unavailable_record`.
6. Publish a row-level mapping with source URL/hash and extraction evidence for every verified row.
7. Report coverage by calendar year, draw era, and source domain; include missingness, conflicts, first/last verified draw per set, longest gaps, and the denominator of all eligible draws.
8. Manually verify a stratified sample and every conflict against the archived source bytes. Independent reviewers must be able to reproduce the mapping without inspecting drawn-number patterns.

Do not map `source_equipment_count` to ball-set identity, even if values happen to be 1/2/3. The explicit per-draw official announcement is the required label evidence.

## 4. Modeling eligibility

Do not set a minimum sample size after seeing which model performs best. Before scoring, preregister a per-set eligibility rule that considers:
- minimum number of earlier verified labeled draws at every evaluated target;
- temporal coverage and regime stability;
- effective sample size for any weighted estimator;
- optimizer convergence and finite normalized probabilities;
- calibration and uncertainty width;
- performance relative to both pooled and uniform baselines.

If a set is ineligible, its independent model slot remains unavailable. Do not copy pooled output into that slot and call it set-specific. If official records cannot be recovered for older periods, use only a verified subset under the preregistered eligibility rule; never backfill labels by inference.

## 5. Current decision

- The official three-physical-set semantics are confirmed.
- Explicit per-draw set labels are demonstrably published in some official result announcements.
- Complete historical coverage and reproducible row-level mapping are **not yet established**.
- `source_equipment_count` remains raw metadata and must not be used as a ball-set label.
- No three-way historical training partition is approved until the archival audit is complete.
- LOT-051 must exclude all equipment/ball-set fields from its confirmatory feature set.
- LOT-053 Stage 0 remains incomplete.
- The N → 3N product contract is a future gated behavior, not a currently available predictor.

This is now a historical-source coverage and archival reproducibility blocker, not a question about whether three physical sets exist. It does not prevent continued development of the pooled model.
