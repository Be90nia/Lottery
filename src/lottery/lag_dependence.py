"""Exact circular-shift diagnostics for R1-R4 draw-to-draw dependence.

The randomization preserves each complete draw row (and therefore each legal
fixed-size selected set) while shifting the time origin. It is conditional on
the observed per-number frequencies and assumes no privileged cyclic origin.
It is a diagnostic, not a test for manipulation or a guarantee of predictability.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

ZONES = (
    ("front", "front_numbers", 35, 5),
    ("back", "back_numbers", 12, 2),
)
LAGS = (1, 2, 3, 4)


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


def rotate_time(mask: int, shift: int, n: int, full_mask: int) -> int:
    """Return a mask whose bit t is the original mask's bit (t-shift) mod n."""
    return ((mask << shift) | (mask >> (n - shift))) & full_mask


def holm_adjust(items: list[dict[str, Any]]) -> None:
    ordered = sorted(items, key=lambda item: item["p_value"])
    running = 0.0
    total = len(ordered)
    for rank, item in enumerate(ordered):
        adjusted = min(1.0, (total - rank) * item["p_value"])
        running = max(running, adjusted)
        item["p_value_holm"] = running


def zone_diagnostics(rows: list[dict[str, Any]], zone: tuple[str, str, int, int],
                     max_features: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    zone_name, field, pool_size, pick = zone
    n = len(rows)
    full_mask = (1 << n) - 1
    masks = [0] * pool_size
    for draw_index, row in enumerate(rows):
        bit = 1 << draw_index
        for number in row[field]:
            masks[number - 1] |= bit

    shift_count = n - 1
    null_max = [0.0] * shift_count
    observed_max = {lag: 0.0 for lag in LAGS}
    top_by_lag: dict[int, list[dict[str, Any]]] = {lag: [] for lag in LAGS}
    diagonal_counts: dict[int, list[int]] = {lag: [] for lag in LAGS}
    diagonal_means: list[float] = []
    diagonal_shift_counts = [0] * shift_count
    diagonal_shift_means: list[float] = []

    for a in range(pool_size):
        for b in range(pool_size):
            counts = [
                (masks[a] & rotate_time(masks[b], shift, n, full_mask)).bit_count()
                for shift in range(1, n)
            ]
            mean = sum(counts) / shift_count
            variance = sum((value - mean) ** 2 for value in counts) / shift_count
            sd = math.sqrt(variance)
            if a == b:
                diagonal_means.append(mean)
                for index, value in enumerate(counts):
                    diagonal_shift_counts[index] += value
            if sd > 0:
                for index, value in enumerate(counts):
                    null_max[index] = max(null_max[index], abs(value - mean) / sd)

            for lag in LAGS:
                value = counts[lag - 1]
                z_score = abs(value - mean) / sd if sd > 0 else 0.0
                observed_max[lag] = max(observed_max[lag], z_score)
                feature = {
                    "from_number": a + 1,
                    "to_number": b + 1,
                    "kind": "same_number_recurrence" if a == b else "ordered_cross_number_transition",
                    "observed_count": value,
                    "circular_shift_expected": mean,
                    "effect_count": value - mean,
                    "absolute_standardized_effect": z_score,
                }
                top_by_lag[lag].append(feature)

    all_pair_effects = {lag: list(top_by_lag[lag]) for lag in LAGS}
    for lag in LAGS:
        top_by_lag[lag].sort(
            key=lambda item: item["absolute_standardized_effect"], reverse=True
        )
        top_by_lag[lag] = top_by_lag[lag][:max_features]

    overlap_values = diagonal_shift_counts
    overlap_mean = sum(overlap_values) / shift_count
    overlap_variance = sum((value - overlap_mean) ** 2 for value in overlap_values) / shift_count
    overlap_sd = math.sqrt(overlap_variance)
    overlap_results = []
    for lag in LAGS:
        observed_overlap = overlap_values[lag - 1]
        distance = abs(observed_overlap - overlap_mean)
        p_overlap = (
            sum(abs(value - overlap_mean) >= distance - 1e-12 for value in overlap_values)
            / shift_count
        )
        overlap_results.append({
            "lag": lag,
            "observed_shared_numbers_across_draw_pairs": observed_overlap,
            "circular_shift_expected": overlap_mean,
            "independent_fixed_size_expected": n * pick * pick / pool_size,
            "effect_vs_circular_shift": observed_overlap - overlap_mean,
            "circular_shift_sd": overlap_sd,
            "two_sided_circular_shift_p_descriptive_only": p_overlap,
        })

    same_number_results = []
    for lag in LAGS:
        observed = sum(
            (masks[number] & rotate_time(masks[number], lag, n, full_mask)).bit_count()
            for number in range(pool_size)
        )
        expected = sum(diagonal_means)
        same_number_results.append({
            "lag": lag,
            "observed_recurrence_count": observed,
            "circular_shift_expected": expected,
            "independent_fixed_size_expected": n * pick * pick / pool_size,
            "effect_vs_circular_shift": observed - expected,
        })

    omnibus = []
    for lag in LAGS:
        observed_stat = observed_max[lag]
        p_value = sum(value >= observed_stat - 1e-12 for value in null_max) / shift_count
        omnibus.append({
            "zone": zone_name,
            "lag": lag,
            "statistic": "maximum_absolute_standardized_ordered_transition",
            "observed_max_statistic": observed_stat,
            "exact_circular_shift_p": p_value,
            "p_value": p_value,
            "null_shifts": shift_count,
            "p_value_resolution": 1 / shift_count,
        })

    result = {
        "zone": zone_name,
        "draws": n,
        "pool_size": pool_size,
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
    }
    return result, omnibus


def analyze(rows: list[dict[str, Any]], dataset_sha256: str,
            max_features: int = 20) -> dict[str, Any]:
    zone_results = []
    omnibus_tests: list[dict[str, Any]] = []
    for zone in ZONES:
        result, tests = zone_diagnostics(rows, zone, max_features)
        zone_results.append(result)
        omnibus_tests.extend(tests)
    holm_adjust(omnibus_tests)
    adjusted = {(item["zone"], item["lag"]): item["p_value_holm"]
                for item in omnibus_tests}
    for zone_result in zone_results:
        for item in zone_result["omnibus_tests"]:
            item["p_value_holm_across_8_zone_lag_tests"] = adjusted[
                (item["zone"], item["lag"])
            ]
    return {
        "schema": "dlt-r1-r4-circular-shift-diagnostics/v1",
        "dataset_sha256": dataset_sha256,
        "draw_count": len(rows),
        "first_draw_id": str(rows[0]["draw_id"]),
        "last_draw_id": str(rows[-1]["draw_id"]),
        "lag_definition": "lag r compares draw t with draw t-r; r=1 is immediately previous draw",
        "randomization": {
            "method": "exact enumeration of all non-zero circular shifts of complete draw rows",
            "shifts_per_test": len(rows) - 1,
            "preserves": [
                "each draw's legal fixed-size selected set",
                "per-number inclusion totals",
                "front/back zone separation",
            ],
            "assumption": "under the null, no circular time origin is privileged",
            "boundary_note": "circular pairing includes wraparound; interpret as a conditional phase-randomization diagnostic",
            "monte_carlo": False,
        },
        "multiplicity": {
            "confirmatory_family": "8 zone-by-lag omnibus maximum-statistic tests",
            "adjustment": "Holm across all 4 lags x 2 zones",
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
    parser.add_argument("--max-features", type=int, default=20)
    args = parser.parse_args()
    if args.max_features < 1:
        parser.error("--max-features must be positive")
    rows, digest = load_rows(args.input)
    report = analyze(rows, digest, args.max_features)
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
