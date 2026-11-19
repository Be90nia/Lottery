#!/usr/bin/env python3
"""Build an immutable, evidence-bound reported set-index view (not a physical-set model)."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lottery.reported_set_index import (  # noqa: E402
    ReportedSetIndexError,
    build_reported_set_index_view,
    write_reported_set_index_view,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--coverage-json", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        rows, manifest = build_reported_set_index_view(
            args.inventory, args.coverage_json, args.ledger, args.archive_dir
        )
        output, manifest_path = write_reported_set_index_view(rows, manifest, args.output_dir)
        print(json.dumps({
            "status": "reported_set_index_view_built",
            "records": manifest["record_count"],
            "set_index_counts": manifest["set_index_counts"],
            "coverage_report_sha256": manifest["coverage_report_sha256"],
            "output": str(output),
            "manifest": str(manifest_path),
            "training_eligibility": manifest["training_eligibility"],
            "model_scope": manifest["model_scope"],
        }, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, ReportedSetIndexError) as exc:
        print(f"REPORTED_SET_INDEX_VIEW_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
