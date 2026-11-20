#!/usr/bin/env python3
"""Run the preregistered reported-index rolling-origin pilot; never promotes a model."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lottery.reported_index_pilot import (  # noqa: E402
    ReportedIndexPilotError,
    build_reported_index_pilot,
    write_reported_index_pilot,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--code-commit", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = build_reported_index_pilot(
            args.view, args.manifest, code_commit=args.code_commit
        )
        output = write_reported_index_pilot(report, args.output_dir)
        print(json.dumps({
            "status": report["reported_index_pilot_status"],
            "decision": report["decision"],
            "comparison_count": report["inference"]["comparison_count"],
            "target_counts": report["target_counts"],
            "significant_index_specific_improvements": report["significant_index_specific_improvements"],
            "report_sha256": report["report_sha256"],
            "output": str(output),
            "physical_model_eligibility": report["physical_model_eligibility"],
            "predictive_efficacy_claim": report["predictive_efficacy_claim"],
        }, ensure_ascii=False, sort_keys=True))
        return 0 if report["reported_index_pilot_status"] == "research_only_complete" else 1
    except (OSError, ValueError, ReportedIndexPilotError) as exc:
        print(f"REPORTED_INDEX_PILOT_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
