#!/usr/bin/env python3
"""Compare an official API sample with the imported legacy candidate."""
import argparse
import json
from pathlib import Path
import sys


def load_jsonl(path: Path):
    records = {}
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            key = row["draw_id"]
            if key in records:
                raise ValueError(f"{path}:{line_no}: duplicate draw_id {key}")
            records[key] = row
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("official_sample", type=Path)
    args = parser.parse_args()
    candidate = load_jsonl(args.candidate)
    official = load_jsonl(args.official_sample)
    overlap = sorted(set(candidate) & set(official))
    mismatches = []
    for draw_id in overlap:
        old, new = candidate[draw_id], official[draw_id]
        fields = {
            "draw_date": (old.get("draw_date"), new.get("draw_date")),
            "front_numbers": (old.get("front_numbers"), new.get("front_numbers")),
            "back_numbers": (old.get("back_numbers"), new.get("back_numbers")),
        }
        for field, values in fields.items():
            if values[0] != values[1]:
                mismatches.append({"draw_id": draw_id, "field": field, "candidate": values[0], "official": values[1]})
    report = {
        "candidate_records": len(candidate),
        "official_sample_records": len(official),
        "overlap_records": len(overlap),
        "matching_records": len(overlap) - len({x["draw_id"] for x in mismatches}),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:20],
        "official_sample_first": min(official) if official else None,
        "official_sample_last": max(official) if official else None,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not official:
        return 2
    if not overlap:
        print("WARNING: no overlap; candidate cannot yet be reconciled against this sample", file=sys.stderr)
        return 3
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
