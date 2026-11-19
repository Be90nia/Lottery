"""Frozen-snapshot exact-subset rolling-origin evaluation runner.

This runner is equipment-blind and does not read LOT-042 holdout data or
ball-set metadata. It is an implementation evaluation, not a promotion tool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import scipy
from pathlib import Path

from lottery.backtest import _probabilities
from lottery.subset_model import (
    BACK_POPULATION,
    BACK_SELECTION,
    FRONT_POPULATION,
    FRONT_SELECTION,
    ExponentialFamily,
    ConditionalPoisson,
    build_uniform_feature_table,
)

EXPECTED_SHA256 = "9f4cc51b76fd258dd056e0b86f675192d3d9a41c2901f771cab778c65ec2b6aa"
EXPECTED_ROWS = 2949
MIN_TRAIN = 300
BOOTSTRAP_REPLICATES = 1000
BOOTSTRAP_BLOCK = 50
BOOTSTRAP_SEED = 20261118
CANDIDATE_MAX_ITERATIONS = 5000
CANDIDATE_GRADIENT_TOLERANCE = 1e-8


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
    # Impose the one-sided null mean(delta)=0 before resampling. Resampling
    # uncentered bootstrap means and treating their lower tail as a p-value
    # would not be a valid null test.
    null_centered = [value - observed for value in values]
    null_rng = random.Random(seed ^ 0x5A17C0DE)
    null_means = []
    for _ in range(BOOTSTRAP_REPLICATES):
        sample = []
        while len(sample) < n:
            start = null_rng.randrange(0, n - BOOTSTRAP_BLOCK + 1)
            sample.extend(null_centered[start:start + BOOTSTRAP_BLOCK])
        null_means.append(sum(sample[:n]) / n)
    lower_tail = sum(value <= observed for value in null_means)
    one_sided_p = (lower_tail + 1) / (BOOTSTRAP_REPLICATES + 1)
    return {
        "observed_mean_delta_candidate_minus_reference": observed,
        "ci_95_lower": _percentile(means, 0.025),
        "ci_95_upper": _percentile(means, 0.975),
        "one_sided_null_centered_p_value": one_sided_p,
        "replicates": BOOTSTRAP_REPLICATES,
        "block_length_draws": BOOTSTRAP_BLOCK,
        "seed": seed,
        "method": "paired non-circular moving-block bootstrap; null-centered one-sided mean test",
        "null_centering": "subtract observed paired mean before block resampling",
    }


def _holm_adjust(p_values: dict[str, float | None], family_size: int = 6) -> dict[str, float | None]:
    """Holm step-down adjusted p-values for the frozen six-comparison family."""
    if len(p_values) != family_size or any(
        type(value) not in (int, float) or not math.isfinite(value) or not 0.0 <= value <= 1.0
        for value in p_values.values()
    ):
        return {key: None for key in p_values}
    ordered = sorted(p_values.items(), key=lambda item: item[1])
    adjusted: dict[str, float] = {}
    running_max = 0.0
    for rank, (key, value) in enumerate(ordered):
        candidate = min(1.0, (family_size - rank) * value)
        running_max = max(running_max, candidate)
        adjusted[key] = running_max
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



def _checkpoint_record_hash(record: dict) -> str:
    body = {key: value for key, value in record.items() if key != "record_sha256"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_checkpoint_record(record: dict, *, row: dict, training_count: int,
                                uniform_nll: float) -> None:
    expected_record_keys = {
        "record_type", "target_draw_id", "training_count", "training_cutoff_draw_id",
        "fit_statuses", "exact_set_nll", "candidate_iterations",
        "candidate_gradient_infinity_norm", "record_sha256",
    }
    if (not isinstance(record, dict) or set(record) != expected_record_keys
            or record.get("record_type") != "target"):
        raise ValueError("checkpoint target record has invalid shape")
    supplied_hash = record.get("record_sha256")
    if not isinstance(supplied_hash, str) or supplied_hash != _checkpoint_record_hash(record):
        raise ValueError("checkpoint target record SHA-256 mismatch")
    if (type(record.get("candidate_iterations")) is not int
            or not 0 <= record["candidate_iterations"] <= CANDIDATE_MAX_ITERATIONS):
        raise ValueError("checkpoint candidate iteration count is invalid")
    gradient = record.get("candidate_gradient_infinity_norm")
    if type(gradient) not in (int, float) or not math.isfinite(gradient) or gradient < 0:
        raise ValueError("checkpoint candidate gradient diagnostic is invalid")
    expected_statuses = {"candidate", "expanding", "ewma"}
    expected_scores = {"uniform", "expanding", "ewma", "exponential_family"}
    if not isinstance(record.get("fit_statuses"), dict) or set(record["fit_statuses"]) != expected_statuses:
        raise ValueError("checkpoint fit_statuses schema mismatch")
    if not isinstance(record.get("exact_set_nll"), dict) or set(record["exact_set_nll"]) != expected_scores:
        raise ValueError("checkpoint exact_set_nll schema mismatch")
    if (record.get("target_draw_id") != row["draw_id"]
            or record.get("training_count") != training_count):
        raise ValueError("checkpoint target order/training count mismatch")
    if not isinstance(record.get("training_cutoff_draw_id"), str) or not record["training_cutoff_draw_id"]:
        raise ValueError("checkpoint training cutoff is missing")
    if any(not isinstance(status, str) or not status for status in record["fit_statuses"].values()):
        raise ValueError("checkpoint fit status must be a non-empty string")
    if (record["fit_statuses"]["candidate"] == "converged"
            and gradient > CANDIDATE_GRADIENT_TOLERANCE):
        raise ValueError("checkpoint candidate gradient exceeds the convergence tolerance")
    scores = record["exact_set_nll"]
    if type(scores["uniform"]) not in (int, float) or not math.isfinite(scores["uniform"]):
        raise ValueError("checkpoint uniform NLL must be finite")
    if abs(scores["uniform"] - uniform_nll) > 1e-10:
        raise ValueError("checkpoint uniform NLL does not match legal support")
    for status_key, score_key in (
        ("candidate", "exponential_family"),
        ("expanding", "expanding"),
        ("ewma", "ewma"),
    ):
        score = scores[score_key]
        if record["fit_statuses"][status_key] == "converged":
            if type(score) not in (int, float) or not math.isfinite(score) or score < -1e-10:
                raise ValueError(f"checkpoint {score_key} NLL invalid for converged fit")
        elif score is not None:
            raise ValueError(f"checkpoint {score_key} score must be null when fit did not converge")


def _evaluate_zone(rows: list[dict], zone: str, m: int, k: int, include_gap: bool,
                   seed: int, checkpoint_path: Path, snapshot_digest: str) -> dict:
    table = build_uniform_feature_table(m, k, include_gap_variance=include_gap)
    model = ExponentialFamily(table)
    field = f"{zone}_numbers"
    observations = [tuple(row[field]) for row in rows]
    uniform_nll = math.log(math.comb(m, k))
    expected = len(rows) - MIN_TRAIN
    header = {
        "record_type": "header", "schema": "lot-055-checkpoint-v2",
        "snapshot_sha256": snapshot_digest, "code_commit": os.environ.get("RESEARCH_CODE_COMMIT", os.environ.get("GITHUB_SHA", "local")),
        "zone": zone,
        "minimum_training_rows": MIN_TRAIN, "first_target": rows[MIN_TRAIN]["draw_id"],
        "last_target": rows[-1]["draw_id"], "models": ["uniform", "expanding", "ewma", "exponential_family"],
        "alpha": 100.0, "ewma_half_life": 100.0,
    }
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    records = []
    if checkpoint_path.exists():
        lines = checkpoint_path.read_text(encoding="utf-8").splitlines()
        if not lines or json.loads(lines[0]) != header:
            raise ValueError(f"checkpoint header mismatch: {checkpoint_path}")
        if len(lines) - 1 > expected:
            raise ValueError(f"checkpoint has too many records: {checkpoint_path}")
        for offset, line in enumerate(lines[1:]):
            record = json.loads(line)
            idx = MIN_TRAIN + offset
            _validate_checkpoint_record(
                record, row=rows[idx], training_count=idx,
                uniform_nll=uniform_nll,
            )
            if record.get("training_cutoff_draw_id") != rows[idx - 1]["draw_id"]:
                raise ValueError(f"checkpoint cutoff mismatch at target index {idx}")
            records.append(record)
    else:
        with checkpoint_path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(header, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    status_counts = {name: {} for name in ("candidate", "expanding", "ewma")}
    def count_status(record):
        for name, status in record["fit_statuses"].items():
            bucket = status_counts[name]
            bucket[status] = bucket.get(status, 0) + 1
    for record in records:
        count_status(record)

    with checkpoint_path.open("a", encoding="utf-8") as checkpoint:
        for idx in range(MIN_TRAIN + len(records), len(rows)):
            training = rows[:idx]
            target = observations[idx]
            fit = model.fit(
                observations[:idx],
                max_iterations=CANDIDATE_MAX_ITERATIONS,
                gradient_tolerance=CANDIDATE_GRADIENT_TOLERANCE,
            )
            statuses = {"candidate": fit.terminal_status}
            scores = {"uniform": uniform_nll}
            candidate = -model.log_probability(target, fit.theta) if fit.converged else None
            for baseline in ("expanding", "ewma"):
                try:
                    marginals = _probabilities(training, field, m, k, model=baseline,
                                               alpha=100.0, half_life=100.0)
                    calibration = ConditionalPoisson.calibrate(marginals, k)
                    statuses[baseline] = calibration.terminal_status
                    scores[baseline] = (-ConditionalPoisson(
                        calibration.centered_log_weights, k
                    ).log_probability(target)) if calibration.converged else None
                except (ValueError, ArithmeticError, OverflowError) as exc:
                    statuses[baseline] = "failed:" + type(exc).__name__
                    scores[baseline] = None
            scores["exponential_family"] = candidate
            record = {
                "record_type": "target", "target_draw_id": rows[idx]["draw_id"],
                "training_count": idx, "training_cutoff_draw_id": rows[idx - 1]["draw_id"],
                "fit_statuses": statuses, "exact_set_nll": scores,
                "candidate_iterations": fit.iterations,
                "candidate_gradient_infinity_norm": fit.gradient_infinity_norm,
            }
            record["record_sha256"] = _checkpoint_record_hash(record)
            checkpoint.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
            checkpoint.flush()
            os.fsync(checkpoint.fileno())
            _validate_checkpoint_record(
                record, row=rows[idx], training_count=idx,
                uniform_nll=uniform_nll,
            )
            records.append(record)
            count_status(record)
            completed = idx - MIN_TRAIN + 1
            if completed % 50 == 0 or completed == expected:
                print(f"EXACT_SUBSET_PROGRESS zone={zone} completed={completed}/{expected}", flush=True)

    references = ("uniform", "expanding", "ewma")
    deltas = {name: [] for name in references}
    scored = {name: 0 for name in ("uniform", "expanding", "ewma", "exponential_family")}
    sums = {name: 0.0 for name in scored}
    for record in records:
        for name, value in record["exact_set_nll"].items():
            if value is not None:
                scored[name] += 1
                sums[name] += value
        candidate = record["exact_set_nll"]["exponential_family"]
        if candidate is not None:
            for name in references:
                baseline = record["exact_set_nll"][name]
                if baseline is not None:
                    deltas[name].append(candidate - baseline)
    complete = (len(records) == expected and all(v == expected for v in scored.values())
                and all(len(v) == expected for v in deltas.values()))
    comparisons = {
        name: _moving_block_bootstrap(values, seed + index)
        if len(values) == expected else None
        for index, (name, values) in enumerate(deltas.items())
    }
    return {
        "zone": zone, "population_size": m, "selection_size": k,
        "target_count": expected, "scored_target_counts": scored,
        "fit_status_counts": status_counts, "complete_coverage": complete,
        "mean_exact_set_nll": {name: sums[name] / scored[name] if scored[name] else None for name in sums},
        "paired_candidate_minus_baseline": comparisons,
        "target_records": records, "checkpoint_path": str(checkpoint_path),
    }


def run(snapshot_path: Path, output_path: Path, checkpoint_dir: Path | None = None) -> dict:
    rows, digest = _load_and_validate(snapshot_path)
    checkpoint_dir = checkpoint_dir or output_path.parent / "subset-model-checkpoints"
    front = _evaluate_zone(rows, "front", FRONT_POPULATION, FRONT_SELECTION, True,
                           BOOTSTRAP_SEED, checkpoint_dir / "front.jsonl", digest)
    back = _evaluate_zone(rows, "back", BACK_POPULATION, BACK_SELECTION, False,
                          BOOTSTRAP_SEED + 1, checkpoint_dir / "back.jsonl", digest)
    p_values: dict[str, float | None] = {}
    for zone_name, zone in (("front", front), ("back", back)):
        for reference in ("uniform", "expanding", "ewma"):
            comparison = zone["paired_candidate_minus_baseline"][reference]
            p_values[f"{zone_name}:{reference}"] = (
                comparison["one_sided_null_centered_p_value"]
                if comparison is not None else None
            )
    holm_adjusted = _holm_adjust(p_values, family_size=6)
    for zone_name, zone in (("front", front), ("back", back)):
        for reference in ("uniform", "expanding", "ewma"):
            comparison = zone["paired_candidate_minus_baseline"][reference]
            if comparison is not None:
                comparison["holm_adjusted_p_value"] = holm_adjusted[f"{zone_name}:{reference}"]
                comparison["holm_family_size"] = 6

    diagnostic_pass = all(
        zone["complete_coverage"] and all(
            zone["paired_candidate_minus_baseline"][ref] is not None
            and zone["paired_candidate_minus_baseline"][ref]["ci_95_upper"] < 0.0
            and zone["paired_candidate_minus_baseline"][ref]["holm_adjusted_p_value"] is not None
            and zone["paired_candidate_minus_baseline"][ref]["holm_adjusted_p_value"] < 0.05
            for ref in ("uniform", "expanding", "ewma"))
        for zone in (front, back))
    result = {
        "run_type": "LOT-055-equipment-blind-exact-subset-rolling-origin",
        "snapshot_sha256": digest, "snapshot_rows": len(rows),
        "code_commit": os.environ.get("RESEARCH_CODE_COMMIT", os.environ.get("GITHUB_SHA", "local")),
        "snapshot_first_draw": rows[0]["draw_id"], "snapshot_last_draw": rows[-1]["draw_id"],
        "first_target_draw": rows[MIN_TRAIN]["draw_id"], "last_target_draw": rows[-1]["draw_id"],
        "target_count_per_zone": len(rows) - MIN_TRAIN, "minimum_training_rows": MIN_TRAIN,
        "model_comparison": ["uniform", "expanding", "ewma", "exponential_family"],
        "objective_scale": "mean_nll", "regularization_lambda": 1.0,
        "solver": "scipy.optimize.L-BFGS-B",
        "solver_version": scipy.__version__,
        "solver_options": {
            "max_iterations": CANDIDATE_MAX_ITERATIONS,
            "max_function_evaluations": CANDIDATE_MAX_ITERATIONS * 100,
            "history_size": 10,
            "max_line_search_steps": 60,
            "ftol": 0.0,
            "gradient_tolerance": CANDIDATE_GRADIENT_TOLERANCE,
            "bounds": None,
        },
        "solver_policy_note": "Matches the frozen L-BFGS-B proposal; parameters are unconstrained and no box bounds are supplied.",
        "diagnostic_candidate_pass": bool(diagnostic_pass),
        "confirmatory_candidate_pass": bool(diagnostic_pass),
        "confirmatory_status": (
            "passed_preregistered_six_comparison_gate" if diagnostic_pass
            else "did_not_pass_preregistered_six_comparison_gate"
        ),
        "confirmatory_block_reason": None,
        "data_trust_status": "manifest_complete_not_officially_authenticated",
        "bootstrap": {"replicates": BOOTSTRAP_REPLICATES, "block_length": BOOTSTRAP_BLOCK,
                      "seed": BOOTSTRAP_SEED,
                      "method": "paired non-circular moving-block percentile CI plus null-centered one-sided test"},
        "multiple_testing": {
            "method": "Holm step-down",
            "family_size": 6,
            "alpha": 0.05,
            "family": ["front:uniform", "front:expanding", "front:ewma",
                       "back:uniform", "back:expanding", "back:ewma"],
            "adjusted_p_values": holm_adjusted,
        },
        "front": front, "back": back,
        "production_ready": False,
        "limitations": ["pooled equipment-blind model only", "snapshot not officially authenticated",
                        "no LOT-042 access", "no promotion or serving"],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                           encoding="utf-8")
    print("SUBSET_MODEL_ROLLING_ORIGIN_RESULT=" + json.dumps({
        "snapshot_sha256": digest, "target_count_per_zone": result["target_count_per_zone"],
        "front_complete": front["complete_coverage"], "back_complete": back["complete_coverage"],
        "front_scores": front["mean_exact_set_nll"], "back_scores": back["mean_exact_set_nll"],
        "diagnostic_candidate_pass": result["diagnostic_candidate_pass"],
        "confirmatory_candidate_pass": result["confirmatory_candidate_pass"],
        "confirmatory_status": result["confirmatory_status"], "production_ready": False,
    }, sort_keys=True))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint-dir", type=Path)
    args = parser.parse_args()
    run(args.snapshot, args.output, args.checkpoint_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
