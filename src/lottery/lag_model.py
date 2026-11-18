"""Strictly causal four-lag marginal inclusion model and rolling-origin evaluation."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from .backtest import (
    BACK_PICK, BACK_SIZE, FRONT_PICK, FRONT_SIZE,
    _moving_block_bootstrap_ci, _probabilities, _scores, _validate_rows,
)

LAG_COUNT = 4
RIDGE_LAMBDA = 10.0
BOOTSTRAP_REPLICATES = 1000
BOOTSTRAP_BLOCK_LENGTH = 50
BOOTSTRAP_SEED = 20261119


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


def _softplus(value: float) -> float:
    return max(value, 0.0) + math.log1p(math.exp(-abs(value)))


def _solve_linear(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Solve a small dense system with partial-pivot Gaussian elimination."""
    n = len(vector)
    augmented = [matrix[i][:] + [vector[i]] for i in range(n)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise ArithmeticError("singular information matrix")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        scale = augmented[column][column]
        for j in range(column, n + 1):
            augmented[column][j] /= scale
        for row in range(n):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor == 0:
                continue
            for j in range(column, n + 1):
                augmented[row][j] -= factor * augmented[column][j]
    return [augmented[i][n] for i in range(n)]


def _pattern_for_number(history: list[dict[str, Any]], target_index: int,
                        field: str, number: int) -> int:
    pattern = 0
    for lag in range(LAG_COUNT):
        if number in history[target_index - 1 - lag][field]:
            pattern |= 1 << lag
    return pattern


def _aggregate_training_cells(history: list[dict[str, Any]], field: str,
                              pool_size: int) -> tuple[list[int], list[int]]:
    counts = [0] * (1 << LAG_COUNT)
    successes = [0] * (1 << LAG_COUNT)
    for target_index in range(LAG_COUNT, len(history)):
        selected = set(history[target_index][field])
        for number in range(1, pool_size + 1):
            pattern = _pattern_for_number(history, target_index, field, number)
            counts[pattern] += 1
            if number in selected:
                successes[pattern] += 1
    return counts, successes


def _prefix_training_cells(records: list[dict[str, Any]], field: str,
                           pool_size: int) -> tuple[list[list[int]], list[list[int]]]:
    """Precompute causal prefix sufficient statistics for every rolling origin."""
    n = len(records)
    prefix_counts = [[0] * (1 << LAG_COUNT) for _ in range(n + 1)]
    prefix_successes = [[0] * (1 << LAG_COUNT) for _ in range(n + 1)]
    for target_index in range(n):
        prefix_counts[target_index + 1] = prefix_counts[target_index].copy()
        prefix_successes[target_index + 1] = prefix_successes[target_index].copy()
        if target_index < LAG_COUNT:
            continue
        selected = set(records[target_index][field])
        for number in range(1, pool_size + 1):
            pattern = _pattern_for_number(records, target_index, field, number)
            prefix_counts[target_index + 1][pattern] += 1
            if number in selected:
                prefix_successes[target_index + 1][pattern] += 1
    return prefix_counts, prefix_successes


def _fit_coefficients_from_cells(counts: list[int], successes: list[int],
                                 pick: int, pool_size: int,
                                 ridge: float = RIDGE_LAMBDA) -> tuple[list[float], dict[str, Any]]:
    if ridge <= 0:
        raise ValueError("ridge penalty must be positive")
    feature_rows = [
        [1.0] + [float((pattern >> lag) & 1) for lag in range(LAG_COUNT)]
        for pattern in range(1 << LAG_COUNT)
    ]
    theta = [math.log((pick / pool_size) / (1.0 - pick / pool_size))] + [0.0] * LAG_COUNT
    iterations = 0

    def objective(parameters: list[float]) -> float:
        value = 0.0
        for pattern, row in enumerate(feature_rows):
            if counts[pattern] == 0:
                continue
            score = sum(parameters[j] * row[j] for j in range(LAG_COUNT + 1))
            value += successes[pattern] * score - counts[pattern] * _softplus(score)
        value -= 0.5 * ridge * sum(parameters[j] ** 2 for j in range(1, LAG_COUNT + 1))
        return value

    for iteration in range(60):
        gradient = [0.0] * (LAG_COUNT + 1)
        information = [[0.0] * (LAG_COUNT + 1) for _ in range(LAG_COUNT + 1)]
        for pattern, row in enumerate(feature_rows):
            total = counts[pattern]
            if total == 0:
                continue
            score = sum(theta[j] * row[j] for j in range(LAG_COUNT + 1))
            probability = _sigmoid(score)
            residual = successes[pattern] - total * probability
            weight = total * probability * (1.0 - probability)
            for i in range(LAG_COUNT + 1):
                gradient[i] += residual * row[i]
                for j in range(LAG_COUNT + 1):
                    information[i][j] += weight * row[i] * row[j]
        for j in range(1, LAG_COUNT + 1):
            gradient[j] -= ridge * theta[j]
            information[j][j] += ridge

        if max(abs(value) for value in gradient) < 1e-8:
            iterations = iteration
            break
        delta = _solve_linear(information, gradient)
        current = objective(theta)
        step = 1.0
        accepted = False
        while step >= 1e-8:
            candidate = [theta[i] + step * delta[i] for i in range(LAG_COUNT + 1)]
            if objective(candidate) >= current - 1e-12:
                theta = candidate
                accepted = True
                break
            step *= 0.5
        iterations = iteration + 1
        if not accepted or max(abs(step * value) for value in delta) < 1e-8:
            break

    return theta, {
        "training_target_draws": sum(counts) // pool_size,
        "training_number_examples": sum(counts),
        "iterations": iterations,
        "ridge_lambda": ridge,
    }


def _fit_coefficients(history: list[dict[str, Any]], field: str, pool_size: int,
                      pick: int, ridge: float = RIDGE_LAMBDA) -> tuple[list[float], dict[str, Any]]:
    """Fit coefficients from a historical prefix (convenience path for tests)."""
    if len(history) < LAG_COUNT + 1:
        raise ValueError("at least five historical draws are required")
    counts, successes = _aggregate_training_cells(history, field, pool_size)
    return _fit_coefficients_from_cells(counts, successes, pick, pool_size, ridge)

def lag_probabilities(history: list[dict[str, Any]], field: str,
                      pool_size: int, pick: int,
                      ridge: float = RIDGE_LAMBDA,
                      training_cells: tuple[list[int], list[int]] | None = None
                      ) -> tuple[list[float], list[float], dict[str, Any]]:
    """Predict the next draw from four prior draws; probabilities sum exactly to pick."""
    if len(history) < LAG_COUNT:
        raise ValueError("four prior draws are required to construct lag features")
    # At least one historical labelled target is required to fit coefficients.
    if len(history) >= LAG_COUNT + 1:
        if training_cells is None:
            theta, fit_info = _fit_coefficients(history, field, pool_size, pick, ridge)
        else:
            theta, fit_info = _fit_coefficients_from_cells(
                training_cells[0], training_cells[1], pick, pool_size, ridge
            )
    else:
        theta = [math.log((pick / pool_size) / (1.0 - pick / pool_size))] + [0.0] * LAG_COUNT
        fit_info = {"training_target_draws": 0, "training_number_examples": 0,
                    "iterations": 0, "ridge_lambda": ridge}

    patterns = []
    scores = []
    for number in range(1, pool_size + 1):
        pattern = 0
        for lag in range(LAG_COUNT):
            if number in history[-1 - lag][field]:
                pattern |= 1 << lag
        patterns.append(pattern)
        score = theta[0] + sum(
            theta[lag + 1] for lag in range(LAG_COUNT) if pattern & (1 << lag)
        )
        scores.append(score)

    low, high = -40.0, 40.0
    for _ in range(100):
        offset = (low + high) / 2.0
        total = sum(_sigmoid(score + offset) for score in scores)
        if total > pick:
            high = offset
        else:
            low = offset
    offset = (low + high) / 2.0
    probabilities = [_sigmoid(score + offset) for score in scores]
    return probabilities, theta, {
        **fit_info,
        "prediction_patterns": patterns,
        "calibration_offset": offset,
    }


def rolling_origin_lag_backtest(rows: list[dict[str, Any]], *,
                                min_train: int = 300,
                                alpha: float = 100.0,
                                half_life: float = 100.0,
                                ridge: float = RIDGE_LAMBDA) -> dict[str, Any]:
    records = _validate_rows(rows)
    if min_train < LAG_COUNT + 1 or min_train >= len(records):
        raise ValueError("min_train must be >= 5 and less than number of draws")
    if alpha <= 0 or half_life <= 0 or ridge <= 0:
        raise ValueError("alpha, half_life, and ridge must be positive")

    baseline_models = ("uniform", "expanding", "ewma")
    metrics = {
        "lag_logistic": {
            zone: {"brier_sum": 0.0, "log_loss_sum": 0.0, "topk_hits": 0}
            for zone in ("front", "back")
        }
    }
    deltas = {
        baseline: {
            zone: {"brier": [], "log_loss": []}
            for zone in ("front", "back")
        }
        for baseline in baseline_models
    }
    coefficient_history = {
        zone: [] for zone in ("front", "back")
    }
    prefix_cells = {
        "front": _prefix_training_cells(records, "front_numbers", FRONT_SIZE),
        "back": _prefix_training_cells(records, "back_numbers", BACK_SIZE),
    }

    evaluated = 0
    for target_index in range(min_train, len(records)):
        history = records[:target_index]
        target = records[target_index]
        evaluated += 1
        for zone, field, size, pick in (
            ("front", "front_numbers", FRONT_SIZE, FRONT_PICK),
            ("back", "back_numbers", BACK_SIZE, BACK_PICK),
        ):
            candidate_probs, theta, _ = lag_probabilities(
                history, field, size, pick, ridge,
                training_cells=(
                    prefix_cells[zone][0][target_index],
                    prefix_cells[zone][1][target_index],
                ),
            )
            coefficient_history[zone].append(theta[1:])
            brier, log_loss, hits = _scores(candidate_probs, target[field])
            bucket = metrics["lag_logistic"][zone]
            bucket["brier_sum"] += brier
            bucket["log_loss_sum"] += log_loss
            bucket["topk_hits"] += hits

            for baseline in baseline_models:
                baseline_probs = _probabilities(
                    history, field, size, pick, model=baseline,
                    alpha=alpha, half_life=half_life,
                )
                base_brier, base_log_loss, _ = _scores(baseline_probs, target[field])
                deltas[baseline][zone]["brier"].append(brier - base_brier)
                deltas[baseline][zone]["log_loss"].append(log_loss - base_log_loss)

    candidate_summary = {}
    for zone, size, pick in (
        ("front", FRONT_SIZE, FRONT_PICK),
        ("back", BACK_SIZE, BACK_PICK),
    ):
        bucket = metrics["lag_logistic"][zone]
        coefficients = coefficient_history[zone]
        candidate_summary[zone] = {
            "mean_brier_per_number": bucket["brier_sum"] / evaluated,
            "mean_log_loss_per_number": bucket["log_loss_sum"] / evaluated,
            "mean_hits_in_top_k": bucket["topk_hits"] / evaluated,
            "uniform_expected_top_k_hits": pick * pick / size,
            "mean_lag_coefficients": [
                sum(row[i] for row in coefficients) / len(coefficients)
                for i in range(LAG_COUNT)
            ],
            "last_lag_coefficients": coefficients[-1],
        }

    paired_vs_baselines: dict[str, Any] = {}
    for baseline_index, baseline in enumerate(baseline_models):
        paired_vs_baselines[baseline] = {}
        for zone_index, zone in enumerate(("front", "back")):
            paired_vs_baselines[baseline][zone] = {
                metric: _moving_block_bootstrap_ci(
                    values,
                    replicates=BOOTSTRAP_REPLICATES,
                    block_length=BOOTSTRAP_BLOCK_LENGTH,
                    seed=BOOTSTRAP_SEED + baseline_index * 10 + zone_index * 2 + metric_index,
                )
                for metric_index, (metric, values) in enumerate(
                    deltas[baseline][zone].items()
                )
            }

    # Conservative promotion gate: the lag model must beat every reference
    # on both proper scores in both zones, using paired 95% block intervals.
    promotion_checks = []
    for baseline in baseline_models:
        for zone in ("front", "back"):
            for metric in ("brier", "log_loss"):
                interval = paired_vs_baselines[baseline][zone][metric]
                promotion_checks.append({
                    "baseline": baseline,
                    "zone": zone,
                    "metric": metric,
                    "upper_95_below_zero": interval["ci_95_upper"] < 0,
                    "ci_95_upper": interval["ci_95_upper"],
                })
    eligible = all(item["upper_95_below_zero"] for item in promotion_checks)

    return {
        "schema": "dlt-four-lag-logistic-rolling-backtest/v1",
        "draw_count": len(records),
        "evaluated_draws": evaluated,
        "first_evaluation_draw": str(records[min_train]["draw_id"]),
        "last_evaluation_draw": str(records[-1]["draw_id"]),
        "settings": {
            "min_train_draws": min_train,
            "lags": [1, 2, 3, 4],
            "ridge_lambda": ridge,
            "alpha_expanding_baseline": alpha,
            "half_life_ewma_baseline": half_life,
            "bootstrap_replicates": BOOTSTRAP_REPLICATES,
            "bootstrap_block_length_draws": BOOTSTRAP_BLOCK_LENGTH,
            "bootstrap_seed_base": BOOTSTRAP_SEED,
            "primary_metric": "per-number Brier",
            "secondary_metric": "per-number Bernoulli log loss",
            "delta_sign": "candidate minus baseline; negative is better",
        },
        "model": {
            "name": "four-lag shared-coefficient ridge logistic marginal inclusion model",
            "training_objective": "composite Bernoulli log likelihood over 16 lag-pattern cells with L2 penalty",
            "features": "same-number inclusion indicators at lags 1-4, using only draws before each target",
            "probability_calibration": "per-target intercept offset solved by bisection so sum of inclusion probabilities equals pick count",
            "joint_distribution_claim": False,
        },
        "metrics": {"lag_logistic": candidate_summary},
        "paired_score_delta_vs_baselines": paired_vs_baselines,
        "promotion_gate": {
            "rule": "all Brier and log-loss paired 95% moving-block CI upper bounds must be below zero versus uniform, expanding, and EWMA in both zones",
            "eligible_for_promotion": eligible,
            "checks": promotion_checks,
        },
        "interpretation": [
            "All forecasts are generated before their target draw; each fit uses only earlier labelled draws.",
            "The marginal inclusion probabilities sum to the legal pick count but do not specify a joint ticket distribution.",
            "Historical rolling-origin performance is not prospective validation.",
            "Top-K hits are descriptive; proper scores determine the promotion gate.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--min-train", type=int, default=300)
    parser.add_argument("--alpha", type=float, default=100.0)
    parser.add_argument("--half-life", type=float, default=100.0)
    parser.add_argument("--ridge", type=float, default=RIDGE_LAMBDA)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    report = rolling_origin_lag_backtest(
        rows, min_train=args.min_train, alpha=args.alpha,
        half_life=args.half_life, ridge=args.ridge,
    )
    report["dataset_sha256"] = __import__("hashlib").sha256(args.input.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "dataset_sha256": report["dataset_sha256"],
        "evaluated_draws": report["evaluated_draws"],
        "promotion_gate": report["promotion_gate"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
