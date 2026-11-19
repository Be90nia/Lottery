#!/usr/bin/env python3
"""Generate all exploratory candidate lanes for reported set indices 1, 2, and 3."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lottery.reported_index_mvp import (  # noqa: E402
    ReportedIndexMVPError,
    build_reported_index_mvp,
    write_reported_index_mvp,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", type=Path, required=True)
    parser.add_argument("--view-manifest", type=Path, required=True)
    parser.add_argument("--pilot-report", type=Path, required=True)
    parser.add_argument("--tickets-per-strategy", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20261119)
    parser.add_argument("--alpha", type=float, default=100.0)
    parser.add_argument("--half-life", type=float, default=100.0)
    parser.add_argument("--code-commit", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = build_reported_index_mvp(
            args.view,
            args.view_manifest,
            args.pilot_report,
            tickets_per_strategy=args.tickets_per_strategy,
            seed=args.seed,
            alpha=args.alpha,
            half_life=args.half_life,
            code_commit=args.code_commit,
        )
        output = write_reported_index_mvp(report, args.output_dir)
        print(json.dumps({
            "status": "reported_index_candidates_built",
            "total_tickets": report["total_tickets"],
            "tickets_per_strategy_per_index": report["tickets_per_strategy_per_index"],
            "per_index_training_counts": {
                key: value["training_draw_count"]
                for key, value in report["index_batches"].items()
            },
            "pilot_decision": report["pilot_decision"],
            "predictive_efficacy_claim": report["predictive_efficacy_claim"],
            "physical_model_eligibility": report["physical_model_eligibility"],
            "report_sha256": report["report_sha256"],
            "output": str(output),
        }, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, ReportedIndexMVPError) as exc:
        print(f"REPORTED_INDEX_MVP_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
