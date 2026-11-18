"""Multiplicity-controlled pair co-occurrence diagnostics under legal-draw nulls."""
from __future__ import annotations

from collections import Counter
from itertools import combinations
import math
from typing import Any, Iterable

from .baseline import holm_adjust

FRONT_POOL_SIZE, FRONT_PICK = 35, 5
BACK_POOL_SIZE, BACK_PICK = 12, 2
_MIN_LOG_FLOAT = -744.4400719213812


def _validate_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    records = list(rows)
    if not records:
        raise ValueError("cannot analyze an empty dataset")
    for index, row in enumerate(records, 1):
        for field, pool_size, pick in (
            ("front_numbers", FRONT_POOL_SIZE, FRONT_PICK),
            ("back_numbers", BACK_POOL_SIZE, BACK_PICK),
        ):
            values = row.get(field)
            if (not isinstance(values, list) or len(values) != pick
                    or any(type(value) is not int or not 1 <= value <= pool_size for value in values)
                    or len(set(values)) != pick):
                raise ValueError(
                    f"draw {index}: {field} must contain {pick} distinct integers in 1..{pool_size}"
                )
    return records


def _log_binomial_pmf(n: int, x: int, probability: float) -> float:
    return (
        math.lgamma(n + 1) - math.lgamma(x + 1) - math.lgamma(n - x + 1)
        + x * math.log(probability)
        + (n - x) * math.log1p(-probability)
    )


def _logsumexp(values: list[float]) -> float:
    peak = max(values)
    return peak + math.log(math.fsum(math.exp(value - peak) for value in values))


def _binomial_cdf(n: int, observed: int, probability: float) -> float:
    log_probability = _logsumexp([
        _log_binomial_pmf(n, value, probability)
        for value in range(observed + 1)
    ])
    return min(1.0, math.exp(max(_MIN_LOG_FLOAT, log_probability)))


def _binomial_survival(n: int, observed: int, probability: float) -> float:
    log_probability = _logsumexp([
        _log_binomial_pmf(n, value, probability)
        for value in range(observed, n + 1)
    ])
    return min(1.0, math.exp(max(_MIN_LOG_FLOAT, log_probability)))


def exact_binomial_two_sided_pvalue(n: int, observed: int, probability: float) -> float:
    """Conservative equal-tailed exact two-sided binomial p-value."""
    if n < 1 or not 0 <= observed <= n:
        raise ValueError("observed count must be in 0..n and n must be positive")
    if not 0 < probability < 1:
        raise ValueError("binomial probability must be strictly between zero and one")
    lower = _binomial_cdf(n, observed, probability)
    upper = _binomial_survival(n, observed, probability)
    return min(1.0, 2.0 * min(lower, upper))


def _pair_counts(records: list[dict[str, Any]], field: str) -> Counter[tuple[int, int]]:
    counts: Counter[tuple[int, int]] = Counter()
    for row in records:
        counts.update(combinations(sorted(row[field]), 2))
    return counts


def analyze_pair_cooccurrence(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Test all fixed pairs; Holm-adjust one family spanning both zones."""
    records = _validate_rows(rows)
    draw_count = len(records)
    zones = (
        ("front", "front_numbers", FRONT_POOL_SIZE, FRONT_PICK),
        ("back", "back_numbers", BACK_POOL_SIZE, BACK_PICK),
    )
    raw_p_values: dict[str, float] = {}
    zone_results: dict[str, list[dict[str, Any]]] = {}
    null: dict[str, dict[str, float]] = {}

    for zone, field, pool_size, pick in zones:
        probability = pick * (pick - 1) / (pool_size * (pool_size - 1))
        expected = draw_count * probability
        counts = _pair_counts(records, field)
        pair_results = []
        p_cache: dict[int, float] = {}
        for first, second in combinations(range(1, pool_size + 1), 2):
            observed = counts[(first, second)]
            if observed not in p_cache:
                p_cache[observed] = exact_binomial_two_sided_pvalue(
                    draw_count, observed, probability
                )
            key = f"{zone}:{first:02d}-{second:02d}"
            raw_p_values[key] = p_cache[observed]
            pair_results.append({
                "pair": [first, second],
                "count": observed,
                "expected_count": expected,
                "count_delta": observed - expected,
                "p_value_two_sided": p_cache[observed],
            })
        zone_results[zone] = pair_results
        null[zone] = {
            "pool_size": pool_size,
            "numbers_drawn_per_draw": pick,
            "pair_inclusion_probability_per_draw": probability,
            "expected_pair_count": expected,
        }

    adjusted = holm_adjust(raw_p_values)
    for zone, pair_results in zone_results.items():
        for item in pair_results:
            first, second = item["pair"]
            key = f"{zone}:{first:02d}-{second:02d}"
            item["holm_adjusted_p_value"] = adjusted[key]
            item["significant_at_0_05_after_holm"] = adjusted[key] <= 0.05

    all_pairs = [item for zone, _, _, _ in zones for item in zone_results[zone]]
    most_unusual = sorted(
        [
            {"zone": zone, **item}
            for zone, _, _, _ in zones
            for item in zone_results[zone]
        ],
        key=lambda item: (item["holm_adjusted_p_value"], item["zone"], item["pair"]),
    )
    return {
        "method": (
            "Per-pair exact equal-tailed two-sided binomial tests under independent "
            "uniform legal draws; one Holm family across all front and back pairs"
        ),
        "draw_count": draw_count,
        "hypotheses_tested": len(raw_p_values),
        "familywise_alpha": 0.05,
        "null": null,
        "front_pairs": zone_results["front"],
        "back_pairs": zone_results["back"],
        "most_unusual_pairs_by_adjusted_p": most_unusual[:20],
        "significant_pair_count_after_holm": sum(
            item["significant_at_0_05_after_holm"] for item in all_pairs
        ),
        "limitations": [
            "The binomial null assumes independent draws across time as well as uniform selection without replacement within each zone.",
            "Holm controls family-wise error across all 661 pair tests under arbitrary dependence among the tests, but does not repair a misspecified across-draw null.",
            "A small adjusted p-value is a discrepancy under this null, not evidence of manipulation, a causal mechanism, or future predictive value.",
            "Candidate data provenance must be independently verified before interpreting historical deviations.",
            "Pair co-occurrence is descriptive only and is not used as a forecast feature.",
        ],
    }
