#!/usr/bin/env python3
"""Run one immutable prospective schedule registration or cutoff-finalization pass."""
from __future__ import annotations

import argparse
import json
import sys

from lottery.prospective import ProspectiveLedger
from lottery.prospective_schedule import ScheduleError, load_schedule, run_schedule


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schedule", required=True, help="content-addressed prospective schedule JSON")
    parser.add_argument("--ledger", required=True, help="append-only prospective ledger JSONL")
    parser.add_argument("--mode", choices=("register", "finalize"), required=True)
    args = parser.parse_args()
    try:
        schedule = load_schedule(args.schedule)
        receipt = run_schedule(
            schedule, ProspectiveLedger(args.ledger), mode=args.mode
        )
    except (ScheduleError, OSError) as exc:
        print(f"prospective schedule failed closed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if receipt["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
