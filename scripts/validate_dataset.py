#!/usr/bin/env python3
"""Validate the canonical draw JSONL file."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lottery.validate import validate_jsonl  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", nargs="?", type=Path, default=ROOT / "data/processed/draws.jsonl")
    args = parser.parse_args()
    try:
        report = validate_jsonl(args.dataset)
    except (OSError, ValueError) as exc:
        print(f"VALIDATION_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "VALID", **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
