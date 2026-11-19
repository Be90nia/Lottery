#!/usr/bin/env python3
"""Generate live three-index candidates from a frozen pilot and A2-verified latest view."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lottery.live_reported_index_mvp import (  # noqa: E402
    LiveReportedIndexMVPError,
    build_live_reported_index_mvp,
    write_live_reported_index_mvp,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen-view", type=Path, required=True)
    parser.add_argument("--frozen-manifest", type=Path, required=True)
    parser.add_argument("--live-view", type=Path, required=True)
    parser.add_argument("--live-manifest", type=Path, required=True)
    parser.add_argument("--candidate-dataset", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--pilot-report", type=Path, required=True)
    parser.add_argument("--tickets-per-strategy", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20261119)
    parser.add_argument("--alpha", type=float, default=100.0)
    parser.add_argument("--half-life", type=float, default=100.0)
    parser.add_argument("--code-commit", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = build_live_reported_index_mvp(
            args.frozen_view,
            args.frozen_manifest,
            args.live_view,
            args.live_manifest,
            args.candidate_dataset,
            args.candidate_manifest,
            args.pilot_report,
            tickets_per_strategy=args.tickets_per_strategy,
            seed=args.seed,
            alpha=args.alpha,
            half_life=args.half_life,
            code_commit=args.code_commit,
        )
        output = write_live_reported_index_mvp(report, args.output_dir)
        print(json.dumps({
            "status": "live_reported_index_candidates_built",
            "total_tickets": report["total_tickets"],
            "live_set_index_counts": report["live_set_index_counts"],
            "appended_draw_ids": report["appended_draw_ids"],
            "latest_draw_id": report["latest_draw_id"],
            "pilot_decision": report["pilot_decision"],
            "predictive_efficacy_claim": report["predictive_efficacy_claim"],
            "physical_model_eligibility": report["physical_model_eligibility"],
            "candidate_dataset_sha256": report["candidate_dataset_sha256"],
            "report_sha256": report["report_sha256"],
            "output": str(output),
        }, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, LiveReportedIndexMVPError) as exc:
        print(f"LIVE_REPORTED_INDEX_MVP_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
