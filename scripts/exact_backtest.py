#!/usr/bin/env python3
"""Run the frozen exact-set rolling-origin research evaluation.

This command is intentionally explicit: it never defaults to the unverified
legacy candidate data, and it refuses mismatched snapshot, target manifest,
or dependency-lock bytes before fitting.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys

from lottery.canonical_artifact import attach_artifact_id, canonicalize
from lottery.exact_backtest import (
    evaluate_rolling_origin,
    verify_frozen_snapshot,
    verify_target_manifest,
)
from lottery.subset_probability import (
    aggregate_feature_cells,
    make_exponential_factory,
    make_weighted_baseline_factory,
)


def _sha256(path: Path) -> tuple[bytes, str]:
    raw = path.read_bytes()
    return raw, hashlib.sha256(raw).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--snapshot-sha256", required=True)
    parser.add_argument("--target-manifest", type=Path, required=True)
    parser.add_argument("--target-manifest-sha256", required=True)
    parser.add_argument("--dependency-lock", type=Path, required=True)
    parser.add_argument("--dependency-lock-sha256", required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--code-revision", required=True)
    parser.add_argument("--bootstrap-seed", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    try:
        snapshot_raw, snapshot_hash = _sha256(args.snapshot)
        target_raw, target_hash = _sha256(args.target_manifest)
        lock_raw, lock_hash = _sha256(args.dependency_lock)
        if snapshot_hash != args.snapshot_sha256:
            raise ValueError("snapshot SHA-256 does not match the preregistered digest")
        if target_hash != args.target_manifest_sha256:
            raise ValueError("target manifest SHA-256 does not match the preregistered digest")
        if lock_hash != args.dependency_lock_sha256:
            raise ValueError("dependency lock SHA-256 does not match the supplied digest")
        lock_text = lock_raw.decode("utf-8")
        scipy_version = importlib.metadata.version("scipy")
        if f"scipy=={scipy_version}" not in lock_text:
            raise ValueError("installed SciPy version is not pinned by the verified dependency lock")

        targets = verify_target_manifest(target_raw, expected_sha256=target_hash)
        records = verify_frozen_snapshot(
            snapshot_raw, expected_sha256=snapshot_hash, expected_row_count=2949,
            expected_target_ids=targets, min_train=300,
        )
        if len(targets) != 2649 or targets[0] != "09054" or targets[-1] != "26131":
            raise ValueError("target manifest differs from frozen LOT-055 target range")

        front_cells = aggregate_feature_cells(35, 5)
        back_cells = aggregate_feature_cells(12, 2)
        factories = {
            "expanding_conditional_poisson": make_weighted_baseline_factory("expanding"),
            "ewma_conditional_poisson": make_weighted_baseline_factory("ewma"),
            "complete_set_exponential": make_exponential_factory(front_cells, back_cells),
        }
        report = evaluate_rolling_origin(
            records, target_ids=targets, model_factories=factories, min_train=300,
            snapshot_sha256=snapshot_hash, bootstrap_seed=args.bootstrap_seed,
            bootstrap_replicates=1000, bootstrap_block_length=50,
        )
        manifest = attach_artifact_id({
            "schema": "lottery.exact-set-evaluation-run/v1",
            "experiment_id": args.experiment_id,
            "code_revision": args.code_revision,
            "snapshot_sha256": snapshot_hash,
            "target_manifest_sha256": target_hash,
            "dependency_lock_sha256": lock_hash,
            "python_version": platform.python_version(),
            "scipy_version": scipy_version,
            "target_count": len(targets),
            "minimum_training_rows": 300,
            "bootstrap": {"method": "non_circular_paired_moving_block_percentile",
                          "replicates": 1000, "block_length": 50,
                          "seed": args.bootstrap_seed},
            "model_ids": sorted(factories),
            "confirmatory_gate": "BLOCKED",
            "confirmatory_blocker": (
                "The exact one-sided p-value construction and the complete Holm "
                "hypothesis family must be frozen in the preregistration before "
                "confirmatory claims are permitted."
            ),
        })
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "run-manifest.jcs.json").write_bytes(canonicalize(manifest) + b"\n")
        with (args.output_dir / "target-records.jsonl").open("w", encoding="utf-8") as handle:
            for row in report["records"]:
                handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False,
                                        sort_keys=True, separators=(",", ":")) + "\n")
        (args.output_dir / "summary.json").write_text(
            json.dumps(report["summary"], ensure_ascii=False, allow_nan=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({
            "status": "DESCRIPTIVE_RUN_COMPLETE",
            "confirmatory_gate": "BLOCKED",
            "target_count": report["target_count"],
            "terminal_record_count": report["terminal_record_count"],
            "output_dir": str(args.output_dir),
            "run_manifest_artifact_id": manifest["artifact_id"],
        }, ensure_ascii=False, indent=2))
        return 0
    except (OSError, UnicodeDecodeError, ValueError, KeyError, ImportError,
            importlib.metadata.PackageNotFoundError) as exc:
        print(f"EXACT_BACKTEST_BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
