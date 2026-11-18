"""Legal-draw Monte Carlo baseline for exploratory frequency diagnostics.

The simulation seed belongs to this analysis only. It says nothing about the
physical lottery equipment or the source of randomness used in real draws.
"""
from __future__ import annotations

from collections import Counter
import random
from typing import Any, Iterable

FRONT_POOL = tuple(range(1, 36))
BACK_POOL = tuple(range(1, 13))
FRONT_PICK = 5
BACK_PICK = 2


def _pearson(counts: list[int], expected: float) -> float:
    return sum((observed - expected) ** 2 / expected for observed in counts)


def _max_abs_z(counts: list[int], expected: float, standard_deviation: float) -> float:
    return max(abs(observed - expected) / standard_deviation for observed in counts)


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    """Holm step-down family-wise adjustment for a named family of p-values."""
    ordered = sorted(p_values.items(), key=lambda item: item[1])
    adjusted: dict[str, float] = {}
    running_max = 0.0
    total = len(ordered)
    for rank, (name, p_value) in enumerate(ordered):
        running_max = max(running_max, min(1.0, (total - rank) * p_value))
        adjusted[name] = running_max
    return adjusted


def _count_numbers(rows: list[dict[str, Any]], field: str, pool_size: int) -> list[int]:
    counter: Counter[int] = Counter()
    for row in rows:
        counter.update(row[field])
    return [counter[number] for number in range(1, pool_size + 1)]


def _draw_features(rows: list[dict[str, Any]]) -> dict[str, Any]:
    front_sums = [sum(row["front_numbers"]) for row in rows]
    back_sums = [sum(row["back_numbers"]) for row in rows]
    front_odd = [sum(number % 2 for number in row["front_numbers"]) for row in rows]
    adjacent_front_pairs = [
        sum(b == a + 1 for a, b in zip(sorted(row["front_numbers"]), sorted(row["front_numbers"])[1:]))
        for row in rows
    ]
    return {
        "mean_front_sum": sum(front_sums) / len(rows),
        "mean_back_sum": sum(back_sums) / len(rows),
        "mean_front_odd_count": sum(front_odd) / len(rows),
        "mean_adjacent_front_pairs": sum(adjacent_front_pairs) / len(rows),
    }


def analyze_frequency_baseline(
    rows: Iterable[dict[str, Any]],
    *,
    simulations: int = 999,
    seed: int = 20261118,
) -> dict[str, Any]:
    """Compare observed marginal number frequencies with legal independent draws."""
    records = list(rows)
    if not records:
        raise ValueError("cannot analyze an empty dataset")
    if simulations < 1:
        raise ValueError("simulations must be at least 1")

    draw_count = len(records)
    front_counts = _count_numbers(records, "front_numbers", 35)
    back_counts = _count_numbers(records, "back_numbers", 12)

    front_expected = draw_count * FRONT_PICK / len(FRONT_POOL)
    back_expected = draw_count * BACK_PICK / len(BACK_POOL)
    front_sd = (draw_count * (FRONT_PICK / 35) * (1 - FRONT_PICK / 35)) ** 0.5
    back_sd = (draw_count * (BACK_PICK / 12) * (1 - BACK_PICK / 12)) ** 0.5

    observed = {
        "front_pearson": _pearson(front_counts, front_expected),
        "back_pearson": _pearson(back_counts, back_expected),
        "front_max_abs_z": _max_abs_z(front_counts, front_expected, front_sd),
        "back_max_abs_z": _max_abs_z(back_counts, back_expected, back_sd),
    }

    rng = random.Random(seed)
    exceed = {key: 0 for key in observed}
    for _ in range(simulations):
        simulated_front = [0] * 35
        simulated_back = [0] * 12
        for _draw in range(draw_count):
            for number in rng.sample(FRONT_POOL, FRONT_PICK):
                simulated_front[number - 1] += 1
            for number in rng.sample(BACK_POOL, BACK_PICK):
                simulated_back[number - 1] += 1
        simulated = {
            "front_pearson": _pearson(simulated_front, front_expected),
            "back_pearson": _pearson(simulated_back, back_expected),
            "front_max_abs_z": _max_abs_z(simulated_front, front_expected, front_sd),
            "back_max_abs_z": _max_abs_z(simulated_back, back_expected, back_sd),
        }
        for key, value in simulated.items():
            exceed[key] += value >= observed[key]

    p_values = {key: (exceed[key] + 1) / (simulations + 1) for key in observed}
    monte_carlo_se = {
        key: (p * (1 - p) / (simulations + 1)) ** 0.5
        for key, p in p_values.items()
    }

    return {
        "method": "independent legal draws; sampling without replacement within each zone",
        "draw_count": draw_count,
        "simulations": simulations,
        "seed": seed,
        "null": {
            "front_inclusion_probability_per_draw": 1 / 7,
            "back_inclusion_probability_per_draw": 1 / 6,
            "front_expected_count_per_number": front_expected,
            "back_expected_count_per_number": back_expected,
        },
        "observed_statistics": observed,
        "monte_carlo_p_values_upper_tail": p_values,
        "holm_adjusted_p_values_within_report": holm_adjust(p_values),
        "monte_carlo_standard_errors": monte_carlo_se,
        "front_frequency": [
            {"number": number, "count": front_counts[number - 1]}
            for number in range(1, 36)
        ],
        "back_frequency": [
            {"number": number, "count": back_counts[number - 1]}
            for number in range(1, 13)
        ],
        "draw_level_descriptives": _draw_features(records),
        "interpretation": (
            "Exploratory diagnostics only. Monte Carlo p-values test global marginal "
            "frequency imbalance under the stated null; they do not identify causes, "
            "prove manipulation, or imply predictive advantage."
        ),
    }
