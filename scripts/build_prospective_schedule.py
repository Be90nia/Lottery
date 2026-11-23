#!/usr/bin/env python3
"""Build or operate a registry-bound LOT-063 prospective schedule.

Build requires a protected trust-adapter module with verify_target_manifest(value)
and verify_inventory(value) functions. No default/trivial verifier is supplied.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import sys

from lottery.prospective import ProspectiveLedger
from lottery.prospective_registry import (
    RegistryScheduleError,
    _load_canonical,
    assert_registry_unchanged,
    build_registry_schedule,
)
from lottery.prospective_schedule import load_schedule, run_schedule
from lottery.subset_model.artifact import canonicalize
from lottery.subset_model.lifecycle import ChampionLifecycle


def _write_once(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.read_bytes() != raw:
            raise RegistryScheduleError("immutable schedule path already contains different bytes")
        return
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("build", "register", "finalize"), required=True)
    parser.add_argument("--lifecycle-root", required=True)
    parser.add_argument("--schedule", required=True, help="immutable schedule JSON path")
    parser.add_argument("--ledger", help="append-only prospective ledger JSONL path")
    parser.add_argument("--target-manifest", help="content-addressed official target manifest")
    parser.add_argument("--inventory", help="content-addressed official draw/date inventory")
    parser.add_argument("--trust-adapter", help="trusted Python module implementing the two verifier callbacks")
    parser.add_argument("--code-commit", default=os.environ.get("GITHUB_SHA"))
    args = parser.parse_args()

    try:
        lifecycle = ChampionLifecycle(args.lifecycle_root)
        schedule_path = Path(args.schedule)
        if args.mode == "build":
            if not (args.target_manifest and args.inventory and args.trust_adapter and args.code_commit):
                raise RegistryScheduleError("build requires target manifest, inventory, trust adapter and full code commit")
            adapter = importlib.import_module(args.trust_adapter)
            manifest = _load_canonical(args.target_manifest)
            inventory = _load_canonical(args.inventory)
            schedule = build_registry_schedule(
                lifecycle, manifest, inventory,
                now=datetime.now(timezone.utc),
                code_commit=args.code_commit,
                target_manifest_verifier=adapter.verify_target_manifest,
                inventory_verifier=adapter.verify_inventory,
            )
            raw = canonicalize(schedule)
            _write_once(schedule_path, raw)
            result = {"status": "built", "schedule_id": schedule["schedule_id"],
                      "expected_count": len(schedule["expected_forecasts"]),
                      "path": str(schedule_path)}
        else:
            if not args.ledger:
                raise RegistryScheduleError("register/finalize requires --ledger")
            schedule = load_schedule(schedule_path)
            assert_registry_unchanged(lifecycle, schedule)
            receipt = run_schedule(
                schedule, ProspectiveLedger(args.ledger), mode=args.mode,
            )
            result = receipt
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0 if result.get("status") in ("built", "complete") else 2
    except (RegistryScheduleError, OSError, ImportError, AttributeError, ValueError) as exc:
        print(f"prospective registry operation failed closed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
