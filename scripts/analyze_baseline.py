#!/usr/bin/env python3
"""Run reproducible legal-draw Monte Carlo frequency diagnostics on JSONL data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lottery.baseline import analyze_frequency_baseline  # noqa: E402
from lottery.validate import validate_jsonl  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--simulations", type=int, default=999)
    parser.add_argument("--seed", type=int, default=20261118)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        validation = validate_jsonl(args.dataset)
        raw = args.dataset.read_bytes()
        rows = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
        report = analyze_frequency_baseline(rows, simulations=args.simulations, seed=args.seed)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"ANALYSIS_FAILED: {exc}", file=sys.stderr)
        return 1

    report["dataset"] = {
        "path": str(args.dataset),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "validation": validation,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
