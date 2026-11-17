#!/usr/bin/env python3
"""Fetch official historical Super Lotto draws into raw snapshots and JSONL."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lottery.ingest import fetch_history  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/draws.jsonl")
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw/sporttery")
    args = parser.parse_args()
    result = fetch_history(args.output, args.raw_dir, args.page_size, args.max_pages, args.delay)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
