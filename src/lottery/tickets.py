"""Small, reproducible MVP for generating legal DLT ticket candidates.

The three strategies are uniform, expanding-frequency, and EWMA marginal
weights. Weighted sampling is a diversification heuristic, not a joint model
or evidence of predictive advantage. No physical ball-set identity is inferred.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
from pathlib import Path
import sys
from typing import Any, Iterable

from .conditional_poisson import ConditionalPoisson
from .backtest import (
    BACK_PICK, BACK_SIZE, DEFAULT_ALPHA, FRONT_PICK, FRONT_SIZE,
    _probabilities, _validate_rows,
)
from .validate import validate_jsonl


STRATEGIES = ("uniform", "expanding", "ewma")
MAX_TICKETS_PER_STRATEGY = 100
SLOT_SEED_STRIDE = 1_000_003


SAMPLER_VERSION = "conditional-poisson-rejective-v1"
CALIBRATION_VERSION = "deterministic-lbfgs-armijo-calibration-v1"
CALIBRATION_TOLERANCE = 1e-8
CALIBRATION_MAX_ITERATIONS = 5000
CALIBRATION_HISTORY_SIZE = 10


def _calibrated_sampler(
    probabilities: list[float], count: int
) -> tuple[ConditionalPoisson, dict[str, Any]]:
    calibration = ConditionalPoisson.calibrate(
        probabilities,
        count,
        tolerance=CALIBRATION_TOLERANCE,
        max_iterations=CALIBRATION_MAX_ITERATIONS,
        history_size=CALIBRATION_HISTORY_SIZE,
    )
    if not calibration.converged:
        raise ValueError(
            f"conditional-Poisson marginal calibration failed: "
            f"{calibration.terminal_status}; residual={calibration.maximum_absolute_residual}"
        )
    sampler = ConditionalPoisson(calibration.centered_log_weights, count)
    achieved = sampler.inclusion_marginals()
    residual = max(abs(actual - target) for actual, target in zip(achieved, probabilities))
    if not math.isfinite(residual) or residual > CALIBRATION_TOLERANCE:
        raise ValueError(
            f"conditional-Poisson sampler failed independent marginal check: {residual}"
        )
    return sampler, {
        "terminal_status": calibration.terminal_status,
        "iterations": calibration.iterations,
        "gradient_infinity_norm": calibration.gradient_infinity_norm,
        "maximum_absolute_residual": residual,
        "tolerance": CALIBRATION_TOLERANCE,
        "algorithm": CALIBRATION_VERSION,
    }


def _sample_ticket_subset(sampler: ConditionalPoisson, rng: random.Random) -> list[int]:
    return list(sampler.sample(rng))


def generate_ticket_candidates(
    rows: Iterable[dict[str, Any]], *, tickets_per_strategy: int = 1,
    seed: int = 20261119, alpha: float = DEFAULT_ALPHA,
    half_life: float = 100.0, code_commit: str | None = None,
) -> dict[str, Any]:
    if type(tickets_per_strategy) is not int or not 1 <= tickets_per_strategy <= MAX_TICKETS_PER_STRATEGY:
        raise ValueError(f"tickets_per_strategy must be a positive integer in 1..{MAX_TICKETS_PER_STRATEGY}")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    if type(alpha) not in (int, float) or not math.isfinite(alpha) or alpha <= 0:
        raise ValueError("alpha must be finite and positive (non-boolean numeric value)")
    if type(half_life) not in (int, float) or not math.isfinite(half_life) or half_life <= 0:
        raise ValueError("half_life must be finite and positive (non-boolean numeric value)")
    if code_commit is not None and (
        not isinstance(code_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", code_commit)
    ):
        raise ValueError("code_commit must be a full 40-character lowercase Git SHA or None")

    records = _validate_rows(rows)
    canonical_rows = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    dataset_fingerprint = hashlib.sha256(canonical_rows).hexdigest()
    run_identity = {
        "dataset_fingerprint": dataset_fingerprint,
        "seed": seed,
        "tickets_per_strategy": tickets_per_strategy,
        "alpha": alpha,
        "half_life": half_life,
        "code_commit": code_commit,
        "strategies": STRATEGIES,
        "sampler_version": SAMPLER_VERSION,
        "calibration_version": CALIBRATION_VERSION,
        "calibration_tolerance": CALIBRATION_TOLERANCE,
    }
    generation_run_id = hashlib.sha256(
        json.dumps(run_identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    candidates: dict[str, list[dict[str, Any]]] = {}
    strategy_metadata: dict[str, dict[str, Any]] = {}
    for strategy_index, strategy in enumerate(STRATEGIES):
        front_weights = _probabilities(
            records, "front_numbers", FRONT_SIZE, FRONT_PICK,
            model=strategy, alpha=alpha, half_life=half_life,
        )
        back_weights = _probabilities(
            records, "back_numbers", BACK_SIZE, BACK_PICK,
            model=strategy, alpha=alpha, half_life=half_life,
        )
        front_sampler, front_calibration = _calibrated_sampler(front_weights, FRONT_PICK)
        back_sampler, back_calibration = _calibrated_sampler(back_weights, BACK_PICK)
        slot_seed = seed + strategy_index * SLOT_SEED_STRIDE
        rng = random.Random(slot_seed)
        tickets = []
        for ticket_index in range(tickets_per_strategy):
            front = _sample_ticket_subset(front_sampler, rng)
            back = _sample_ticket_subset(back_sampler, rng)
            ticket_id = hashlib.sha256(
                f"{generation_run_id}:{strategy}:{ticket_index + 1}".encode("utf-8")
            ).hexdigest()[:24]
            tickets.append({
                "ticket": ticket_index + 1,
                "ticket_id": ticket_id,
                "front_numbers": front,
                "back_numbers": back,
            })
        candidates[strategy] = tickets
        lane_counts: dict[tuple[tuple[int, ...], tuple[int, ...]], int] = {}
        for ticket in tickets:
            combination = (tuple(ticket["front_numbers"]), tuple(ticket["back_numbers"]))
            lane_counts[combination] = lane_counts.get(combination, 0) + 1
        strategy_metadata[strategy] = {
            "strategy": strategy,
            "slot_seed": slot_seed,
            "ticket_count": len(tickets),
            "unique_ticket_combinations": len(lane_counts),
            "duplicate_ticket_count": sum(count - 1 for count in lane_counts.values()),
            "training_cutoff_draw_id": records[-1]["draw_id"],
            "sampling_method": "exact conditional-Poisson rejective sampling; with replacement across tickets",
            "front_marginal_calibration": front_calibration,
            "back_marginal_calibration": back_calibration,
        }

    global_counts: dict[tuple[tuple[int, ...], tuple[int, ...]], int] = {}
    lane_presence: dict[tuple[tuple[int, ...], tuple[int, ...]], set[str]] = {}
    for strategy, tickets in candidates.items():
        for ticket in tickets:
            combination = (tuple(ticket["front_numbers"]), tuple(ticket["back_numbers"]))
            global_counts[combination] = global_counts.get(combination, 0) + 1
            lane_presence.setdefault(combination, set()).add(strategy)
    duplicate_ticket_count = sum(count - 1 for count in global_counts.values())
    cross_lane_duplicate_combination_count = sum(
        len(lanes) > 1 for lanes in lane_presence.values()
    )

    return {
        "schema_version": 2,
        "purpose": "exploratory_ticket_candidates",
        "generated_seed": seed,
        "generation_run_id": generation_run_id,
        "code_commit": code_commit,
        "total_tickets": tickets_per_strategy * len(STRATEGIES),
        "unique_ticket_combinations": len(global_counts),
        "duplicate_ticket_count": duplicate_ticket_count,
        "cross_lane_duplicate_combination_count": cross_lane_duplicate_combination_count,
        "tickets_per_strategy": tickets_per_strategy,
        "maximum_tickets_per_strategy": MAX_TICKETS_PER_STRATEGY,
        "training_draw_count": len(records),
        "training_dataset_fingerprint": dataset_fingerprint,
        "strategy_metadata": strategy_metadata,
        "rng": {
            "algorithm": "Python random.Random (MT19937)",
            "slot_seed_derivation": f"master_seed + slot_index * {SLOT_SEED_STRIDE}",
        },
        "training_first_draw_id": records[0]["draw_id"],
        "training_last_draw_id": records[-1]["draw_id"],
        "model_configuration": {
            "expanding_alpha_pseudo_draws": alpha,
            "ewma_half_life_draws": half_life,
            "sampling": "conditional-Poisson rejective distribution calibrated to the supplied inclusion marginals",
            "sampler_version": SAMPLER_VERSION,
            "calibration_version": CALIBRATION_VERSION,
            "calibration_tolerance": CALIBRATION_TOLERANCE,
            "calibration_max_iterations": CALIBRATION_MAX_ITERATIONS,
            "calibration_history_size": CALIBRATION_HISTORY_SIZE,
        },
        "strategies": candidates,
        "limitations": [
            "Historical candidate data may be unverified; this tool does not authenticate its input.",
            "The conditional-Poisson joint distribution matches the requested first-order inclusion marginals; its higher-order dependence structure is a rejective-sampling assumption, not a demonstrated predictive edge.",
            "No out-of-sample advantage over the legal uniform baseline has been established.",
            "Strategy labels are computational variants, not physical lottery ball-set identities.",
            "Each ticket is a legal combination, not a prediction or guarantee.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="chronological draw JSONL")
    parser.add_argument("--tickets", type=int, default=1,
                        help="tickets generated per strategy (default: 1)")
    parser.add_argument("--seed", type=int, default=20261119)
    parser.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    parser.add_argument("--half-life", type=float, default=100.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        validation = validate_jsonl(args.dataset)
        raw = args.dataset.read_bytes()
        rows = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
        report = generate_ticket_candidates(
            rows, tickets_per_strategy=args.tickets, seed=args.seed,
            alpha=args.alpha, half_life=args.half_life,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"TICKET_GENERATION_FAILED: {exc}", file=sys.stderr)
        return 1
    report["dataset"] = {
        "path": str(args.dataset),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "validation": validation,
        "trust_status": "not_authenticated_by_this_tool",
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
