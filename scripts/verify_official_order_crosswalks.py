#!/usr/bin/env python3
"""Verify curated official draw-order crosswalks against the legacy candidate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_number}: row must be an object")
        rows.append(row)
    return rows


def verify(candidate_rows: list[dict[str, Any]],
           registry: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    candidate_by_id: dict[str, dict[str, Any]] = {}
    for row in candidate_rows:
        draw_id = str(row.get("draw_id", ""))
        if not draw_id:
            errors.append("candidate row has empty draw_id")
            continue
        if draw_id in candidate_by_id:
            errors.append(f"duplicate candidate draw_id {draw_id}")
        candidate_by_id[draw_id] = row

    records = registry.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("crosswalk registry must contain a non-empty records array")

    seen: set[str] = set()
    compared = 0
    fields = (
        "draw_date",
        "front_numbers",
        "back_numbers",
        "front_draw_order",
        "back_draw_order",
        "equipment_set",
    )
    candidate_fields = {
        "draw_date": "draw_date",
        "front_numbers": "front_numbers",
        "back_numbers": "back_numbers",
        "front_draw_order": "front_draw_order",
        "back_draw_order": "back_draw_order",
        "equipment_set": "equipment_code_legacy",
    }

    for record in records:
        draw_id = str(record.get("draw_id", ""))
        if not draw_id:
            errors.append("crosswalk record has empty draw_id")
            continue
        if draw_id in seen:
            errors.append(f"duplicate crosswalk draw_id {draw_id}")
            continue
        seen.add(draw_id)

        if not str(record.get("source_url", "")).startswith("https://"):
            errors.append(f"{draw_id}: source_url must be HTTPS")
        if record.get("source_capture_status") != "url_transcribed_not_archived":
            errors.append(f"{draw_id}: unexpected source_capture_status")
        if record.get("source_label_order") != "本期出球顺序":
            errors.append(f"{draw_id}: official order label missing")
        if record.get("source_label_equipment") != (
            f"本期使用第{record.get('equipment_set')}套摇奖球"
        ):
            errors.append(f"{draw_id}: official equipment label mismatch")

        candidate = candidate_by_id.get(draw_id)
        if candidate is None:
            errors.append(f"{draw_id}: draw_id absent from candidate dataset")
            continue

        for field in fields:
            candidate_field = candidate_fields[field]
            expected = record.get(field)
            actual = candidate.get(candidate_field)
            if actual != expected:
                errors.append(
                    f"{draw_id}: {candidate_field} mismatch; "
                    f"candidate={actual!r}, official_crosswalk={expected!r}"
                )

        front = record.get("front_numbers")
        back = record.get("back_numbers")
        front_order = record.get("front_draw_order")
        back_order = record.get("back_draw_order")
        if not isinstance(front, list) or sorted(front) != front:
            errors.append(f"{draw_id}: official front numbers are not sorted")
        if not isinstance(back, list) or sorted(back) != back:
            errors.append(f"{draw_id}: official back numbers are not sorted")
        if not isinstance(front_order, list) or sorted(front_order) != sorted(front or []):
            errors.append(f"{draw_id}: official front order is not a permutation")
        if not isinstance(back_order, list) or sorted(back_order) != sorted(back or []):
            errors.append(f"{draw_id}: official back order is not a permutation")
        if record.get("equipment_set") not in (1, 2, 3):
            errors.append(f"{draw_id}: equipment_set must be 1, 2, or 3")

        compared += 1

    return {
        "registry_schema": registry.get("schema"),
        "candidate_draw_count": len(candidate_rows),
        "crosswalk_records": len(records),
        "compared_records": compared,
        "matched_records": len(records) if not errors else None,
        "errors": errors,
        "sample_design": registry.get("sample_design"),
        "source_capture_status": registry.get("source_capture_status"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate",
        type=Path,
        default=Path("data/candidates/legacy_draws.jsonl"),
    )
    parser.add_argument(
        "--crosswalks",
        type=Path,
        default=Path("data/metadata_verification/official_order_crosswalks_20261118.json"),
    )
    args = parser.parse_args()

    registry = json.loads(args.crosswalks.read_text(encoding="utf-8"))
    result = verify(load_jsonl(args.candidate), registry)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
