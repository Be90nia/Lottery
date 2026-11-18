"""Conservative audit helpers for legacy prize rows."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from collections import Counter

from .rules import UnsupportedRulesetError, ruleset_for_draw
from typing import Any, Iterable


class PrizeDataError(ValueError):
    pass


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


def audit_prize_rows(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    seen: set[tuple[str, str]] = set()
    labels: set[str] = set()
    label_counts: Counter[str] = Counter()
    ruleset_counts: Counter[str] = Counter()
    unsupported_ruleset_rows = 0
    draws: set[str] = set()
    count = 0
    missing_amount = 0
    missing_total = 0
    amount_total_mismatches = 0
    zero_amount_positive_total = 0
    examples: list[dict[str, Any]] = []
    for count, row in enumerate(rows, start=1):
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
        if amount is not None and total is not None and amount * winners != total:
            amount_total_mismatches += 1
            if amount == 0 and total > 0:
                zero_amount_positive_total += 1
            if len(examples) < 10:
                examples.append({"draw_id": draw_id, "tier": label,
                                 "amount": str(amount), "winner_count": winners,
                                 "total": str(total)})
    return {
        "prize_rows": count,
        "draw_ids": len(draws),
        "tier_label_kinds": len(labels),
        "tier_label_counts": dict(sorted(label_counts.items())),
        "ruleset_row_counts": dict(sorted(ruleset_counts.items())),
        "unsupported_ruleset_rows": unsupported_ruleset_rows,
        "missing_amount_rows": missing_amount,
        "missing_total_rows": missing_total,
        "amount_times_count_mismatch_rows": amount_total_mismatches,
        "zero_amount_positive_total_rows": zero_amount_positive_total,
        "mismatch_examples": examples,
    }
