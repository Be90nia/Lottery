#!/usr/bin/env python3
"""Evaluate LOT-067 release receipts without enabling production."""
from __future__ import annotations

import argparse
import json
import sys

from lottery.readiness import ReadinessError, evaluate_readiness, load_json, write_readiness_report
from lottery.readiness_receipts import ReceiptVerificationError, verify_receipt_set


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--policy", help="versioned readiness-policy-v1.json (required for structural v1 mode)")
    parser.add_argument(
        "--typed-receipts", action="store_true",
        help="verify typed LOT-074 receipts; reports completeness only and never readiness authorization",
    )
    parser.add_argument("--gate-results", required=True)
    parser.add_argument("--fault-results", required=True)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        manifest = load_json(args.manifest)
        gates = load_json(args.gate_results)
        faults = load_json(args.fault_results)
        if args.typed_receipts:
            report = verify_receipt_set(manifest, gates, faults, args.evidence_root)
        else:
            if not args.policy:
                parser.error("--policy is required unless --typed-receipts is selected")
            policy = load_json(args.policy)
            report = evaluate_readiness(
                manifest, gates, faults, args.evidence_root, policy=policy
            )
        write_readiness_report(report, args.output)
    except (ReadinessError, ReceiptVerificationError, OSError) as exc:
        print(f"readiness evaluation failed closed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if args.typed_receipts:
        return 0 if report["receipt_completeness"] == "COMPLETE" else 2
    return 0 if report["readiness"] in ("READY_FOR_OFFLINE_VALIDATION", "READY_FOR_SHADOW") else 2


if __name__ == "__main__":
    raise SystemExit(main())
