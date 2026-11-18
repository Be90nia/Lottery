"""Frozen-snapshot exact-subset rolling-origin evaluation runner.

This runner is equipment-blind and does not read LOT-042 holdout data or
ball-set metadata. It is an implementation evaluation, not a promotion tool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path

from lottery.subset_model import (
    BACK_POPULATION,
    BACK_SELECTION,
    FRONT_POPULATION,
    FRONT_SELECTION,
    ExponentialFamily,
    build_uniform_feature_table,
)

EXPECTED_SHA256 = "9f4cc51b76fd258dd056e0b86f675192d3d9a41c2901f771cab778c65ec2b6aa"
EXPECTED_ROWS = 2949
MIN_TRAIN = 300
BOOTSTRAP_REPLICATES = 1000
BOOTSTRAP_BLOCK = 50
BOOTSTRAP_SEED = 20261118


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _moving_block_bootstrap(values: list[float], seed: int) -> dict:
    n = len(values)
    if n < BOOTSTRAP_BLOCK:
        raise ValueError("not enough paired targets for the preregistered block length")
    rng = random.Random(seed)
    means = []
    for _ in range(BOOTSTRAP_REPLICATES):
        sample = []
        while len(sample) < n:
            start = rng.randrange(0, n - BOOTSTRAP_BLOCK + 1)
            sample.extend(values[start:start + BOOTSTRAP_BLOCK])
        means.append(sum(sample[:n]) / n)
    observed = sum(values) / n
    p_value = (1 + sum(value >= 0.0 for value in means)) / (BOOTSTRAP_REPLICATES + 1)
    return {
        "observed_mean_delta_candidate_minus_uniform": observed,
        "ci_95_lower": _percentile(means, 0.025),
        "ci_95_upper": _percentile(means, 0.975),
        "one_sided_bootstrap_p_value": p_value,
        "replicates": BOOTSTRAP_REPLICATES,
        "block_length_draws": BOOTSTRAP_BLOCK,
        "seed": seed,
        "method": "non-circular moving-block bootstrap on chronological paired differences",
    }


def _holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(p_values.items(), key=lambda item: item[1])
    adjusted = {}
    running = 0.0
    count = len(ordered)
    for index, (name, value) in enumerate(ordered):
        running = max(running, min(1.0, (count - index) * value))
        adjusted[name] = running
    return adjusted


def _load_and_validate(path: Path) -> tuple[list[dict], str]:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError(f"snapshot SHA-256 mismatch: expected {EXPECTED_SHA256}, got {digest}")
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]
    if len(rows) != EXPECTED_ROWS:
        raise ValueError(f"snapshot row count mismatch: expected {EXPECTED_ROWS}, got {len(rows)}")
    if rows[0]["draw_id"] != "07001" or rows[MIN_TRAIN]["draw_id"] != "09054":
        raise ValueError("frozen rolling-origin target boundary mismatch")
    if rows[-1]["draw_id"] != "26131":
        raise ValueError("frozen snapshot final draw mismatch")
    previous_id = None
    previous_date = None
    for row in rows:
        draw_id, draw_date = row["draw_id"], row["draw_date"]
        if previous_id is not None and (draw_id <= previous_id or draw_date <= previous_date):
            raise ValueError("draw inventory is not strictly chronological")
        front, back = row["front_numbers"], row["back_numbers"]
        if (len(front) != FRONT_SELECTION or len(set(front)) != FRONT_SELECTION
                or front != sorted(front)
                or any(type(x) is not int or not 1 <= x <= FRONT_POPULATION for x in front)):
            raise ValueError(f"invalid front subset at draw {draw_id}")
        if (len(back) != BACK_SELECTION or len(set(back)) != BACK_SELECTION
                or back != sorted(back)
                or any(type(x) is not int or not 1 <= x <= BACK_POPULATION for x in back)):
            raise ValueError(f"invalid back subset at draw {draw_id}")
        previous_id, previous_date = draw_id, draw_date
    if len({row["draw_id"] for row in rows}) != len(rows):
        raise ValueError("duplicate draw IDs in frozen snapshot")
    return rows, digest


def _evaluate_zone(rows: list[dict], zone: str, m: int, k: int, include_gap: bool, seed: int) -> dict:
    table = build_uniform_feature_table(m, k, include_gap_variance=include_gap)
    model = ExponentialFamily(table)
    observations = [tuple(row[f"{zone}_numbers"]) for row in rows]
    uniform_nll = math.log(math.comb(m, k))
    records = []
    differences = []
    statuses: dict[str, int] = {}

    for target_index in range(MIN_TRAIN, len(rows)):
        training = observations[:target_index]
        target = observations[target_index]
        fit = model.fit(training)
        statuses[fit.terminal_status] = statuses.get(fit.terminal_status, 0) + 1
        record = {
            "target_draw_id": rows[target_index]["draw_id"],
            "training_count": target_index,
            "training_cutoff_draw_id": rows[target_index - 1]["draw_id"],
            "fit_status": fit.terminal_status,
            "iterations": fit.iterations,
            "gradient_infinity_norm": fit.gradient_infinity_norm,
            "candidate_exact_set_nll": None,
            "candidate_minus_uniform_nll": None,
        }
        if fit.converged:
            candidate_nll = -model.log_probability(target, fit.theta)
            delta = candidate_nll - uniform_nll
            record["candidate_exact_set_nll"] = candidate_nll
            record["candidate_minus_uniform_nll"] = delta
            differences.append(delta)
        records.append(record)

    expected_targets = len(rows) - MIN_TRAIN
    scored_targets = len(differences)
    complete = len(records) == expected_targets and scored_targets == expected_targets
    result = {
        "zone": zone,
        "population_size": m,
        "selection_size": k,
        "target_count": expected_targets,
        "scored_target_count": scored_targets,
        "fit_status_counts": statuses,
        "complete_coverage": complete,
        "uniform_exact_set_nll": uniform_nll,
        "candidate_mean_exact_set_nll_scored_only": (
            sum(record["candidate_exact_set_nll"] for record in records
                if record["candidate_exact_set_nll"] is not None) / scored_targets
            if scored_targets else None
        ),
        "candidate_minus_uniform_mean_nll_scored_only": (
            sum(differences) / scored_targets if scored_targets else None
        ),
        "bootstrap": _moving_block_bootstrap(differences, seed) if complete else None,
        "target_records": records,
    }
    return result


def run(snapshot_path: Path, output_path: Path) -> dict:
    rows, digest = _load_and_validate(snapshot_path)
    front = _evaluate_zone(
        rows, "front", FRONT_POPULATION, FRONT_SELECTION, True, BOOTSTRAP_SEED
    )
    back = _evaluate_zone(
        rows, "back", BACK_POPULATION, BACK_SELECTION, False, BOOTSTRAP_SEED + 1
    )
    p_values = {}
    if front["complete_coverage"]:
        p_values["front"] = front["bootstrap"]["one_sided_bootstrap_p_value"]
    if back["complete_coverage"]:
        p_values["back"] = back["bootstrap"]["one_sided_bootstrap_p_value"]
    holm = _holm_adjust(p_values) if len(p_values) == 2 else {}
    for zone in (front, back):
        zone["holm_adjusted_p_value"] = holm.get(zone["zone"])
        zone["co_primary_pass"] = bool(
            zone["complete_coverage"]
            and zone["bootstrap"] is not None
            and zone["bootstrap"]["ci_95_upper"] < 0.0
            and zone["holm_adjusted_p_value"] is not None
            and zone["holm_adjusted_p_value"] < 0.05
        )
    result = {
        "run_type": "LOT-055-equipment-blind-exact-subset-rolling-origin-implementation-evaluation",
        "snapshot_sha256": digest,
        "snapshot_rows": len(rows),
        "snapshot_first_draw": rows[0]["draw_id"],
        "snapshot_last_draw": rows[-1]["draw_id"],
        "first_target_draw": rows[MIN_TRAIN]["draw_id"],
        "last_target_draw": rows[-1]["draw_id"],
        "target_count_per_zone": len(rows) - MIN_TRAIN,
        "minimum_training_rows": MIN_TRAIN,
        "model_family": "regularized_complete_unordered_subset_exponential_family",
        "objective_scale": "mean_nll",
        "regularization_lambda": 1.0,
        "solver": "deterministic_unbounded_lbfgs_armijo_v1",
        "solver_policy_note": "Implementation solver differs from initial L-BFGS-B proposal; this run is diagnostic and not a frozen confirmatory acceptance until solver policy is formally reviewed.",
        "bootstrap": {"replicates": BOOTSTRAP_REPLICATES, "block_length": BOOTSTRAP_BLOCK, "seed": BOOTSTRAP_SEED},
        "holm_adjusted_p_values": holm,
        "front": front,
        "back": back,
        "confirmatory_candidate_pass": bool(front["co_primary_pass"] and back["co_primary_pass"]),
        "production_ready": False,
        "limitations": [
            "equipment-blind pooled model only",
            "no ball-set labels or set-conditioned slots",
            "no LOT-042 holdout access",
            "no Champion promotion or user-facing service",
            "one frozen snapshot and preregistered targets only",
            "solver implementation policy requires review before confirmatory acceptance",
        ],
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    summary = {
        "snapshot_sha256": digest,
        "target_count_per_zone": result["target_count_per_zone"],
        "front": {key: front[key] for key in (
            "scored_target_count", "complete_coverage", "candidate_mean_exact_set_nll_scored_only",
            "uniform_exact_set_nll", "candidate_minus_uniform_mean_nll_scored_only",
            "bootstrap", "holm_adjusted_p_value", "co_primary_pass",
        )},
        "back": {key: back[key] for key in (
            "scored_target_count", "complete_coverage", "candidate_mean_exact_set_nll_scored_only",
            "uniform_exact_set_nll", "candidate_minus_uniform_mean_nll_scored_only",
            "bootstrap", "holm_adjusted_p_value", "co_primary_pass",
        )},
        "confirmatory_candidate_pass": result["confirmatory_candidate_pass"],
        "production_ready": False,
        "output_path": str(output_path),
    }
    print("SUBSET_MODEL_ROLLING_ORIGIN_RESULT=" + json.dumps(summary, sort_keys=True))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.snapshot, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
