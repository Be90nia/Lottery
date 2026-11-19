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
from pathlib import Path
import sys
from typing import Any, Iterable

from .backtest import (
    BACK_PICK, BACK_SIZE, DEFAULT_ALPHA, FRONT_PICK, FRONT_SIZE,
    _probabilities, _validate_rows,
)
from .validate import validate_jsonl


STRATEGIES = ("uniform", "expanding", "ewma")
MAX_TICKETS_PER_STRATEGY = 100
SLOT_SEED_STRIDE = 1_000_003


def _weighted_sample_without_replacement(
    probabilities: list[float], count: int, rng: random.Random
) -> list[int]:
    if count < 1 or count > len(probabilities):
        raise ValueError("sample count must be between 1 and pool size")
    if any(not math.isfinite(weight) or weight < 0 for weight in probabilities):
        raise ValueError("weights must be finite and non-negative")
    remaining = list(enumerate(probabilities, start=1))
    selected: list[int] = []
    for _ in range(count):
        total = sum(weight for _, weight in remaining)
        if total <= 0:
            raise ValueError("weights must have positive remaining mass")
        threshold = rng.random() * total
        cumulative = 0.0
        chosen_index = len(remaining) - 1
        for index, (_, weight) in enumerate(remaining):
            cumulative += weight
            if threshold < cumulative:
                chosen_index = index
                break
        number, _ = remaining.pop(chosen_index)
        selected.append(number)
    return sorted(selected)


def generate_ticket_candidates(
    rows: Iterable[dict[str, Any]], *, tickets_per_strategy: int = 1,
    seed: int = 20261119, alpha: float = DEFAULT_ALPHA,
    half_life: float = 100.0,
) -> dict[str, Any]:
    if type(tickets_per_strategy) is not int or not 1 <= tickets_per_strategy <= MAX_TICKETS_PER_STRATEGY:
        raise ValueError(f"tickets_per_strategy must be an integer in 1..{MAX_TICKETS_PER_STRATEGY}")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    if not math.isfinite(alpha) or alpha <= 0:
        raise ValueError("alpha must be finite and positive")
    if not math.isfinite(half_life) or half_life <= 0:
        raise ValueError("half_life must be finite and positive")

    records = _validate_rows(rows)
    canonical_rows = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    dataset_fingerprint = hashlib.sha256(canonical_rows).hexdigest()
    run_identity = {
        "dataset_fingerprint": dataset_fingerprint,
        "seed": seed,
        "tickets_per_strategy": tickets_per_strategy,
        "alpha": alpha,
        "half_life": half_life,
        "strategies": STRATEGIES,
        "sampler_version": "sequential-weighted-without-replacement-v1",
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
        slot_seed = seed + strategy_index * SLOT_SEED_STRIDE
        rng = random.Random(slot_seed)
        tickets = []
        for ticket_index in range(tickets_per_strategy):
            front = _weighted_sample_without_replacement(front_weights, FRONT_PICK, rng)
            back = _weighted_sample_without_replacement(back_weights, BACK_PICK, rng)
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
        strategy_metadata[strategy] = {
            "strategy": strategy,
            "slot_seed": slot_seed,
            "ticket_count": len(tickets),
            "training_cutoff_draw_id": records[-1]["draw_id"],
            "sampling_method": "sequential weighted sampling without replacement",
        }

    return {
        "schema_version": 1,
        "purpose": "exploratory_ticket_candidates",
        "generated_seed": seed,
        "generation_run_id": generation_run_id,
        "total_tickets": tickets_per_strategy * len(STRATEGIES),
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
            "sampling": "sequential weighted sampling without replacement",
            "sampler_version": "sequential-weighted-without-replacement-v1",
        },
        "strategies": candidates,
        "limitations": [
            "Historical candidate data may be unverified; this tool does not authenticate its input.",
            "Marginal inclusion weights do not define a calibrated joint ticket probability.",
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
