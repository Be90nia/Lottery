#!/usr/bin/env python3
"""Build or operate a registry-bound LOT-063 prospective schedule.

The protected adapter must export verify_target_manifest, verify_inventory,
attest_schedule, and verify_schedule. No permissive verifier is supplied.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile

from lottery.prospective import ProspectiveLedger, ProspectiveLedgerError
from lottery.prospective_registry import (
    RegistryScheduleError,
    _load_canonical,
    assert_registry_unchanged,
    build_registry_schedule,
)
from lottery.prospective_schedule import load_schedule, run_schedule
from lottery.subset_model.artifact import canonicalize
from lottery.subset_model.lifecycle import ChampionLifecycle, LifecycleError


def _write_once(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise RegistryScheduleError("immutable schedule path already contains different bytes")
        if hasattr(os, "O_DIRECTORY"):
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("build", "register", "finalize"), required=True)
    parser.add_argument("--lifecycle-root", required=True)
    parser.add_argument("--schedule", required=True, help="immutable schedule JSON path")
    parser.add_argument("--ledger", help="append-only prospective ledger JSONL path")
    parser.add_argument("--target-manifest", help="content-addressed official target manifest")
    parser.add_argument("--inventory", help="content-addressed official draw/date inventory")
    parser.add_argument("--trust-adapter", help="protected Python module with source and schedule verifiers")
    parser.add_argument("--code-commit", default=os.environ.get("GITHUB_SHA"))
    args = parser.parse_args()

    try:
        lifecycle = ChampionLifecycle(args.lifecycle_root)
        schedule_path = Path(args.schedule)
        if not args.trust_adapter:
            raise RegistryScheduleError("all operations require the protected schedule trust adapter")
        adapter = importlib.import_module(args.trust_adapter)
        if args.mode == "build":
            if not (args.target_manifest and args.inventory and args.code_commit):
                raise RegistryScheduleError("build requires target manifest, inventory and full code commit")
            manifest = _load_canonical(args.target_manifest)
            inventory = _load_canonical(args.inventory)
            schedule = build_registry_schedule(
                lifecycle, manifest, inventory,
                now=datetime.now(timezone.utc),
                code_commit=args.code_commit,
                target_manifest_verifier=adapter.verify_target_manifest,
                inventory_verifier=adapter.verify_inventory,
                schedule_attestor=adapter.attest_schedule,
                schedule_verifier=adapter.verify_schedule,
            )
            _write_once(schedule_path, canonicalize(schedule))
            result = {
                "status": "built",
                "schedule_id": schedule["schedule_id"],
                "expected_count": len(schedule["expected_forecasts"]),
                "path": str(schedule_path),
            }
        else:
            if not args.ledger:
                raise RegistryScheduleError("register/finalize requires --ledger")
            schedule = load_schedule(schedule_path)
            assert_registry_unchanged(
                lifecycle, schedule, schedule_verifier=adapter.verify_schedule
            )
            result = run_schedule(schedule, ProspectiveLedger(args.ledger), mode=args.mode)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0 if result.get("status") in ("built", "complete") else 2
    except (
        RegistryScheduleError, LifecycleError, ProspectiveLedgerError,
        OSError, ImportError, AttributeError, ValueError,
    ) as exc:
        print(f"prospective registry operation failed closed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
