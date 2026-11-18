"""Leakage-safe expanding-window evaluation for marginal number probabilities.

This is a research benchmark, not a claim that past draws predict future draws.
All model parameters are fixed in the experiment config; no tuning is performed
on the evaluation period.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Iterable

FRONT_SIZE, FRONT_PICK = 35, 5
BACK_SIZE, BACK_PICK = 12, 2
DEFAULT_ALPHA = 100.0
DEFAULT_MIN_TRAIN = 300


def _validate_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    records = list(rows)
    if len(records) < 2:
        raise ValueError("at least two draws are required")
    required = {"draw_id", "draw_date", "front_numbers", "back_numbers"}
    seen: set[str] = set()
    for index, row in enumerate(records):
        missing = required - row.keys()
        if missing:
            raise ValueError(f"row {index} missing fields: {sorted(missing)}")
        draw_id = str(row["draw_id"])
        if draw_id in seen:
            raise ValueError(f"duplicate draw_id: {draw_id}")
        seen.add(draw_id)
        for field, size, pick in (
            ("front_numbers", FRONT_SIZE, FRONT_PICK),
            ("back_numbers", BACK_SIZE, BACK_PICK),
        ):
            values = row[field]
            if (not isinstance(values, list) or len(values) != pick
                    or any(type(v) is not int or not 1 <= v <= size for v in values)
                    or len(set(values)) != pick):
                raise ValueError(f"invalid {field} in draw {draw_id}")
    records.sort(key=lambda row: (str(row["draw_date"]), str(row["draw_id"])))
    return records


def _inclusion_counts(rows: list[dict[str, Any]], field: str, pool_size: int) -> list[int]:
    counts = [0] * pool_size
    for row in rows:
        for number in row[field]:
            counts[number - 1] += 1
    return counts


def _probabilities(
    train: list[dict[str, Any]], field: str, pool_size: int, pick: int,
    *, model: str, alpha: float = DEFAULT_ALPHA, half_life: float = 100.0,
) -> list[float]:
    prior = pick / pool_size
    if model == "uniform":
        return [prior] * pool_size
    if model == "expanding":
        counts = _inclusion_counts(train, field, pool_size)
        return [(count + alpha * prior) / (len(train) + alpha) for count in counts]
    if model == "ewma":
        # Weights depend only on the age of each already-observed training draw.
        weights = [0.5 ** ((len(train) - 1 - i) / half_life) for i in range(len(train))]
        total_weight = sum(weights)
        counts = [0.0] * pool_size
        for weight, row in zip(weights, train):
            for number in row[field]:
                counts[number - 1] += weight
        return [(count + alpha * prior) / (total_weight + alpha) for count in counts]
    raise ValueError(f"unknown model: {model}")


def _scores(probabilities: list[float], actual: list[int]) -> tuple[float, float, int]:
    selected = set(actual)
    brier = sum((p - (1.0 if i + 1 in selected else 0.0)) ** 2
                for i, p in enumerate(probabilities)) / len(probabilities)
    eps = 1e-15
    log_loss = -sum(
        math.log(max(eps, min(1 - eps, p))) if i + 1 in selected
        else math.log(max(eps, min(1 - eps, 1 - p)))
        for i, p in enumerate(probabilities)
    ) / len(probabilities)
    ranked = sorted(range(1, len(probabilities) + 1),
                    key=lambda number: (-probabilities[number - 1], number))
    hits = len(set(ranked[:len(actual)]) & selected)
    return brier, log_loss, hits


def rolling_origin_backtest(
    rows: Iterable[dict[str, Any]], *, min_train: int = DEFAULT_MIN_TRAIN,
    alpha: float = DEFAULT_ALPHA, half_life: float = 100.0,
) -> dict[str, Any]:
    records = _validate_rows(rows)
    if min_train < 1 or min_train >= len(records):
        raise ValueError("min_train must be >= 1 and less than number of draws")
    if alpha <= 0 or half_life <= 0:
        raise ValueError("alpha and half_life must be positive")

    models = ("uniform", "expanding", "ewma")
    metrics = {
        model: {zone: {"brier_sum": 0.0, "log_loss_sum": 0.0, "topk_hits": 0}
                for zone in ("front", "back")}
        for model in models
    }
    evaluated = 0
    for target_index in range(min_train, len(records)):
        train = records[:target_index]
        target = records[target_index]
        evaluated += 1
        for model in models:
            for zone, field, size, pick in (
                ("front", "front_numbers", FRONT_SIZE, FRONT_PICK),
                ("back", "back_numbers", BACK_SIZE, BACK_PICK),
            ):
                probs = _probabilities(
                    train, field, size, pick, model=model,
                    alpha=alpha, half_life=half_life,
                )
                brier, log_loss, hits = _scores(probs, target[field])
                bucket = metrics[model][zone]
                bucket["brier_sum"] += brier
                bucket["log_loss_sum"] += log_loss
                bucket["topk_hits"] += hits

    summary: dict[str, Any] = {}
    for model in models:
        summary[model] = {}
        for zone, size, pick in (
            ("front", FRONT_SIZE, FRONT_PICK), ("back", BACK_SIZE, BACK_PICK)
        ):
            bucket = metrics[model][zone]
            summary[model][zone] = {
                "mean_brier_per_number": bucket["brier_sum"] / evaluated,
                "mean_log_loss_per_number": bucket["log_loss_sum"] / evaluated,
                "mean_hits_in_top_k": bucket["topk_hits"] / evaluated,
                "uniform_expected_top_k_hits": pick * pick / size,
            }
    return {
        "method": "expanding rolling-origin; each target uses strictly earlier draws",
        "draw_count": len(records),
        "first_evaluation_draw": records[min_train]["draw_id"],
        "last_evaluation_draw": records[-1]["draw_id"],
        "min_train_draws": min_train,
        "evaluated_draws": evaluated,
        "configuration": {"expanding_dirichlet_pseudo_draws": alpha,
                          "ewma_half_life_draws": half_life},
        "metrics": summary,
        "interpretation": (
            "Lower Brier/log loss is better; top-k hits are descriptive. "
            "A small observed difference is not evidence of a stable edge. "
            "This is a marginal-probability benchmark, not a joint ticket model."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--min-train", type=int, default=DEFAULT_MIN_TRAIN)
    parser.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    parser.add_argument("--half-life", type=float, default=100.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        raw = args.dataset.read_bytes()
        rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
        report = rolling_origin_backtest(
            rows, min_train=args.min_train, alpha=args.alpha, half_life=args.half_life
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"BACKTEST_FAILED: {exc}", file=sys.stderr)
        return 1
    report["dataset"] = {"path": str(args.dataset),
                         "sha256": hashlib.sha256(raw).hexdigest()}
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
