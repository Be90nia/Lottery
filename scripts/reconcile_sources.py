#!/usr/bin/env python3
"""Reconcile the legacy JSONL candidate against the preserved independent CSV."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lottery.reconcile import parse_external_csv, reconcile_draw_sets  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy", type=Path, default=ROOT / "data/candidates/legacy_draws.jsonl")
    parser.add_argument("--external", type=Path, default=ROOT / "data/candidates/pickwise_dlt.csv")
    args = parser.parse_args()
    try:
        legacy_bytes = args.legacy.read_bytes()
        external_bytes = args.external.read_bytes()
        legacy_rows = [json.loads(line) for line in legacy_bytes.decode("utf-8").splitlines()]
        external_text = external_bytes.decode("utf-8-sig")
        external_rows = parse_external_csv(external_text)
        report = reconcile_draw_sets(legacy_rows, external_rows)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"RECONCILIATION_FAILED: {exc}", file=sys.stderr)
        return 1

    report["provenance"] = {
        "legacy_sha256": hashlib.sha256(legacy_bytes).hexdigest(),
        "external_sha256": hashlib.sha256(external_bytes).hexdigest(),
        "external_source_repository": "https://github.com/cs4745/PickWise",
        "external_source_commit": "2f6f125e8f5f3c23460ae4ba9d60a73531c46dc9",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["mismatch_count"] or report["legacy_only_ids"] or report["overlap_records"] == 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
