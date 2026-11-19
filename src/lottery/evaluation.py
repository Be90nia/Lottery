"""Frozen paired regression gate for per-draw lottery model scores.

This creates review evidence only. It never tunes models, changes a champion,
or reads the protected prospective holdout.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from typing import Any, Iterable

ZONES = ("front", "back")
METRICS = ("brier", "log_loss")
MODELS = ("candidate", "champion", "uniform")
RECEIPT_SCHEMA = "lot-073-evaluation-receipt-v1"


class EvaluationGateError(ValueError):
    """Raised when evaluation evidence is incomplete or inconsistent."""


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _validate_sha(value: str, field: str) -> None:
    if (not isinstance(value, str) or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise EvaluationGateError(f"{field} must be a lowercase SHA-256 digest")


def _bootstrap(values: list[float], *, replicates: int,
               block_length: int, seed: int) -> dict[str, float | int]:
    if not values:
        raise EvaluationGateError("paired score series must not be empty")
    n = len(values)
    block = min(block_length, n)
    rng = random.Random(seed)
    samples = []
    for _ in range(replicates):
        sample = []
        while len(sample) < n:
            start = rng.randrange(0, n - block + 1)
            sample.extend(values[start:start + block])
        samples.append(sum(sample[:n]) / n)
    samples.sort()
    return {
        "mean_delta": sum(values) / n,
        "ci_95_lower": samples[int(0.025 * (replicates - 1))],
        "ci_95_upper": samples[int(0.975 * (replicates - 1))],
        "replicates": replicates,
        "block_length_draws": block,
        "seed": seed,
    }


def build_evaluation_receipt(
    score_rows: Iterable[dict[str, Any]], *,
    candidate_model_id: str,
    champion_model_id: str,
    dataset_sha256: str,
    code_commit: str,
    protocol_version: str,
    scope: str = "rolling_origin",
    min_targets: int = 200,
    replicates: int = 1000,
    block_length: int = 50,
    seed: int = 20261119,
) -> dict[str, Any]:
    """Build a deterministic receipt from chronological per-target scores.

    Each row has target_draw_id and model_scores[model][zone][metric].
    Negative candidate-minus-reference deltas are improvements.
    """
    _validate_sha(dataset_sha256, "dataset_sha256")
    if (not isinstance(code_commit, str) or len(code_commit) != 40
            or any(c not in "0123456789abcdef" for c in code_commit)):
        raise EvaluationGateError("code_commit must be a full lowercase Git SHA")
    if (not isinstance(candidate_model_id, str) or not candidate_model_id
            or not isinstance(champion_model_id, str) or not champion_model_id
            or candidate_model_id == champion_model_id):
        raise EvaluationGateError("candidate and champion model IDs must be distinct non-empty strings")
    if not isinstance(protocol_version, str) or not protocol_version:
        raise EvaluationGateError("protocol_version must be a non-empty string")
    if scope not in ("rolling_origin", "shadow"):
        raise EvaluationGateError("scope must be rolling_origin or shadow; prospective holdout is forbidden")
    if (type(min_targets) is not int or min_targets < 200
            or type(replicates) is not int or replicates < 1000
            or type(block_length) is not int or block_length < 50
            or block_length > min_targets // 2
            or type(seed) is not int or seed < 0):
        raise EvaluationGateError(
            "frozen gate requires >=200 targets, >=1000 replicates, "
            "50<=block_length<=min_targets/2, and a non-negative integer seed"
        )

    rows = list(score_rows)
    if len(rows) < min_targets:
        raise EvaluationGateError(f"incomplete coverage: {len(rows)} targets; need {min_targets}")
    targets = []
    seen = set()
    previous_target_number = None
    previous_target_number = None
    deltas = {
        reference: {zone: {metric: [] for metric in METRICS} for zone in ZONES}
        for reference in ("champion", "uniform")
    }
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise EvaluationGateError(f"score row {index} must be an object")
        target = row.get("target_draw_id")
        if (not isinstance(target, str) or len(target) != 5
                or not target.isdigit() or target in seen):
            raise EvaluationGateError(f"score row {index} has a missing, malformed, or duplicate target")
        target_number = int(target)
        if previous_target_number is not None and target_number <= previous_target_number:
            raise EvaluationGateError("score rows must be in strictly increasing draw-ID order")
        previous_target_number = target_number
        seen.add(target)
        targets.append(target)
        models = row.get("model_scores")
        if not isinstance(models, dict) or set(models) != set(MODELS):
            raise EvaluationGateError(f"target {target}: scores must contain candidate, champion, uniform")
        for model in MODELS:
            if not isinstance(models[model], dict) or set(models[model]) != set(ZONES):
                raise EvaluationGateError(f"target {target}: invalid {model} zones")
            for zone in ZONES:
                values = models[model][zone]
                if not isinstance(values, dict) or set(values) != set(METRICS):
                    raise EvaluationGateError(f"target {target}: invalid {model} {zone} metrics")
                for metric in METRICS:
                    value = values[metric]
                    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                        raise EvaluationGateError(f"target {target}: invalid {model} {zone} {metric}")
        for reference in ("champion", "uniform"):
            for zone in ZONES:
                for metric in METRICS:
                    deltas[reference][zone][metric].append(
                        float(models["candidate"][zone][metric]) -
                        float(models[reference][zone][metric])
                    )

    comparisons = {}
    all_strictly_better = True
    for reference in ("champion", "uniform"):
        comparisons[reference] = {}
        for zone in ZONES:
            comparisons[reference][zone] = {}
            for metric in METRICS:
                result = _bootstrap(deltas[reference][zone][metric],
                                    replicates=replicates,
                                    block_length=block_length,
                                    seed=seed)
                comparisons[reference][zone][metric] = result
                if result["ci_95_upper"] >= 0:
                    all_strictly_better = False

    decision = "eligible_for_human_review" if all_strictly_better else "rejected_or_inconclusive"
    body = {
        "schema": RECEIPT_SCHEMA,
        "candidate_model_id": candidate_model_id,
        "champion_model_id": champion_model_id,
        "dataset_sha256": dataset_sha256,
        "code_commit": code_commit,
        "protocol_version": protocol_version,
        "scope": scope,
        "target_count": len(targets),
        "score_rows_sha256": hashlib.sha256(_canonical({"score_rows": rows})).hexdigest(),
        "evaluation_config": {
            "min_targets": min_targets,
            "bootstrap_replicates": replicates,
            "block_length_draws": block_length,
            "bootstrap_seed": seed,
        },
        "first_target_draw_id": targets[0],
        "last_target_draw_id": targets[-1],
        "target_draw_ids_sha256": hashlib.sha256(
            _canonical({"target_draw_ids": targets})
        ).hexdigest(),
        "comparison": "paired candidate-minus-reference per-target scores; negative is better",
        "comparisons": comparisons,
        "decision": decision,
        "production_ready": False,
        "automatic_promotion": False,
    }
    return {**body, "receipt_sha256": _digest(body)}


def verify_evaluation_receipt(receipt: dict[str, Any]) -> bool:
    if not isinstance(receipt, dict) or "receipt_sha256" not in receipt:
        raise EvaluationGateError("receipt or receipt hash is missing")
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    _validate_sha(receipt["receipt_sha256"], "receipt_sha256")
    if _digest(body) != receipt["receipt_sha256"]:
        raise EvaluationGateError("receipt hash mismatch")
    if body.get("schema") != RECEIPT_SCHEMA:
        raise EvaluationGateError("unsupported receipt schema")
    if body.get("scope") not in ("rolling_origin", "shadow"):
        raise EvaluationGateError("receipt scope is forbidden or invalid")
    _validate_sha(body.get("dataset_sha256"), "dataset_sha256")
    _validate_sha(body.get("score_rows_sha256"), "score_rows_sha256")
    _validate_sha(body.get("target_draw_ids_sha256"), "target_draw_ids_sha256")
    config = body.get("evaluation_config")
    if (not isinstance(config, dict) or type(config.get("min_targets")) is not int
            or config["min_targets"] < 200
            or type(config.get("bootstrap_replicates")) is not int
            or config["bootstrap_replicates"] < 1000
            or type(config.get("block_length_draws")) is not int
            or config["block_length_draws"] < 50
            or config["block_length_draws"] > config["min_targets"] // 2
            or type(config.get("bootstrap_seed")) is not int
            or config["bootstrap_seed"] < 0
            or type(body.get("target_count")) is not int
            or body["target_count"] < config["min_targets"]):
        raise EvaluationGateError("receipt evaluation configuration is invalid")
    code_commit = body.get("code_commit")
    if (not isinstance(code_commit, str) or len(code_commit) != 40
            or any(char not in "0123456789abcdef" for char in code_commit)):
        raise EvaluationGateError("receipt code_commit is invalid")
    candidate_id = body.get("candidate_model_id")
    champion_id = body.get("champion_model_id")
    if (not isinstance(candidate_id, str) or not candidate_id.strip()
            or not isinstance(champion_id, str) or not champion_id.strip()
            or candidate_id == champion_id):
        raise EvaluationGateError("receipt model IDs are invalid")
    if not isinstance(body.get("protocol_version"), str) or not body["protocol_version"].strip():
        raise EvaluationGateError("receipt protocol version is invalid")
    comparisons = body.get("comparisons")
    if not isinstance(comparisons, dict) or set(comparisons) != {"champion", "uniform"}:
        raise EvaluationGateError("receipt comparisons are incomplete")
    all_strictly_better = True
    for reference in ("champion", "uniform"):
        if not isinstance(comparisons[reference], dict) or set(comparisons[reference]) != set(ZONES):
            raise EvaluationGateError("receipt comparison zones are incomplete")
        for zone in ZONES:
            zone_results = comparisons[reference][zone]
            if not isinstance(zone_results, dict) or set(zone_results) != set(METRICS):
                raise EvaluationGateError("receipt comparison metrics are incomplete")
            for metric in METRICS:
                result = zone_results[metric]
                if not isinstance(result, dict):
                    raise EvaluationGateError("receipt bootstrap result is invalid")
                lower, upper, mean = (
                    result.get("ci_95_lower"), result.get("ci_95_upper"),
                    result.get("mean_delta"),
                )
                if (any(type(value) not in (int, float) or not math.isfinite(value)
                        for value in (lower, upper, mean))
                        or lower > upper
                        or result.get("replicates") != config["bootstrap_replicates"]
                        or result.get("block_length_draws") != config["block_length_draws"]
                        or result.get("seed") != config["bootstrap_seed"]):
                    raise EvaluationGateError("receipt bootstrap result/configuration mismatch")
                if upper >= 0:
                    all_strictly_better = False
    expected_decision = "eligible_for_human_review" if all_strictly_better else "rejected_or_inconclusive"
    if body.get("decision") != expected_decision:
        raise EvaluationGateError("receipt decision does not match paired interval results")
    if body.get("production_ready") is not False or body.get("automatic_promotion") is not False:
        raise EvaluationGateError("evaluation receipt cannot authorize production or promotion")
    return True
