#!/usr/bin/env python3
"""Exploratory five-calendar-year frequency diagnostics with global Holm correction."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lottery.baseline import analyze_frequency_baseline, holm_adjust  # noqa: E402
from lottery.validate import validate_jsonl  # noqa: E402


BINS = ((2007, 2011), (2012, 2016), (2017, 2021), (2022, 2026))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--simulations", type=int, default=1999)
    parser.add_argument("--seed", type=int, default=20261118)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        validation = validate_jsonl(args.dataset)
        rows = [json.loads(line) for line in args.dataset.read_text(encoding="utf-8").splitlines()]
        segments = []
        raw_p_values = {}
        for start, end in BINS:
            subset = [row for row in rows if start <= int(row["draw_date"][:4]) <= end]
            if not subset:
                continue
            result = analyze_frequency_baseline(
                subset, simulations=args.simulations, seed=args.seed + start
            )
            result["calendar_year_range"] = [start, end]
            segments.append(result)
            for test_name, p_value in result["monte_carlo_p_values_upper_tail"].items():
                raw_p_values[f"{start}-{end}:{test_name}"] = p_value
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERA_ANALYSIS_FAILED: {exc}", file=sys.stderr)
        return 1

    report = {
        "method": "exploratory fixed five-calendar-year bins; legal-draw Monte Carlo",
        "simulations_per_segment": args.simulations,
        "base_seed": args.seed,
        "familywise_correction": "Holm step-down across all segment × statistic tests in this report",
        "holm_adjusted_p_values": holm_adjust(raw_p_values),
        "dataset_validation": validation,
        "segments": segments,
        "limitations": [
            "Calendar bins are exploratory and were selected after the full-period frequency signal was observed.",
            "Holm correction covers only the tests in this report, not every prior exploratory analysis.",
            "Equipment, ball-set, rule-era, and data-source effects are not modeled here.",
            "A significant frequency deviation is not evidence of manipulation or predictive advantage."
        ]
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
