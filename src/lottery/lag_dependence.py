#!/usr/bin/env python3
"""Row-permutation R1-R4 dependence diagnostics for fixed-size lottery draws."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any

ZONES = (
    ("front", "front_numbers", 35, 5),
    ("back", "back_numbers", 12, 2),
)
LAGS = (1, 2, 3, 4)
DEFAULT_PERMUTATIONS = 1999
DEFAULT_SEED = 20261118


def load_rows(path: Path) -> tuple[list[dict[str, Any]], str]:
    raw = path.read_bytes()
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if len(rows) < 6:
        raise ValueError("at least six draws are required for lag 1-4 diagnostics")
    required = {"draw_id", "draw_date", "front_numbers", "back_numbers"}
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not required.issubset(row):
            raise ValueError(f"row {index} is missing required draw fields")
        draw_id = str(row["draw_id"])
        if draw_id in seen:
            raise ValueError(f"duplicate draw_id: {draw_id}")
        seen.add(draw_id)
        for _, field, pool, pick in ZONES:
            values = row[field]
            if (not isinstance(values, list) or len(values) != pick
                    or any(type(value) is not int or not 1 <= value <= pool for value in values)
                    or len(set(values)) != pick):
                raise ValueError(f"invalid {field} in draw {draw_id}")
    rows.sort(key=lambda row: (str(row["draw_date"]), str(row["draw_id"])))
    return rows, hashlib.sha256(raw).hexdigest()


def holm_adjust(items: list[dict[str, Any]]) -> None:
    ordered = sorted(items, key=lambda item: item["p_value"])
    running = 0.0
    total = len(ordered)
    for rank, item in enumerate(ordered):
        adjusted = min(1.0, (total - rank) * item["p_value"])
        running = max(running, adjusted)
        item["p_value_holm"] = running


def _row_masks(rows: list[dict[str, Any]], permutation: list[int] | None = None
               ) -> dict[str, list[int]]:
    n = len(rows)
    masks = {"front": [0] * 35, "back": [0] * 12}
    order = range(n) if permutation is None else permutation
    for position, row_index in enumerate(order):
        bit = 1 << position
        row = rows[row_index]
        for number in row["front_numbers"]:
            masks["front"][number - 1] |= bit
        for number in row["back_numbers"]:
            masks["back"][number - 1] |= bit
    return masks


def _transition_matrices(masks: list[int], n: int) -> dict[int, list[list[int]]]:
    matrices: dict[int, list[list[int]]] = {}
    shifted_by_lag = {lag: [mask >> lag for mask in masks] for lag in LAGS}
    for lag in LAGS:
        shifted = shifted_by_lag[lag]
        matrices[lag] = [
            [(masks[a] & shifted[b]).bit_count() for b in range(len(masks))]
            for a in range(len(masks))
        ]
    return matrices


def _permutation_moments(rows: list[dict[str, Any]], permutations: int,
                         seed: int) -> dict[str, Any]:
    n = len(rows)
    rng = random.Random(seed)
    output: dict[str, Any] = {}
    for zone, _, pool, _ in ZONES:
        output[zone] = {
            "sum": {lag: [[0.0] * pool for _ in range(pool)] for lag in LAGS},
            "sum_sq": {lag: [[0.0] * pool for _ in range(pool)] for lag in LAGS},
            "overlap_sum": {lag: 0.0 for lag in LAGS},
            "overlap_sum_sq": {lag: 0.0 for lag in LAGS},
        }

    population = range(n)
    for _ in range(permutations):
        permutation = rng.sample(population, n)
        masks_by_zone = _row_masks(rows, permutation)
        for zone, _, pool, _ in ZONES:
            matrices = _transition_matrices(masks_by_zone[zone], n)
            for lag in LAGS:
                matrix = matrices[lag]
                overlap = 0
                sums = output[zone]["sum"][lag]
                sums_sq = output[zone]["sum_sq"][lag]
                for a in range(pool):
                    row_values = matrix[a]
                    sum_row = sums[a]
                    sum_sq_row = sums_sq[a]
                    for b, value in enumerate(row_values):
                        sum_row[b] += value
                        sum_sq_row[b] += value * value
                        if a == b:
                            overlap += value
                output[zone]["overlap_sum"][lag] += overlap
                output[zone]["overlap_sum_sq"][lag] += overlap * overlap

    for zone, _, pool, _ in ZONES:
        for lag in LAGS:
            sums = output[zone]["sum"][lag]
            sums_sq = output[zone]["sum_sq"][lag]
            means = [[sums[a][b] / permutations for b in range(pool)] for a in range(pool)]
            sds = [[
                math.sqrt(max(0.0, sums_sq[a][b] / permutations - means[a][b] ** 2))
                for b in range(pool)
            ] for a in range(pool)]
            overlap_mean = output[zone]["overlap_sum"][lag] / permutations
            overlap_variance = (
                output[zone]["overlap_sum_sq"][lag] / permutations - overlap_mean ** 2
            )
            output[zone].setdefault("moments", {})[lag] = {
                "means": means,
                "sds": sds,
                "overlap_mean": overlap_mean,
                "overlap_sd": math.sqrt(max(0.0, overlap_variance)),
            }
    return output


def _permutation_maxima(rows: list[dict[str, Any]], moments: dict[str, Any],
                        permutations: int, seed: int
                        ) -> tuple[dict[str, list[float]], dict[str, dict[int, list[int]]]]:
    n = len(rows)
    rng = random.Random(seed)
    maxima = {zone: {lag: [] for lag in LAGS} for zone, *_ in ZONES}
    overlaps = {zone: {lag: [] for lag in LAGS} for zone, *_ in ZONES}
    population = range(n)

    for _ in range(permutations):
        permutation = rng.sample(population, n)
        masks_by_zone = _row_masks(rows, permutation)
        for zone, _, pool, _ in ZONES:
            matrices = _transition_matrices(masks_by_zone[zone], n)
            for lag in LAGS:
                matrix = matrices[lag]
                moment = moments[zone]["moments"][lag]
                means, sds = moment["means"], moment["sds"]
                maximum = 0.0
                overlap = 0
                for a in range(pool):
                    for b, value in enumerate(matrix[a]):
                        sd = sds[a][b]
                        if sd > 0:
                            z_score = abs(value - means[a][b]) / sd
                            if z_score > maximum:
                                maximum = z_score
                        if a == b:
                            overlap += value
                overlap_sd = moment["overlap_sd"]
                if overlap_sd > 0:
                    overlap_z = abs(overlap - moment["overlap_mean"]) / overlap_sd
                    maximum = max(maximum, overlap_z)
                maxima[zone][lag].append(maximum)
                overlaps[zone][lag].append(overlap)
    return maxima, overlaps


def _mc_summary(p_value: float, permutations: int) -> dict[str, float]:
    standard_error = math.sqrt(p_value * (1.0 - p_value) / (permutations + 1))
    return {
        "p_value": p_value,
        "monte_carlo_standard_error": standard_error,
        "monte_carlo_95_lower": max(0.0, p_value - 1.96 * standard_error),
        "monte_carlo_95_upper": min(1.0, p_value + 1.96 * standard_error),
    }


def analyze(rows: list[dict[str, Any]], dataset_sha256: str,
            permutations: int = DEFAULT_PERMUTATIONS,
            seed: int = DEFAULT_SEED, max_features: int = 20) -> dict[str, Any]:
    if permutations < 99:
        raise ValueError("at least 99 permutations are required")
    if max_features < 1:
        raise ValueError("max_features must be positive")
    n = len(rows)
    observed_masks = _row_masks(rows)
    moments = _permutation_moments(rows, permutations, seed)
    null_maxima, null_overlaps = _permutation_maxima(
        rows, moments, permutations, seed + 1
    )

    zone_results = []
    omnibus_tests: list[dict[str, Any]] = []
    for zone, _, pool, pick in ZONES:
        observed_matrices = _transition_matrices(observed_masks[zone], n)
        zone_moments = moments[zone]["moments"]
        same_number_results = []
        overlap_results = []
        top_by_lag = {}
        all_pair_effects = {}
        omnibus = []

        for lag in LAGS:
            matrix = observed_matrices[lag]
            moment = zone_moments[lag]
            means, sds = moment["means"], moment["sds"]
            features = []
            observed_max = 0.0
            observed_overlap = 0
            for a in range(pool):
                for b, value in enumerate(matrix[a]):
                    expected = means[a][b]
                    sd = sds[a][b]
                    z_score = abs(value - expected) / sd if sd > 0 else 0.0
                    observed_max = max(observed_max, z_score)
                    features.append({
                        "from_number": a + 1,
                        "to_number": b + 1,
                        "kind": "same_number_recurrence" if a == b else "ordered_cross_number_transition",
                        "observed_count": value,
                        "permutation_expected": expected,
                        "permutation_sd": sd,
                        "effect_count": value - expected,
                        "absolute_standardized_effect": z_score,
                    })
                    if a == b:
                        observed_overlap += value

            overlap_sd = moment["overlap_sd"]
            overlap_z = (
                abs(observed_overlap - moment["overlap_mean"]) / overlap_sd
                if overlap_sd > 0 else 0.0
            )
            observed_max = max(observed_max, overlap_z)
            null_max = null_maxima[zone][lag]
            exceedances = sum(value >= observed_max - 1e-12 for value in null_max)
            p_value = (exceedances + 1) / (permutations + 1)
            p_summary = _mc_summary(p_value, permutations)
            omnibus.append({
                "zone": zone,
                "lag": lag,
                "statistic": "maximum_absolute_standardized_transition_or_set_overlap",
                "observed_max_statistic": observed_max,
                "exceedances": exceedances,
                "permutations": permutations,
                **p_summary,
            })

            overlap_null = null_overlaps[zone][lag]
            overlap_distance = abs(observed_overlap - moment["overlap_mean"])
            overlap_exceedances = sum(
                abs(value - moment["overlap_mean"]) >= overlap_distance - 1e-12
                for value in overlap_null
            )
            overlap_p = (overlap_exceedances + 1) / (permutations + 1)
            overlap_results.append({
                "lag": lag,
                "observed_shared_numbers_across_draw_pairs": observed_overlap,
                "permutation_expected": moment["overlap_mean"],
                "independent_fixed_size_expected": (n - lag) * pick * pick / pool,
                "permutation_sd": overlap_sd,
                "effect_vs_permutation_expected": observed_overlap - moment["overlap_mean"],
                "two_sided_permutation_p_descriptive_only": overlap_p,
            })
            same_number_results.append({
                "lag": lag,
                "observed_recurrence_count": observed_overlap,
                "permutation_expected": moment["overlap_mean"],
                "independent_fixed_size_expected": (n - lag) * pick * pick / pool,
                "effect_vs_permutation_expected": observed_overlap - moment["overlap_mean"],
            })

            features.sort(
                key=lambda item: item["absolute_standardized_effect"], reverse=True
            )
            all_pair_effects[lag] = features
            top_by_lag[lag] = features[:max_features]
            omnibus_tests.append(omnibus[-1])

        zone_results.append({
            "zone": zone,
            "draws": n,
            "pool_size": pool,
            "numbers_per_draw": pick,
            "same_number_recurrence": same_number_results,
            "set_overlap": overlap_results,
            "top_ordered_transitions_by_lag": [
                {"lag": lag, "features": top_by_lag[lag]} for lag in LAGS
            ],
            "all_ordered_pair_effects_by_lag": [
                {"lag": lag, "features": all_pair_effects[lag]} for lag in LAGS
            ],
            "omnibus_tests": omnibus,
        })
    omnibus_tests = [
        item for zone_result in zone_results for item in zone_result["omnibus_tests"]
    ]
    holm_adjust(omnibus_tests)
    adjusted = {(item["zone"], item["lag"]): item["p_value_holm"]
                for item in omnibus_tests}
    for zone_result in zone_results:
        for item in zone_result["omnibus_tests"]:
            item["p_value_holm_across_8_zone_lag_tests"] = adjusted[
                (item["zone"], item["lag"])
            ]

    return {
        "schema": "dlt-r1-r4-row-permutation-diagnostics/v1",
        "dataset_sha256": dataset_sha256,
        "draw_count": n,
        "first_draw_id": str(rows[0]["draw_id"]),
        "last_draw_id": str(rows[-1]["draw_id"]),
        "lag_definition": "lag r compares draw t with draw t-r; r=1 is immediately previous draw",
        "randomization": {
            "method": "Monte Carlo uniform permutation of complete draw rows without replacement",
            "moment_permutations": permutations,
            "test_permutations": permutations,
            "moment_seed": seed,
            "test_seed": seed + 1,
            "preserves": [
                "each draw's legal fixed-size selected set",
                "per-number inclusion totals",
                "front/back zone separation",
            ],
            "breaks": "chronological order between complete draw rows",
            "p_value_formula": "(exceedances + 1) / (permutations + 1)",
            "monte_carlo_uncertainty": "standard error and normal-approximation 95% interval reported for each omnibus p-value",
        },
        "multiplicity": {
            "confirmatory_family": "8 zone-by-lag omnibus maximum-statistic tests",
            "adjustment": "Holm across all 4 lags x 2 zones",
            "maximum_statistic": "maximum absolute standardized deviation over all ordered number transitions (including same-number recurrence) and aggregate set overlap",
            "per_number_and_pair_rows": "effect-size diagnostics only; no individual significance claims",
        },
        "zones": zone_results,
        "omnibus_tests_holm": omnibus_tests,
        "interpretation_guardrails": [
            "A significant dependence diagnostic does not establish manipulation or a recoverable random seed.",
            "A temporal association is not automatically a forecast edge; Phase C must test proper scores out of sample.",
            "No feature is promoted by this diagnostic alone.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--permutations", type=int, default=DEFAULT_PERMUTATIONS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--max-features", type=int, default=20)
    args = parser.parse_args()
    rows, digest = load_rows(args.input)
    report = analyze(rows, digest, args.permutations, args.seed, args.max_features)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "dataset_sha256": digest,
        "draw_count": len(rows),
        "omnibus_tests_holm": report["omnibus_tests_holm"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
