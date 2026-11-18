"""Conservative audit and base/additional award reconciliation for legacy prize rows."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP
from typing import Any, Iterable

from .rules import UnsupportedRulesetError, ruleset_for_draw


class PrizeDataError(ValueError):
    pass


_CHINESE_TIER = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9,
}


def classify_prize_label(label: str) -> dict[str, Any]:
    """Classify the original label without normalizing or replacing it."""
    tier_number = None
    for chinese, number in _CHINESE_TIER.items():
        if label.startswith(chinese + "等奖"):
            tier_number = number
            break
    if "派奖" in label:
        kind = "promotion_overlay"
        promotion_kind = "additional" if "追加" in label else (
            "basic" if "基本" in label else "unspecified"
        )
    elif "附加玩法" in label or "幸运彩" in label:
        kind = "side_game"
        promotion_kind = None
    elif label.endswith("(追加)") or label.endswith("（追加）"):
        kind = "additional_bet"
        promotion_kind = None
    elif tier_number is not None and label in {
        "一等奖", "二等奖", "三等奖", "四等奖", "五等奖",
        "六等奖", "七等奖", "八等奖", "九等奖",
    }:
        kind = "base_award"
        promotion_kind = None
    else:
        kind = "unknown"
        promotion_kind = None
    return {
        "original_label": label,
        "award_kind": kind,
        "tier_number": tier_number,
        "promotion_kind": promotion_kind,
    }


def _decimal_or_none(value: Any, field: str, row_no: int) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PrizeDataError(f"row {row_no}: {field} must be a decimal string or null")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise PrizeDataError(f"row {row_no}: invalid decimal in {field}: {value!r}") from exc
    if not amount.is_finite() or amount < 0:
        raise PrizeDataError(f"row {row_no}: {field} must be finite and nonnegative")
    return amount


def reconcile_additional_awards(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    records = list(rows)
    base_rows: dict[tuple[str, int], dict[str, Any]] = {}
    additional_rows: dict[tuple[str, int], dict[str, Any]] = {}
    unsupported = []
    for row in records:
        parsed = classify_prize_label(row.get("tier_label_original", ""))
        tier = parsed["tier_number"]
        if tier is None:
            continue
        key = (row.get("draw_id", ""), tier)
        if parsed["award_kind"] == "base_award":
            base_rows[key] = row
        elif parsed["award_kind"] == "additional_bet":
            additional_rows[key] = row

    checked = 0
    unscorable = 0
    mismatches: list[dict[str, Any]] = []
    unexpected: list[dict[str, Any]] = []
    missing_base: list[dict[str, Any]] = []
    for key, additional in sorted(additional_rows.items()):
        draw_id, tier_number = key
        base = base_rows.get(key)
        if base is None:
            missing_base.append({"draw_id": draw_id, "tier": tier_number})
            continue
        try:
            ruleset = ruleset_for_draw(draw_id)
        except UnsupportedRulesetError:
            unsupported.append({"draw_id": draw_id, "tier": tier_number})
            continue
        multiplier = ruleset.additional_award_multiplier(tier_number)
        additional_winners = additional["winner_count"]
        base_winners = base["winner_count"]
        if additional_winners == 0:
            continue
        if multiplier is None or multiplier <= 0:
            unexpected.append({
                "draw_id": draw_id, "tier": tier_number,
                "ruleset_id": ruleset.ruleset_id,
                "additional_winner_count": additional_winners,
                "reason": "ruleset does not authorize an additional award for this tier",
            })
            continue
        if additional_winners > base_winners:
            mismatches.append({
                "draw_id": draw_id, "tier": tier_number,
                "ruleset_id": ruleset.ruleset_id,
                "reason": "additional winner count exceeds base winner count",
                "base_winner_count": base_winners,
                "additional_winner_count": additional_winners,
            })
            continue
        base_amount = _decimal_or_none(base["amount_yuan_original"], "base amount", 0)
        additional_amount = _decimal_or_none(
            additional["amount_yuan_original"], "additional amount", 0
        )
        if base_amount is None or additional_amount is None:
            unscorable += 1
            continue
        rounding_modes = {"floor": ROUND_DOWN, "half_up": ROUND_HALF_UP}
        rounding_mode = rounding_modes.get(ruleset.additional_award_rounding)
        if rounding_mode is None:
            raise PrizeDataError(
                f"unsupported additional-award rounding mode for {ruleset.ruleset_id}: "
                f"{ruleset.additional_award_rounding!r}"
            )
        expected = (base_amount * multiplier).to_integral_value(rounding=rounding_mode)
        checked += 1
        if additional_amount != expected:
            mismatches.append({
                "draw_id": draw_id, "tier": tier_number,
                "ruleset_id": ruleset.ruleset_id,
                "reason": "additional unit amount does not match the ruleset multiplier",
                "base_amount_yuan": str(base_amount),
                "multiplier": str(multiplier),
                "expected_additional_amount_yuan": str(expected),
                "actual_additional_amount_yuan": str(additional_amount),
                "base_winner_count": base_winners,
                "additional_winner_count": additional_winners,
            })
    return {
        "additional_pairs_checked": checked,
        "additional_pairs_unscorable_missing_amount": unscorable,
        "additional_pair_mismatches": len(mismatches),
        "unexpected_additional_row_count": len(unexpected),
        "additional_rows_missing_base_count": len(missing_base),
        "unsupported_ruleset_additional_row_count": len(unsupported),
        "mismatches": mismatches,
        "unexpected_additional_rows": unexpected,
        "additional_rows_missing_base": missing_base,
        "unsupported_ruleset_rows": unsupported,
        "rounding": "expected additional unit amount uses the rounding mode declared by the effective ruleset (floor or half_up)",
        "limitations": [
            "Original row labels and monetary values are not rewritten.",
            "Promotional award rows are not treated as ordinary additional bets.",
            "A discrepancy is a candidate-data inconsistency, not proof of official payout error.",
        ],
    }


def audit_prize_rows(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    records = list(rows)
    seen: set[tuple[str, str]] = set()
    labels: set[str] = set()
    label_counts: Counter[str] = Counter()
    award_kind_counts: Counter[str] = Counter()
    ruleset_counts: Counter[str] = Counter()
    unsupported_ruleset_rows = 0
    draws: set[str] = set()
    count = 0
    missing_amount = 0
    missing_total = 0
    amount_total_mismatches = 0
    promotion_rows = 0
    promotion_zero_amount_positive_total = 0
    promotion_total_yuan = Decimal("0")
    promotion_draw_ids: set[str] = set()
    promotion_rows_by_label: Counter[str] = Counter()
    promotion_zero_by_label: Counter[str] = Counter()
    promotion_prefix_summary: dict[str, dict[str, Any]] = {}
    examples: list[dict[str, Any]] = []
    promotion_examples: list[dict[str, Any]] = []

    for count, row in enumerate(records, start=1):
        required = ("draw_id", "tier_label_original", "amount_yuan_original",
                    "winner_count", "total_yuan_original", "source_id")
        missing = [field for field in required if field not in row]
        if missing:
            raise PrizeDataError(f"row {count}: missing fields {', '.join(missing)}")
        draw_id, label = row["draw_id"], row["tier_label_original"]
        if not isinstance(draw_id, str) or not draw_id:
            raise PrizeDataError(f"row {count}: draw_id must be a non-empty string")
        if not isinstance(label, str) or not label:
            raise PrizeDataError(f"row {count}: tier label must be a non-empty string")
        key = (draw_id, label)
        if key in seen:
            raise PrizeDataError(f"row {count}: duplicate draw/tier pair {key}")
        seen.add(key)
        draws.add(draw_id)
        labels.add(label)
        label_counts[label] += 1
        parsed = classify_prize_label(label)
        award_kind_counts[parsed["award_kind"]] += 1
        try:
            ruleset_counts[ruleset_for_draw(draw_id).ruleset_id] += 1
        except UnsupportedRulesetError:
            unsupported_ruleset_rows += 1
        winners = row["winner_count"]
        if type(winners) is not int or winners < 0:
            raise PrizeDataError(f"row {count}: winner_count must be a nonnegative integer")
        amount = _decimal_or_none(row["amount_yuan_original"], "amount_yuan_original", count)
        total = _decimal_or_none(row["total_yuan_original"], "total_yuan_original", count)
        missing_amount += amount is None
        missing_total += total is None

        if parsed["award_kind"] == "promotion_overlay":
            promotion_rows += 1
            promotion_draw_ids.add(draw_id)
            promotion_rows_by_label[label] += 1
            prefix = draw_id[:2] if len(draw_id) == 5 and draw_id.isdigit() else "unknown"
            prefix_summary = promotion_prefix_summary.setdefault(
                prefix, {"rows": 0, "draw_ids": set(), "zero_amount_positive_total_rows": 0,
                         "total_yuan": Decimal("0")}
            )
            prefix_summary["rows"] += 1
            prefix_summary["draw_ids"].add(draw_id)
            if total is not None:
                promotion_total_yuan += total
                prefix_summary["total_yuan"] += total
            if amount == 0 and total is not None and total > 0:
                promotion_zero_by_label[label] += 1
                prefix_summary["zero_amount_positive_total_rows"] += 1
                promotion_zero_amount_positive_total += 1
                if len(promotion_examples) < 10:
                    promotion_examples.append({
                        "draw_id": draw_id, "tier": label,
                        "amount": str(amount), "winner_count": winners,
                        "total": str(total),
                    })
            continue

        if amount is not None and total is not None and amount * winners != total:
            amount_total_mismatches += 1
            if len(examples) < 10:
                examples.append({"draw_id": draw_id, "tier": label,
                                 "amount": str(amount), "winner_count": winners,
                                 "total": str(total)})

    return {
        "prize_rows": count,
        "draw_ids": len(draws),
        "tier_label_kinds": len(labels),
        "tier_label_counts": dict(sorted(label_counts.items())),
        "award_kind_counts": dict(sorted(award_kind_counts.items())),
        "ruleset_row_counts": dict(sorted(ruleset_counts.items())),
        "unsupported_ruleset_rows": unsupported_ruleset_rows,
        "missing_amount_rows": missing_amount,
        "missing_total_rows": missing_total,
        "amount_times_count_mismatch_rows_excluding_promotions": amount_total_mismatches,
        "mismatch_examples": examples,
        "promotion_rows": promotion_rows,
        "promotion_draw_ids": len(promotion_draw_ids),
        "promotion_rows_by_label": dict(sorted(promotion_rows_by_label.items())),
        "promotion_zero_amount_positive_total_rows": promotion_zero_amount_positive_total,
        "promotion_zero_amount_positive_total_by_label": dict(sorted(promotion_zero_by_label.items())),
        "promotion_total_yuan": str(promotion_total_yuan),
        "promotion_summary_by_draw_id_prefix": {
            prefix: {
                "rows": values["rows"],
                "draw_ids": len(values["draw_ids"]),
                "zero_amount_positive_total_rows": values["zero_amount_positive_total_rows"],
                "total_yuan": str(values["total_yuan"]),
            }
            for prefix, values in sorted(promotion_prefix_summary.items())
        },
        "promotion_examples": promotion_examples,
        "additional_reconciliation": reconcile_additional_awards(records),
    }
