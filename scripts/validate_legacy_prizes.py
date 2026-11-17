#!/usr/bin/env python3
"""Audit imported legacy prize rows without assuming every row is amount × count."""
import argparse
import glob
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lottery.prizes import audit_prize_rows  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "data/candidates")
    args = parser.parse_args()
    paths = sorted(args.directory.glob("legacy_prizes_part_*.jsonl"))
    if not paths:
        print("No legacy prize candidate files found", file=sys.stderr)
        return 2
    def rows():
        for path in paths:
            with path.open(encoding="utf-8") as handle:
                for line_no, line in enumerate(handle, 1):
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ValueError(f"{path}:{line_no}: invalid JSON") from exc
    try:
        report = audit_prize_rows(rows())
    except (OSError, ValueError) as exc:
        print(f"PRIZE_AUDIT_FAILED: {exc}", file=sys.stderr)
        return 1
    report["files"] = [path.name for path in paths]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
