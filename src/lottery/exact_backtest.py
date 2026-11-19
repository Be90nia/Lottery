"""Strict exact-set rolling-origin evaluation primitives.

The runner is separate from the legacy marginal backtest and refuses any
snapshot/target mismatch before fitting. Callers supply preregistered model
factories; this module never tunes or silently substitutes a failed model.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from typing import Callable, Any, Sequence

from lottery.subset_probability import validate_subset

ZONES = {
    "front": ("front_numbers", 35, 5),
    "back": ("back_numbers", 12, 2),
}


def holm_adjust(p_values: dict[str, float], *, expected_family_size: int | None = None) -> dict[str, float]:
    """Holm step-down family-wise adjustment, preserving the supplied family."""
    if not p_values:
        raise ValueError("p-value family must not be empty")
    if expected_family_size is not None and len(p_values) != expected_family_size:
        raise ValueError("p-value family size does not match preregistration")
    for name, value in p_values.items():
        if not isinstance(name, str) or not name:
            raise ValueError("hypothesis names must be non-empty strings")
        if type(value) not in (int, float) or not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError("p-values must be finite numbers in [0, 1]")
    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    adjusted: dict[str, float] = {}
    running_max = 0.0
    family_size = len(ordered)
    for rank, (name, value) in enumerate(ordered):
        running_max = max(running_max, min(1.0, (family_size - rank) * value))
        adjusted[name] = running_max
    return adjusted


def moving_block_bootstrap_ci(values: Sequence[float], *, replicates: int = 1000,
                              block_length: int = 50, seed: int) -> dict[str, float | int]:
    """Non-circular paired moving-block percentile interval; no short-fixture fallback."""
    observations = tuple(float(value) for value in values)
    if not observations or any(not math.isfinite(value) for value in observations):
        raise ValueError("bootstrap values must be a non-empty finite sequence")
    if type(replicates) is not int or replicates < 1:
        raise ValueError("replicates must be a positive integer")
    if type(block_length) is not int or block_length < 1 or block_length > len(observations):
        raise ValueError("block length must be in 1..number of paired targets")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    rng = random.Random(seed)
    starts = tuple(range(0, len(observations) - block_length + 1))
    means = []
    for _ in range(replicates):
        sample: list[float] = []
        while len(sample) < len(observations):
            start = rng.choice(starts)
            sample.extend(observations[start:start + block_length])
        means.append(math.fsum(sample[:len(observations)]) / len(observations))
    means.sort()

    def percentile(probability: float) -> float:
        position = (len(means) - 1) * probability
        lower = int(math.floor(position))
        upper = int(math.ceil(position))
        if lower == upper:
            return means[lower]
        fraction = position - lower
        return means[lower] * (1.0 - fraction) + means[upper] * fraction

    return {
        "mean_delta": math.fsum(observations) / len(observations),
        "ci95_lower": percentile(0.025),
        "ci95_upper": percentile(0.975),
        "replicates": replicates,
        "block_length": block_length,
        "seed": seed,
    }


def uniform_exact_nll(population_size: int, selection_size: int) -> float:
    if type(population_size) is not int or type(selection_size) is not int:
        raise ValueError("support dimensions must be integers")
    if population_size < 1 or selection_size < 0 or selection_size > population_size:
        raise ValueError("invalid support dimensions")
    return math.log(math.comb(population_size, selection_size))


def verify_frozen_snapshot(raw: bytes, *, expected_sha256: str,
                           expected_row_count: int,
                           expected_target_ids: Sequence[str],
                           min_train: int = 300) -> list[dict[str, Any]]:
    """Verify exact bytes, chronology, legal subsets, and complete target denominator."""
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha256:
        raise ValueError("snapshot SHA-256 mismatch; preregistration must be amended")
    if type(expected_row_count) is not int or expected_row_count < 1:
        raise ValueError("expected row count must be positive")
    if type(min_train) is not int or min_train < 1:
        raise ValueError("minimum training history must be positive")
    try:
        lines = raw.decode("utf-8").splitlines()
        if any(not line.strip() for line in lines):
            raise ValueError("blank JSONL rows are not allowed")
        records = [json.loads(line) for line in lines]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("snapshot is not valid UTF-8 JSONL") from exc
    if len(records) != expected_row_count:
        raise ValueError("snapshot row count mismatch")
    seen: set[str] = set()
    previous: tuple[str, str] | None = None
    for index, row in enumerate(records):
        if not isinstance(row, dict):
            raise ValueError(f"row {index + 1} is not an object")
        draw_id, draw_date = row.get("draw_id"), row.get("draw_date")
        if not isinstance(draw_id, str) or not draw_id or not isinstance(draw_date, str):
            raise ValueError(f"row {index + 1} has invalid draw identity")
        key = (draw_date, draw_id)
        if previous is not None and key <= previous:
            raise ValueError("snapshot must be strictly chronological without duplicate keys")
        previous = key
        if draw_id in seen:
            raise ValueError("duplicate draw ID")
        seen.add(draw_id)
        for zone, (field, m, k) in ZONES.items():
            try:
                validate_subset(row.get(field), m, k)
            except ValueError as exc:
                raise ValueError(f"row {index + 1} has invalid {zone} subset: {exc}") from exc
    expected = tuple(expected_target_ids)
    actual_targets = tuple(row["draw_id"] for row in records[min_train:])
    if len(records) <= min_train or expected != actual_targets:
        raise ValueError("frozen target manifest does not exactly match the expected chronological denominator")
    return records


def evaluate_rolling_origin(
    records: Sequence[dict[str, Any]],
    *,
    target_ids: Sequence[str],
    model_factories: dict[str, Callable[[Sequence[dict[str, Any]], str], Callable[[Sequence[int]], float]]],
    min_train: int = 300,
    snapshot_sha256: str,
) -> dict[str, Any]:
    """Evaluate registered model factories with one terminal row per model/zone/target."""
    rows = tuple(records)
    if type(min_train) is not int or min_train < 1:
        raise ValueError("min_train must be positive")
    if not model_factories:
        raise ValueError("at least one non-uniform model factory is required")
    if "uniform" in model_factories:
        raise ValueError("uniform is a reserved analytic baseline name")
    expected_targets = tuple(target_ids)
    actual_targets = tuple(row["draw_id"] for row in rows[min_train:])
    if expected_targets != actual_targets:
        raise ValueError("target IDs do not exactly match records after minimum training history")
    if any(not callable(factory) for factory in model_factories.values()):
        raise ValueError("all model factories must be callable")

    records_out: list[dict[str, Any]] = []
    deltas: dict[str, dict[str, list[float]]] = {
        model: {zone: [] for zone in ZONES} for model in model_factories
    }
    for target_index in range(min_train, len(rows)):
        training = rows[:target_index]
        target = rows[target_index]
        if any(row["draw_date"] >= target["draw_date"] for row in training):
            raise ValueError("strict-before-target training cutoff violated")
        for zone, (field, population, selection) in ZONES.items():
            observed = tuple(target[field])
            uniform_nll = uniform_exact_nll(population, selection)
            records_out.append({
                "target_draw_id": target["draw_id"], "zone": zone, "model_id": "uniform",
                "snapshot_sha256": snapshot_sha256, "training_row_count": target_index,
                "training_last_draw_id": training[-1]["draw_id"],
                "strict_before_target": True, "status": "scored",
                "observed_subset": list(observed), "log_probability": -uniform_nll,
                "nll": uniform_nll, "failure_reason": None,
            })
            for model_id, factory in model_factories.items():
                base = {
                    "target_draw_id": target["draw_id"], "zone": zone, "model_id": model_id,
                    "snapshot_sha256": snapshot_sha256, "training_row_count": target_index,
                    "training_last_draw_id": training[-1]["draw_id"],
                    "strict_before_target": True, "observed_subset": list(observed),
                }
                try:
                    scorer = factory(training, zone)
                    if not callable(scorer):
                        raise TypeError("model factory did not return a scorer")
                    logp = float(scorer(observed))
                    if not math.isfinite(logp) or logp > 1e-12:
                        raise ValueError("model returned an invalid log probability")
                    nll = -logp
                    records_out.append({**base, "status": "scored", "log_probability": logp,
                                        "nll": nll, "failure_reason": None})
                    deltas[model_id][zone].append(nll - uniform_nll)
                except Exception as exc:
                    records_out.append({**base, "status": "runner_error",
                                        "log_probability": None, "nll": None,
                                        "failure_reason": f"{type(exc).__name__}: {exc}"})
    expected_record_count = len(expected_targets) * (len(model_factories) + 1) * len(ZONES)
    if len(records_out) != expected_record_count:
        raise ArithmeticError("terminal record denominator mismatch")
    summary: dict[str, Any] = {}
    for model_id, by_zone in deltas.items():
        summary[model_id] = {}
        for zone, values in by_zone.items():
            summary[model_id][zone] = {
                "expected_targets": len(expected_targets),
                "scored_targets": len(values),
                "coverage": len(values) / len(expected_targets) if expected_targets else 0.0,
                "paired_nll_delta_vs_uniform": math.fsum(values) / len(values) if values else None,
            }
    return {
        "snapshot_sha256": snapshot_sha256,
        "target_count": len(expected_targets),
        "minimum_training_rows": min_train,
        "expected_terminal_records": expected_record_count,
        "terminal_record_count": len(records_out),
        "records": records_out,
        "summary": summary,
        "interpretation": "Historical exact-set scoring only; not prospective evidence or proof of predictive advantage.",
    }
