#!/usr/bin/env python3
"""Build an A2-cross-checked append-only draw candidate and live set-index view."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lottery.jiangsu_draw_candidate import (  # noqa: E402
    JiangsuDrawCandidateError,
    build_jiangsu_draw_candidate,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--inventory-manifest", type=Path, required=True)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--frozen-view", type=Path, required=True)
    parser.add_argument("--frozen-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--live-view-dir", type=Path, required=True)
    parser.add_argument("--code-commit", default=os.environ.get("GITHUB_SHA", ""))
    args = parser.parse_args()
    try:
        receipt = build_jiangsu_draw_candidate(
            args.inventory,
            args.inventory_manifest,
            args.coverage,
            args.ledger,
            args.archive_dir,
            args.frozen_view,
            args.frozen_manifest,
            args.output_dir,
            args.live_view_dir,
            code_commit=args.code_commit,
        )
        receipt_path = args.output_dir / (
            f"jiangsu-draw-candidate-receipt-{receipt['coverage_report_sha256'][:16]}.json"
        )
        rendered = (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        encoded = rendered.encode("utf-8")
        if receipt_path.exists():
            if receipt_path.read_bytes() != encoded:
                raise JiangsuDrawCandidateError(f"immutable candidate receipt conflicts: {receipt_path}")
        else:
            try:
                with receipt_path.open("xb") as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
            except FileExistsError:
                if receipt_path.read_bytes() != encoded:
                    raise JiangsuDrawCandidateError(f"immutable candidate receipt conflicts: {receipt_path}")
        print(json.dumps({
            "status": "jiangsu_a2_candidate_built",
            "verified_overlap_draw_count": receipt["verified_overlap_draw_count"],
            "appended_draw_ids": receipt["appended_draw_ids"],
            "live_set_index_counts": receipt["live_set_index_counts"],
            "candidate_dataset_sha256": receipt["candidate_dataset_sha256"],
            "candidate_path": receipt["candidate_path"],
            "candidate_manifest_path": receipt["candidate_manifest_path"],
            "live_view_path": receipt["live_view_path"],
            "live_view_manifest_path": receipt["live_view_manifest_path"],
            "receipt_path": str(receipt_path),
            "receipt_sha256": receipt["receipt_sha256"],
            "canonical_dataset_modified": receipt["canonical_dataset_modified"],
        }, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, JiangsuDrawCandidateError) as exc:
        print(f"JIANGSU_DRAW_CANDIDATE_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
