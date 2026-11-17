"""Validation of the canonical JSONL draw dataset."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


class DatasetValidationError(ValueError):
    pass


def validate_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    seen: dict[str, dict[str, Any]] = {}
    previous_key: tuple[str, str] | None = None
    errors: list[str] = []
    for index, row in enumerate(records, start=1):
        if not isinstance(row, dict):
            errors.append(f"row {index}: record must be an object")
            continue
        required = ("draw_id", "draw_date", "front_numbers", "back_numbers", "source_id")
        missing = [key for key in required if key not in row]
        if missing:
            errors.append(f"row {index}: missing fields {', '.join(missing)}")
            continue
        draw_id = row["draw_id"]
        draw_date = row["draw_date"]
        if not isinstance(draw_id, str) or not draw_id.strip():
            errors.append(f"row {index}: draw_id must be a non-empty string")
            continue
        if not isinstance(draw_date, str):
            errors.append(f"row {index} ({draw_id}): draw_date must be a string")
            continue
        try:
            date.fromisoformat(draw_date)
        except ValueError:
            errors.append(f"row {index} ({draw_id}): invalid ISO date {draw_date!r}")
            continue
        front, back = row["front_numbers"], row["back_numbers"]
        if not isinstance(front, list) or len(front) != 5 or any(type(n) is not int for n in front):
            errors.append(f"row {index} ({draw_id}): front_numbers must contain exactly 5 integers")
            continue
        if len(set(front)) != 5 or any(n < 1 or n > 35 for n in front):
            errors.append(f"row {index} ({draw_id}): front_numbers must be distinct values in 1..35")
        if not isinstance(back, list) or len(back) != 2 or any(type(n) is not int for n in back):
            errors.append(f"row {index} ({draw_id}): back_numbers must contain exactly 2 integers")
            continue
        if len(set(back)) != 2 or any(n < 1 or n > 12 for n in back):
            errors.append(f"row {index} ({draw_id}): back_numbers must be distinct values in 1..12")
        if not isinstance(row["source_id"], str) or not row["source_id"]:
            errors.append(f"row {index} ({draw_id}): source_id must be non-empty")
        key = (draw_date, draw_id)
        if previous_key is not None and key < previous_key:
            errors.append(f"row {index} ({draw_id}): dataset is not sorted chronologically")
        previous_key = key
        if draw_id in seen:
            errors.append(f"row {index} ({draw_id}): duplicate draw_id")
        else:
            seen[draw_id] = row
    if errors:
        raise DatasetValidationError("\n".join(errors))
    ordered = sorted(records, key=lambda row: (row["draw_date"], row["draw_id"]))
    return {
        "records": len(records),
        "first_draw": ordered[0]["draw_id"] if ordered else None,
        "last_draw": ordered[-1]["draw_id"] if ordered else None,
        "date_start": ordered[0]["draw_date"] if ordered else None,
        "date_end": ordered[-1]["draw_date"] if ordered else None,
        "unique_draw_ids": len(seen),
    }


def validate_jsonl(path: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                raise DatasetValidationError(f"line {line_no}: blank lines are not allowed")
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise DatasetValidationError(f"line {line_no}: invalid JSON: {exc.msg}") from exc
    return validate_records(records)
