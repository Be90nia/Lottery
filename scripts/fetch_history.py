#!/usr/bin/env python3
"""Fetch official historical Super Lotto draws into raw snapshots and JSONL."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lottery.ingest import fetch_history, ingest_snapshot_directory  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/draws.jsonl")
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw/sporttery")
    parser.add_argument("--snapshots-dir", type=Path, help="Import existing raw JSON response snapshots without network access")
    parser.add_argument("--require-manifests", action="store_true", help="Reject snapshots without matching sidecar manifests")
    args = parser.parse_args()
    if args.snapshots_dir:
        result = ingest_snapshot_directory(args.snapshots_dir, args.output, args.require_manifests)
    else:
        if args.require_manifests:
            parser.error("--require-manifests requires --snapshots-dir")
        result = fetch_history(args.output, args.raw_dir, args.page_size, args.max_pages, args.delay)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
