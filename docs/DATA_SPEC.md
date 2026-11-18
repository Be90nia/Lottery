# Data Specification

This document defines a target schema. It is not a claim that every historical source already supplies every field.

## Draw record

| Field | Type | Requirement | Meaning |
|---|---|---|---|
| draw_id | string | required | Official draw identifier; preserve leading zeros |
| draw_date | date | required | Official local draw date |
| front_numbers | integer[5] | required | Five distinct values in 1..35 |
| back_numbers | integer[2] | required | Two distinct values in 1..12 |
| front_draw_order | integer[5] | optional | Order actually drawn, only where source supports it |
| back_draw_order | integer[2] | optional | Order actually drawn, only where source supports it |
| source_id | string | required | Provenance reference |
| ruleset_id | string | required when resolved | Rule version applicable to draw |
| equipment_id | string | nullable | Equipment metadata with source |
| ball_set_id | string | nullable | Ball-set metadata with source |
| source_unsort_drawresult | string | nullable | Exact source field value, retained for audit; not itself proof of physical draw sequence |
| source_equipment_count | JSON value | nullable | Exact source metadata value; do not map to equipment identity without documentation |

## Prize record

Store prize tiers as separate rows keyed by draw and tier. Preserve original source label and amount fields. Do not merge base and add-on awards unless a derived field explicitly documents the aggregation rule.

Suggested fields: draw_id, tier_code, source_tier_label, base_winners, base_amount, addon_winners, addon_amount, promotion_winners, promotion_amount, source_id.

Amounts should use integer minor currency units (for example, fen) or decimal arithmetic, never binary floating-point for financial reconciliation.

## Provenance

The ingestion JSONL also retains the upstream `lotteryUnsortDrawresult` and `lotteryEquipmentCount` values in explicitly source-named fields. These are evidence-preservation fields, not normalized claims about physical draw order, machine identity, or ball-set identity. Exact response bytes remain the primary evidence.

Every source snapshot should record:
- source URL and source organization
- retrieval timestamp with timezone
- HTTP status and relevant response metadata
- SHA-256 of exact response bytes
- parser version and ingestion run identifier

## Validation

- draw_id is unique after source reconciliation.
- draw_date is parseable and consistent with source.
- exactly five distinct front numbers in 1..35.
- exactly two distinct back numbers in 1..12.
- draw order, when present, is a permutation of the corresponding selected numbers.
- prize counts and amounts are nonnegative and use explicit units.
- duplicates and conflicting source records are quarantined for review.
- missing values remain missing; never fabricate device, ball-set, order, or prize data.

## Time splits

All model splits use draw_date/draw_id chronology. A feature is eligible only if it would have been available before the target draw. Metadata published after the draw may be used for retrospective explanation, not prediction.

## Versioned prize rules

The rules registry covers the reconstructed eight-tier 2007 launch rules
(07001–09120), eight-tier 2009/2013 rules (09121–14051), six-tier 2014 rules
(14052–19018), nine-tier 2019 rules (19019–26013), and seven-tier 2026 rules
(from 26014). The launch-era rules are reconstructed from contemporaneous
coverage and provincial results rather than an archived primary rule document;
retain that source-quality caveat. See [PRIZE_RULES.md](PRIZE_RULES.md).
