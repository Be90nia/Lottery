# Ball-set label evidence and data readiness

**Status: blocked pending authoritative semantics.** This document deliberately does not identify any numeric equipment field as a physical ball-set ID.

## 1. What the current repository actually establishes

The canonical ingestion schema retains the upstream `lotteryEquipmentCount` value as `source_equipment_count` and `lotteryUnsortDrawresult` as `source_unsort_drawresult`. The data specification explicitly treats these as raw evidence fields, not normalized claims about equipment identity, physical ball-set identity, or actual draw sequence.

The legacy candidate audit reports 2,336 rows with equipment code 1, 2, or 3 and 565 rows with code 0/unknown. It also reports 560 missing draw-order values. These counts describe a derived legacy candidate only. The candidate's equipment metadata was not independently reconciled against immutable official response snapshots and must not be used as verified ball-set labels.

The independently cross-checked PickWise snapshot corroborates selected numbers and dates for its overlap with the legacy candidate; it does not validate equipment, ball-set, prize, or draw-order metadata.

The official history API's currently documented/consumed fields in this repository include draw number, draw date, and selected-number result. The collector does not currently consume a verified physical ball-set identifier.

## 2. Evidence required before assigning ball_set_id

A label mapping can be approved only when all of the following are archived:

1. An authoritative source (official rules, official announcement, official result record, or official data dictionary) explicitly defines the field and its relationship to the physical ball set.
2. The source identifies whether values 1/2/3 mean ball-set identity, count of available equipment, machine count, sequence, or another concept.
3. Effective dates and any changes to the meaning or coding are documented.
4. Raw source records are preserved with URL, retrieval time, exact response hash, and parser version.
5. A row-level mapping report identifies verified set 1/2/3, unknown, conflicting, and out-of-scope rows.
6. Independent reviewers can reproduce the mapping from archived evidence without looking at drawn numbers.

A numeric value of 1, 2, or 3 is not evidence of identity by itself. Never infer a label from number frequencies, draw order, date patterns, or a desired balanced partition.

## 3. Required partition report

For each verified ball set, report:
- total eligible draws and proportion of all draws;
- counts by calendar year and rules/equipment era;
- first and last eligible draw, longest coverage gap, and missing-label rate;
- conflicting or corrected source rows;
- selected-number completeness and draw-order completeness separately;
- source snapshot hashes and mapping-spec version.

Keep unknown/unmapped records in a separate partition. Never silently drop them from coverage denominators or impute a ball-set label.

## 4. Modeling eligibility

Do not set a minimum sample size after seeing which model performs best. Before scoring, derive and preregister a per-set eligibility rule that considers:
- minimum number of earlier labeled draws at every evaluated target;
- temporal coverage and regime stability;
- effective sample size for any weighted estimator;
- optimizer convergence and finite normalized probabilities;
- calibration and uncertainty width;
- performance relative to both pooled and uniform baselines.

If a set is ineligible, its independent model slot remains unavailable. Do not copy pooled output into that slot and call it set-specific.

## 5. Current decision

- `source_equipment_count` remains raw metadata.
- No three-way historical training partition is approved.
- LOT-051 must exclude all equipment/ball-set fields from its confirmatory feature set.
- LOT-053 Stage 0 is not complete.
- The N → 3N product contract is a future gated behavior, not a currently available predictor.

This is a data-semantics blocker, not a reason to stop improving the pooled model.
