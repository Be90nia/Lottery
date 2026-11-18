#!/usr/bin/env python3
"""Audit draw-level legacy promotion flags against official awardType rows.

The comparison is set-based by draw ID. It does not infer ticket-level
eligibility or treat awardType semantics beyond the observed source encoding.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_no}: expected object")
            rows.append(row)
    return rows


def truthy_promotion(value: Any) -> bool:
    # The imported candidate has already normalized this field to JSON bool.
    if not isinstance(value, bool):
        raise ValueError(f"promotion_flag_legacy must be bool, got {value!r}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official", type=Path, required=True,
                        help="Lossless official prize JSONL")
    parser.add_argument("--legacy-draws", type=Path, required=True,
                        help="Legacy draw JSONL")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    official_rows = load_jsonl(args.official)
    legacy_rows = load_jsonl(args.legacy_draws)

    official_draws: set[str] = set()
    award1_draws: set[str] = set()
    identities: Counter[tuple[str, str, str, str]] = Counter()
    identity_draws: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)
    award_types: Counter[str] = Counter()
    promotion_labels: Counter[str] = Counter()

    for row in official_rows:
        draw_id = str(row["draw_id"])
        p = row["raw_prize"]
        official_draws.add(draw_id)
        award_type = p.get("awardType")
        award_type_key = str(award_type)
        award_types[award_type_key] += 1
        key = (
            award_type_key,
            str(p.get("group")),
            str(p.get("sort")),
            str(p.get("prizeLevel", "")),
        )
        identities[key] += 1
        identity_draws[key].add(draw_id)
        if award_type == 1 or award_type == "1":
            award1_draws.add(draw_id)
            promotion_labels[str(p.get("prizeLevel", ""))] += 1

    legacy_true_draws: set[str] = set()
    legacy_all_draws: set[str] = set()
    for row in legacy_rows:
        draw_id = str(row["draw_id"])
        if draw_id in legacy_all_draws:
            raise ValueError(f"duplicate legacy draw ID: {draw_id}")
        legacy_all_draws.add(draw_id)
        if truthy_promotion(row.get("promotion_flag_legacy")):
            legacy_true_draws.add(draw_id)

    overlap = official_draws & legacy_all_draws
    official_only = official_draws - legacy_all_draws
    legacy_only = legacy_all_draws - official_draws
    official_only_award1 = award1_draws - legacy_true_draws
    legacy_only_flags = legacy_true_draws - award1_draws

    report = {
        "schema": "official-legacy-promotion-flag-audit/v1",
        "official_prize_rows": len(official_rows),
        "official_draws": len(official_draws),
        "legacy_draws": len(legacy_rows),
        "legacy_true_promotion_draws": len(legacy_true_draws),
        "official_award_type_1_draws": len(award1_draws),
        "draw_overlap": len(overlap),
        "official_only_draws": sorted(official_only),
        "legacy_only_draws": sorted(legacy_only),
        "award_type_1_without_legacy_flag": sorted(official_only_award1),
        "legacy_flag_without_award_type_1": sorted(legacy_only_flags),
        "promotion_flag_set_exact_match": (
            not official_only_award1 and not legacy_only_flags
        ),
        "award_type_row_counts": dict(sorted(award_types.items())),
        "award_type_1_label_counts": dict(sorted(promotion_labels.items())),
        "source_identity_counts": [
            {
                "awardType": key[0],
                "group": key[1],
                "sort": key[2],
                "prizeLevel": key[3],
                "row_count": count,
                "draw_count": len(identity_draws[key]),
            }
            for key, count in sorted(identities.items())
        ],
        "limitations": [
            "awardType is compared as the observed raw source value; this audit does not independently define its business semantics.",
            "A draw-level promotion flag does not establish ticket-level eligibility or payout entitlement.",
            "Legacy prize rows omit source identity fields, so identity-level prize reconciliation remains unavailable for the legacy side.",
            "The audit compares draw IDs only within the available snapshot and legacy candidate coverage."
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        key: report[key] for key in (
            "official_prize_rows", "official_draws", "legacy_draws",
            "legacy_true_promotion_draws", "official_award_type_1_draws",
            "draw_overlap", "award_type_1_without_legacy_flag",
            "legacy_flag_without_award_type_1", "promotion_flag_set_exact_match",
            "award_type_row_counts", "award_type_1_label_counts"
        )
    }, ensure_ascii=False, indent=2))
    return 0 if report["promotion_flag_set_exact_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
