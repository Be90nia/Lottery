"""Targeted diagnostic for previously incomplete conditional-Poisson fits.

This is a post-outcome exploratory diagnostic only. It cannot authorize
confirmatory inference, promotion, LOT-042 access or production serving.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lottery.backtest import _probabilities
from lottery.subset_model.artifact import canonicalize
from lottery.subset_model import (
    BACK_POPULATION, BACK_SELECTION, FRONT_POPULATION, FRONT_SELECTION,
    ConditionalPoisson,
)

EXPECTED_SNAPSHOT_SHA256 = "9f4cc51b76fd258dd056e0b86f675192d3d9a41c2901f771cab778c65ec2b6aa"
EXPECTED_SNAPSHOT_ROWS = 2949
SOLVER = "conditional_poisson_calibration_lbfgs_strong_wolfe_v2"
TOLERANCE = 1e-8
MAX_ITERATIONS = 5000
HISTORY_SIZE = 10


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _parse_ids(raw: str) -> list[str]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if len(values) != len(set(values)) or any(len(item) != 5 or not item.isdigit() for item in values):
        raise ValueError("target IDs must be unique comma-separated five-digit draw IDs")
    return values


def run(snapshot_path: Path, output_path: Path, front_ids: list[str], back_ids: list[str]) -> dict:
    raw = snapshot_path.read_bytes()
    digest = _sha(raw)
    if digest != EXPECTED_SNAPSHOT_SHA256:
        raise ValueError(f"snapshot SHA-256 mismatch: {digest}")
    rows = [json.loads(line) for line in raw.splitlines()]
    if len(rows) != EXPECTED_SNAPSHOT_ROWS:
        raise ValueError(f"snapshot row count mismatch: {len(rows)}")
    if len({row["draw_id"] for row in rows}) != len(rows):
        raise ValueError("snapshot contains duplicate draw IDs")
    index_by_id = {row["draw_id"]: index for index, row in enumerate(rows)}
    zones = {
        "front": (front_ids, "front_numbers", FRONT_POPULATION, FRONT_SELECTION),
        "back": (back_ids, "back_numbers", BACK_POPULATION, BACK_SELECTION),
    }
    results = {}
    for zone, (target_ids, field, population, selection) in zones.items():
        zone_results = []
        for target_id in target_ids:
            if target_id not in index_by_id:
                raise ValueError(f"target draw {target_id} is absent from the frozen snapshot")
            index = index_by_id[target_id]
            target_row = rows[index]
            training = rows[:index]
            if len(training) < 300 or any(
                row["draw_date"] >= target_row["draw_date"] for row in training
            ):
                raise ValueError(f"training chronology/coverage failed for {zone} {target_id}")
            for baseline in ("expanding", "ewma"):
                marginals = _probabilities(
                    training, field, population, selection,
                    model=baseline, alpha=100.0,
                    half_life=100.0 if baseline == "ewma" else None,
                )
                calibration = ConditionalPoisson.calibrate(
                    marginals, selection,
                    tolerance=TOLERANCE,
                    max_iterations=MAX_ITERATIONS,
                    history_size=HISTORY_SIZE,
                )
                zone_results.append({
                    "target_draw_id": target_id,
                    "target_draw_date": target_row["draw_date"],
                    "training_first_draw_id": training[0]["draw_id"],
                    "training_last_draw_id": training[-1]["draw_id"],
                    "training_row_count": len(training),
                    "training_dates_strictly_before_target": True,
                    "baseline": baseline,
                    "target_marginals_sha256": _sha(canonicalize(list(marginals))),
                    "terminal_status": calibration.terminal_status,
                    "converged": calibration.converged,
                    "iterations": calibration.iterations,
                    "gradient_inf_norm": calibration.gradient_inf_norm,
                    "maximum_absolute_residual": calibration.maximum_absolute_residual,
                    "objective": calibration.objective,
                    "failure_reason": None if calibration.converged else calibration.message,
                })
        results[zone] = zone_results
    body = {
        "schema": "lottery.conditional-poisson-target-diagnostic/v1",
        "experiment_id": "LOT055-CP-STRONG-WOLFE-DIAGNOSTIC-20261120",
        "experiment_class": "exploratory_post_outcome",
        "confirmatory_eligible": False,
        "snapshot_sha256": digest,
        "snapshot_rows": len(rows),
        "solver": SOLVER,
        "tolerance": TOLERANCE,
        "max_iterations": MAX_ITERATIONS,
        "history_size": HISTORY_SIZE,
        "front": results["front"],
        "back": results["back"],
        "all_converged": all(
            row["converged"] for zone_rows in results.values() for row in zone_rows
        ),
        "lot042_accessed": False,
        "production_ready": False,
    }
    body["diagnostic_sha256"] = _sha(canonicalize(body))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("CONDITIONAL_POISSON_TARGET_DIAGNOSTIC=" + json.dumps({
        "diagnostic_sha256": body["diagnostic_sha256"],
        "all_converged": body["all_converged"],
        "front": [{"draw": row["target_draw_id"], "baseline": row["baseline"],
                   "status": row["terminal_status"], "gradient": row["gradient_inf_norm"]}
                  for row in body["front"]],
        "back": [{"draw": row["target_draw_id"], "baseline": row["baseline"],
                  "status": row["terminal_status"], "gradient": row["gradient_inf_norm"]}
                 for row in body["back"]],
    }, sort_keys=True))
    return body


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, default=ROOT / "data/processed/draws-20261118.jsonl")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--front-target-ids", default="10060,21089,22067")
    parser.add_argument("--back-target-ids", default="25135")
    args = parser.parse_args()
    run(args.snapshot, args.output, _parse_ids(args.front_target_ids), _parse_ids(args.back_target_ids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
