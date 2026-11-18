"""Cross-check legacy draw candidates against an independent CSV snapshot."""
from __future__ import annotations

import csv
from io import StringIO
from typing import Any, Iterable


class ReconciliationError(ValueError):
    pass


def parse_external_csv(content: str) -> dict[str, dict[str, Any]]:
    reader = csv.DictReader(StringIO(content.lstrip("\ufeff")))
    required = {"issue", "date", "front", "back"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ReconciliationError("external CSV is missing required columns")
    records: dict[str, dict[str, Any]] = {}
    for line_no, row in enumerate(reader, start=2):
        draw_id = (row.get("issue") or "").strip()
        if not draw_id:
            raise ReconciliationError(f"line {line_no}: missing issue")
        if draw_id in records:
            raise ReconciliationError(f"line {line_no}: duplicate issue {draw_id}")
        try:
            front = sorted(int(x) for x in row["front"].split())
            back = sorted(int(x) for x in row["back"].split())
        except (TypeError, ValueError) as exc:
            raise ReconciliationError(f"line {line_no}: invalid number field") from exc
        if len(front) != 5 or len(set(front)) != 5 or any(x < 1 or x > 35 for x in front):
            raise ReconciliationError(f"line {line_no}: invalid front numbers for {draw_id}")
        if len(back) != 2 or len(set(back)) != 2 or any(x < 1 or x > 12 for x in back):
            raise ReconciliationError(f"line {line_no}: invalid back numbers for {draw_id}")
        records[draw_id] = {
            "draw_date": (row.get("date") or "").strip(),
            "front_numbers": front,
            "back_numbers": back,
        }
    return records


def reconcile_draw_sets(
    legacy_rows: Iterable[dict[str, Any]],
    external_rows: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    legacy: dict[str, dict[str, Any]] = {}
    for row in legacy_rows:
        draw_id = row["draw_id"]
        if draw_id in legacy:
            raise ReconciliationError(f"duplicate legacy draw_id {draw_id}")
        legacy[draw_id] = row

    overlap = sorted(set(legacy) & set(external_rows))
    mismatches = []
    for draw_id in overlap:
        old, new = legacy[draw_id], external_rows[draw_id]
        for field in ("draw_date", "front_numbers", "back_numbers"):
            if old.get(field) != new.get(field):
                mismatches.append({
                    "draw_id": draw_id,
                    "field": field,
                    "legacy": old.get(field),
                    "external": new.get(field),
                })
    legacy_only = sorted(set(legacy) - set(external_rows))
    external_only = sorted(set(external_rows) - set(legacy))
    return {
        "legacy_records": len(legacy),
        "external_records": len(external_rows),
        "overlap_records": len(overlap),
        "exact_matching_records": len(overlap) - len({x["draw_id"] for x in mismatches}),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "legacy_only_ids": legacy_only,
        "external_only_count": len(external_only),
        "external_only_oldest_ids": external_only[:10],
        "external_only_newest_ids": external_only[-10:],
    }
