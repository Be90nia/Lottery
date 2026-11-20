#!/usr/bin/env python3
"""Build or verify a fail-closed LOT-067 readiness receipt."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lottery.readiness import (  # noqa: E402
    ReadinessError,
    build_readiness_report,
    verify_readiness_report,
    write_readiness_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="build an immutable readiness report")
    build.add_argument("--release-manifest", type=Path, required=True)
    build.add_argument("--gate-results", type=Path, required=True)
    build.add_argument("--evidence-root", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)

    verify = subparsers.add_parser("verify", help="recompute and verify a readiness report")
    verify.add_argument("--report", type=Path, required=True)
    verify.add_argument("--release-manifest", type=Path, required=True)
    verify.add_argument("--gate-results", type=Path, required=True)
    verify.add_argument("--evidence-root", type=Path, required=True)

    args = parser.parse_args()
    try:
        if args.command == "build":
            report = build_readiness_report(
                args.release_manifest, args.gate_results, args.evidence_root
            )
            output = write_readiness_report(report, args.output)
        else:
            report = verify_readiness_report(
                args.report, args.release_manifest, args.gate_results, args.evidence_root
            )
            output = args.report
        print(json.dumps({
            "readiness_state": report["readiness_state"],
            "release_id": report["release_id"],
            "release_manifest_sha256": report["release_manifest_sha256"],
            "gate_statuses": report["gate_statuses"],
            "blocking_reasons": report["blocking_reasons"],
            "report_sha256": report["report_sha256"],
            "output": str(output),
            "activation_performed": False,
            "production_approval": report["production_approval"],
        }, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, ReadinessError) as exc:
        print(f"READINESS_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
