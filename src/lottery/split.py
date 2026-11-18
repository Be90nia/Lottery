"""Deterministic date-grouped chronological dataset splitting."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from .validate import validate_records


def split_chronologically(
    rows: Iterable[dict[str, Any]],
    *,
    train_fraction: float = 0.70,
    validation_fraction: float = 0.15,
) -> dict[str, Any]:
    """Split sorted records at date boundaries; never shuffle or split a date."""
    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction must be strictly between 0 and 1")
    if not 0 < validation_fraction < 1:
        raise ValueError("validation_fraction must be strictly between 0 and 1")
    if train_fraction + validation_fraction >= 1:
        raise ValueError("train_fraction + validation_fraction must be less than 1")

    records = list(rows)
    validation = validate_records(records)
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    ordered_dates: list[str] = []
    for row in records:
        draw_date = row["draw_date"]
        if draw_date not in by_date:
            ordered_dates.append(draw_date)
        by_date[draw_date].append(row)

    date_count = len(ordered_dates)
    if date_count < 3:
        raise ValueError("at least three distinct draw dates are required")

    train_end = max(1, min(date_count - 2, int(date_count * train_fraction)))
    validation_end = max(
        train_end + 1,
        min(date_count - 1, int(date_count * (train_fraction + validation_fraction))),
    )
    train_dates = ordered_dates[:train_end]
    validation_dates = ordered_dates[train_end:validation_end]
    test_dates = ordered_dates[validation_end:]

    partitions = {
        "train": [row for day in train_dates for row in by_date[day]],
        "validation": [row for day in validation_dates for row in by_date[day]],
        "test": [row for day in test_dates for row in by_date[day]],
    }
    boundaries = {}
    for name, partition in partitions.items():
        boundaries[name] = {
            "records": len(partition),
            "date_groups": len({row["draw_date"] for row in partition}),
            "first_draw_id": partition[0]["draw_id"],
            "last_draw_id": partition[-1]["draw_id"],
            "date_start": partition[0]["draw_date"],
            "date_end": partition[-1]["draw_date"],
        }
    return {
        "partitions": partitions,
        "metadata": {
            "method": "contiguous chronological split at distinct draw-date boundaries; no shuffle",
            "input_records": validation["records"],
            "input_date_groups": date_count,
            "requested_train_fraction": train_fraction,
            "requested_validation_fraction": validation_fraction,
            "requested_test_fraction": 1.0 - train_fraction - validation_fraction,
            "actual_row_fractions": {
                name: len(partition) / len(records)
                for name, partition in partitions.items()
            },
            "boundaries": boundaries,
        },
    }
