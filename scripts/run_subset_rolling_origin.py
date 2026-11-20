"""Frozen-snapshot exact-subset rolling-origin evaluation runner.

This runner is equipment-blind and does not read LOT-042 holdout data or
ball-set metadata. It is an implementation evaluation, not a promotion tool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import sys
from pathlib import Path

from lottery.backtest import _probabilities
from lottery.subset_model.artifact import canonicalize, create_artifact, verify_artifact
from lottery.subset_model.rolling_origin_ledger import write_immutable_outputs
from lottery.subset_model import (
    BACK_POPULATION,
    BACK_SELECTION,
    FRONT_POPULATION,
    FRONT_SELECTION,
    ExponentialFamily,
    ConditionalPoisson,
    build_uniform_feature_table,
)

EXPECTED_SHA256 = "9f4cc51b76fd258dd056e0b86f675192d3d9a41c2901f771cab778c65ec2b6aa"
EXPECTED_ROWS = 2949
MIN_TRAIN = 300
BOOTSTRAP_REPLICATES = 1000
BOOTSTRAP_BLOCK = 50
BOOTSTRAP_SEED = 20261118


def _confirmatory_gate(
    inferential_pass: bool, *, experiment_registration_approved: bool,
    solver_policy_approved: bool, multiplicity_policy_approved: bool,
    non_regression_policy_approved: bool, non_regression_pass: bool,
) -> bool:
    return bool(
        inferential_pass
        and experiment_registration_approved
        and solver_policy_approved
        and multiplicity_policy_approved
        and non_regression_policy_approved
        and non_regression_pass
    )


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _moving_block_bootstrap(values: list[float], seed: int) -> dict:
    """Use one fixed block-resample stream for both CI and null-centered test."""
    n = len(values)
    if n < BOOTSTRAP_BLOCK:
        raise ValueError("not enough paired targets for the preregistered block length")
    if any(not math.isfinite(value) for value in values):
        raise ValueError("paired score differences must all be finite")

    rng = random.Random(seed)
    observed = sum(values) / n
    null_centered = [value - observed for value in values]
    means = []
    null_means = []
    for _ in range(BOOTSTRAP_REPLICATES):
        indices = []
        while len(indices) < n:
            start = rng.randrange(0, n - BOOTSTRAP_BLOCK + 1)
            indices.extend(range(start, start + BOOTSTRAP_BLOCK))
        indices = indices[:n]
        # The exact same sampled chronological blocks feed the percentile CI
        # and the null-centered one-sided test.
        means.append(sum(values[index] for index in indices) / n)
        null_means.append(sum(null_centered[index] for index in indices) / n)

    p_value = (
        1 + sum(statistic <= observed for statistic in null_means)
    ) / (BOOTSTRAP_REPLICATES + 1)
    return {
        "observed_mean_delta_candidate_minus_reference": observed,
        "ci_95_lower": _percentile(means, 0.025),
        "ci_95_upper": _percentile(means, 0.975),
        "one_sided_null_centered_p_value": p_value,
        "replicates": BOOTSTRAP_REPLICATES,
        "block_length_draws": BOOTSTRAP_BLOCK,
        "seed": seed,
        "method": "paired non-circular moving-block bootstrap; same block indices for percentile CI and null-centered one-sided test",
        "null_test": {
            "alternative": "mean_delta_less_than_zero",
            "null_series": "d_t_minus_observed_mean_delta",
            "tail": "bootstrap_null_mean_less_than_or_equal_to_observed_mean_delta",
            "p_value_correction": "(1 + exceedances) / (replicates + 1)",
        },
    }


def _holm_adjust(p_values: dict[str, float], alpha: float = 0.05) -> dict:
    """Holm step-down adjusted p-values for a preregistered finite family."""
    if not p_values:
        raise ValueError("Holm family must contain at least one hypothesis")
    if not math.isfinite(alpha) or not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be finite and strictly between zero and one")
    for name, value in p_values.items():
        if not isinstance(name, str) or not name:
            raise ValueError("hypothesis names must be non-empty strings")
        if type(value) not in (int, float) or not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(f"invalid p-value for {name}")
    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    adjusted = {}
    running_max = 0.0
    family_size = len(ordered)
    for rank, (name, value) in enumerate(ordered):
        running_max = max(running_max, (family_size - rank) * value)
        adjusted[name] = min(1.0, running_max)
    return adjusted


def _load_and_validate(path: Path) -> tuple[list[dict], str]:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError(f"snapshot SHA-256 mismatch: expected {EXPECTED_SHA256}, got {digest}")
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]
    if len(rows) != EXPECTED_ROWS:
        raise ValueError(f"snapshot row count mismatch: expected {EXPECTED_ROWS}, got {len(rows)}")
    if rows[0]["draw_id"] != "07001" or rows[MIN_TRAIN]["draw_id"] != "09054":
        raise ValueError("frozen rolling-origin target boundary mismatch")
    if rows[-1]["draw_id"] != "26131":
        raise ValueError("frozen snapshot final draw mismatch")
    previous_id = None
    previous_date = None
    for row in rows:
        draw_id, draw_date = row["draw_id"], row["draw_date"]
        if previous_id is not None and (draw_id <= previous_id or draw_date <= previous_date):
            raise ValueError("draw inventory is not strictly chronological")
        front, back = row["front_numbers"], row["back_numbers"]
        if (len(front) != FRONT_SELECTION or len(set(front)) != FRONT_SELECTION
                or front != sorted(front)
                or any(type(x) is not int or not 1 <= x <= FRONT_POPULATION for x in front)):
            raise ValueError(f"invalid front subset at draw {draw_id}")
        if (len(back) != BACK_SELECTION or len(set(back)) != BACK_SELECTION
                or back != sorted(back)
                or any(type(x) is not int or not 1 <= x <= BACK_POPULATION for x in back)):
            raise ValueError(f"invalid back subset at draw {draw_id}")
        previous_id, previous_date = draw_id, draw_date
    if len({row["draw_id"] for row in rows}) != len(rows):
        raise ValueError("duplicate draw IDs in frozen snapshot")
    return rows, digest



def _checkpoint_record_hash(record: dict) -> str:
    body = {key: value for key, value in record.items() if key != "record_sha256"}
    return hashlib.sha256(canonicalize(body)).hexdigest()


def _jcs_hash(value: dict) -> str:
    return "sha256:" + hashlib.sha256(canonicalize(value)).hexdigest()


def _finite_or_none(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _create_fit_failure_artifact(*, model_family: str, zone: str, population_size: int,
                                 selection_size: int, snapshot_digest: str,
                                 training_rows: list[dict], code_revision: str,
                                 feature_schema: dict, model_configuration: dict,
                                 status: str, reason: str, objective,
                                 gradient_inf_norm, iterations: int, optimizer: str,
                                 regularization_lambda, rng_algorithm: str) -> dict:
    runtime = {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
    }
    feature_schema_hash = _jcs_hash(feature_schema)
    config = dict(model_configuration)
    config["feature_schema_hash"] = feature_schema_hash
    payload = {
        "schema_version": 1,
        "artifact_schema": "lottery.subset-probability-model/v1",
        "artifact_type": "fit_failure",
        "model_family": model_family, "zone": zone,
        "population_size": population_size, "selection_size": selection_size,
        "support": {
            "population_size": population_size, "selection_size": selection_size,
            "support_count": math.comb(population_size, selection_size),
            "subset_order": "lexicographic_ascending",
        },
        "feature_schema": feature_schema,
        "feature_schema_hash": feature_schema_hash,
        "model_configuration": config,
        "model_configuration_hash": _jcs_hash(config),
        "parameters": {
            "parameter_order": "feature_schema.names",
            "parameters_available": False,
        },
        "normalization": {
            "method": "not_computed", "log_partition": None, "numeric_dtype": "float64",
        },
        "fit": {
            "status": status, "termination_reason": reason or status,
            "objective": _finite_or_none(objective),
            "gradient_inf_norm": _finite_or_none(gradient_inf_norm),
            "iterations": int(iterations or 0), "optimizer": optimizer,
            "lambda": regularization_lambda,
        },
        "training": {
            "snapshot_sha256": snapshot_digest, "row_count": len(training_rows),
            "first_draw_id": training_rows[0]["draw_id"],
            "last_draw_id": training_rows[-1]["draw_id"],
            "cutoff_draw_id": training_rows[-1]["draw_id"],
            "cutoff_inclusive": True,
        },
        "implementation": {
            "code_revision": code_revision, "runtime": runtime,
            "library_versions": {}, "rng_algorithm": rng_algorithm,
        },
        "training_snapshot_sha256": snapshot_digest,
        "training_first_draw_id": training_rows[0]["draw_id"],
        "training_last_draw_id": training_rows[-1]["draw_id"],
        "training_cutoff_draw_id": training_rows[-1]["draw_id"],
        "training_row_count": len(training_rows),
        "code_revision": code_revision, "runtime": runtime,
        "fit_diagnostics": {
            "terminal_status": status, "converged": False,
            "message": reason, "iterations": int(iterations or 0),
            "gradient_infinity_norm": _finite_or_none(gradient_inf_norm),
            "objective": _finite_or_none(objective),
        },
        "failure_reason": reason or status,
        "forecast_ready": False,
    }
    raw, artifact_id = create_artifact(payload)
    return {"artifact_id": artifact_id, "payload": verify_artifact(raw)}


def _validate_checkpoint_record(record: dict, *, row: dict, zone: str,
                                training_count: int, uniform_nll: float) -> None:
    expected_record_keys = {
        "record_type", "target_draw_id", "target_draw_date", "training_count",
        "training_first_draw_id", "training_last_draw_id", "training_cutoff_draw_id",
        "training_cutoff_date", "training_dates_strictly_before_target",
        "observed_subset", "fit_statuses", "exact_set_nll", "model_artifacts",
        "candidate_iterations", "candidate_gradient_infinity_norm", "record_sha256",
    }
    if (not isinstance(record, dict) or set(record) != expected_record_keys
            or record.get("record_type") != "target"):
        raise ValueError("checkpoint target record has invalid shape")
    supplied_hash = record.get("record_sha256")
    if not isinstance(supplied_hash, str) or supplied_hash != _checkpoint_record_hash(record):
        raise ValueError("checkpoint target record SHA-256 mismatch")
    if type(record.get("candidate_iterations")) is not int or record["candidate_iterations"] < 0:
        raise ValueError("checkpoint candidate iteration count is invalid")
    gradient = record.get("candidate_gradient_infinity_norm")
    if type(gradient) not in (int, float) or not math.isfinite(gradient) or gradient < 0:
        raise ValueError("checkpoint candidate gradient diagnostic is invalid")
    expected_statuses = {"candidate", "expanding", "ewma"}
    expected_scores = {"uniform", "expanding", "ewma", "exponential_family"}
    if not isinstance(record.get("fit_statuses"), dict) or set(record["fit_statuses"]) != expected_statuses:
        raise ValueError("checkpoint fit_statuses schema mismatch")
    if not isinstance(record.get("exact_set_nll"), dict) or set(record["exact_set_nll"]) != expected_scores:
        raise ValueError("checkpoint exact_set_nll schema mismatch")
    if (record.get("target_draw_id") != row["draw_id"]
            or record.get("target_draw_date") != row["draw_date"]
            or record.get("training_count") != training_count
            or record.get("training_first_draw_id") != "07001"
            or record.get("training_last_draw_id") != record.get("training_cutoff_draw_id")):
        raise ValueError("checkpoint target order/training range mismatch")
    if record.get("training_dates_strictly_before_target") is not True:
        raise ValueError("checkpoint strict-before-target assertion is missing")
    if record.get("observed_subset") != row[f"{zone}_numbers"]:
        raise ValueError("checkpoint observed subset does not match target")
    if not isinstance(record.get("training_cutoff_draw_id"), str) or not record["training_cutoff_draw_id"]:
        raise ValueError("checkpoint training cutoff is missing")
    artifacts = record.get("model_artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {"candidate", "expanding", "ewma"}:
        raise ValueError("checkpoint model artifact map is invalid")
    for name, entry in artifacts.items():
        if entry is None:
            raise ValueError(f"{name} fit attempt is missing its immutable model/failure artifact")
        if not isinstance(entry, dict) or set(entry) != {"artifact_id", "payload"}:
            raise ValueError(f"checkpoint {name} artifact entry has invalid shape")
        verified = verify_artifact(canonicalize(entry["payload"]))
        if verified.get("artifact_id") != entry["artifact_id"]:
            raise ValueError(f"checkpoint {name} artifact ID mismatch")
        expected_type = "fitted_model" if record["fit_statuses"][name] == "converged" else "fit_failure"
        if verified.get("artifact_type") != expected_type:
            raise ValueError(f"checkpoint {name} artifact type does not match fit terminal status")
        expected_family = "complete_subset_exponential" if name == "candidate" else "conditional_poisson"
        if (verified.get("zone") != zone or verified.get("model_family") != expected_family
                or verified.get("training_row_count") != training_count
                or verified.get("training_cutoff_draw_id") != record["training_cutoff_draw_id"]):
            raise ValueError(f"checkpoint {name} artifact provenance mismatch")
    if any(not isinstance(status, str) or not status for status in record["fit_statuses"].values()):
        raise ValueError("checkpoint fit status must be a non-empty string")
    scores = record["exact_set_nll"]
    if type(scores["uniform"]) not in (int, float) or not math.isfinite(scores["uniform"]):
        raise ValueError("checkpoint uniform NLL must be finite")
    if abs(scores["uniform"] - uniform_nll) > 1e-10:
        raise ValueError("checkpoint uniform NLL does not match legal support")
    for status_key, score_key in (
        ("candidate", "exponential_family"),
        ("expanding", "expanding"),
        ("ewma", "ewma"),
    ):
        score = scores[score_key]
        if record["fit_statuses"][status_key] == "converged":
            if type(score) not in (int, float) or not math.isfinite(score) or score < -1e-10:
                raise ValueError(f"checkpoint {score_key} NLL invalid for converged fit")
        elif score is not None:
            raise ValueError(f"checkpoint {score_key} score must be null when fit did not converge")


def _evaluate_zone(rows: list[dict], zone: str, m: int, k: int, include_gap: bool,
                   seed: int, checkpoint_path: Path, snapshot_digest: str) -> dict:
    table = build_uniform_feature_table(m, k, include_gap_variance=include_gap)
    model = ExponentialFamily(table)
    field = f"{zone}_numbers"
    observations = [tuple(row[field]) for row in rows]
    uniform_nll = math.log(math.comb(m, k))
    expected = len(rows) - MIN_TRAIN
    header = {
        "record_type": "header", "schema": "lot-055-checkpoint-v3",
        "snapshot_sha256": snapshot_digest,
        "snapshot_source_commit": os.environ.get("RESEARCH_SNAPSHOT_COMMIT", "unverified-local-input"),
        "snapshot_trust_status": os.environ.get("RESEARCH_SNAPSHOT_TRUST_STATUS", "not_verified_by_runner"),
        "code_commit": os.environ.get("RESEARCH_CODE_COMMIT", os.environ.get("GITHUB_SHA", "local")),
        "zone": zone,
        "minimum_training_rows": MIN_TRAIN, "first_target": rows[MIN_TRAIN]["draw_id"],
        "last_target": rows[-1]["draw_id"], "models": ["uniform", "expanding", "ewma", "exponential_family"],
        "alpha": 100.0, "ewma_half_life": 100.0,
    }
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    records = []
    if checkpoint_path.exists():
        lines = checkpoint_path.read_text(encoding="utf-8").splitlines()
        if not lines or json.loads(lines[0]) != header:
            raise ValueError(f"checkpoint header mismatch: {checkpoint_path}")
        if len(lines) - 1 > expected:
            raise ValueError(f"checkpoint has too many records: {checkpoint_path}")
        for offset, line in enumerate(lines[1:]):
            record = json.loads(line)
            idx = MIN_TRAIN + offset
            _validate_checkpoint_record(
                record, row=rows[idx], zone=zone, training_count=idx,
                uniform_nll=uniform_nll,
            )
            if (record.get("training_cutoff_draw_id") != rows[idx - 1]["draw_id"]
                    or record.get("training_cutoff_date") != rows[idx - 1]["draw_date"]
                    or any(item["draw_date"] >= rows[idx]["draw_date"] for item in rows[:idx])):
                raise ValueError(f"checkpoint cutoff/date leakage mismatch at target index {idx}")
            records.append(record)
    else:
        with checkpoint_path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(header, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    status_counts = {name: {} for name in ("candidate", "expanding", "ewma")}
    def count_status(record):
        for name, status in record["fit_statuses"].items():
            bucket = status_counts[name]
            bucket[status] = bucket.get(status, 0) + 1
    for record in records:
        count_status(record)

    with checkpoint_path.open("a", encoding="utf-8") as checkpoint:
        for idx in range(MIN_TRAIN + len(records), len(rows)):
            training = rows[:idx]
            target = observations[idx]
            fit = model.fit(observations[:idx])
            statuses = {"candidate": fit.terminal_status}
            scores = {"uniform": uniform_nll}
            model_artifacts = {"candidate": None, "expanding": None, "ewma": None}
            candidate = -model.log_probability(target, fit.theta) if fit.converged else None
            active_features = list(model.table.stats.feature_names)
            feature_schema = {
                "version": model.table.stats.feature_schema_version,
                "names": active_features,
                "uniform_means": list(model.table.stats.means),
                "uniform_population_stds": list(model.table.stats.standard_deviations),
                "zero_variance_policy": "drop_and_record",
                "candidate_names": list(model.table.stats.candidate_feature_names),
                "zero_variance_features": list(model.table.stats.zero_variance_features),
            }
            candidate_config = {
                "model_family": "complete_subset_exponential", "zone": zone,
                "population_size": m, "selection_size": k,
                "feature_schema_hash": _jcs_hash(feature_schema),
                "objective_scale": fit.objective_scale,
                "regularization_lambda": fit.regularization_lambda,
                "solver": fit.solver, "max_iterations": 5000,
                "gradient_tolerance": 1e-8,
            }
            if fit.converged:
                candidate_payload = {
                    "schema_version": 1, "model_family": "complete_subset_exponential",
                    "zone": zone, "population_size": m, "selection_size": k,
                    "training_snapshot_sha256": snapshot_digest,
                    "training_first_draw_id": rows[0]["draw_id"],
                    "training_last_draw_id": rows[idx - 1]["draw_id"],
                    "training_cutoff_draw_id": rows[idx - 1]["draw_id"],
                    "training_row_count": idx, "code_revision": header["code_commit"],
                    "runtime": {"python": platform.python_version(),
                                "implementation": platform.python_implementation()},
                    "fit_diagnostics": {
                        "terminal_status": fit.terminal_status, "converged": fit.converged,
                        "message": fit.message, "iterations": fit.iterations,
                        "gradient_infinity_norm": fit.gradient_infinity_norm,
                        "unregularized_mean_nll": fit.unregularized_mean_nll,
                        "penalized_objective": fit.penalized_objective,
                        "solver": fit.solver,
                    },
                    "forecast_ready": False,
                    "artifact_schema": "lottery.subset-probability-model/v1",
                    "artifact_type": "fitted_model",
                    "support": {"population_size": m, "selection_size": k,
                                "support_count": math.comb(m, k),
                                "subset_order": "lexicographic_ascending"},
                    "feature_schema": feature_schema,
                    "parameters": {"theta": list(fit.theta),
                                   "parameter_order": "feature_schema.names"},
                    "fit": {
                        "status": fit.terminal_status, "termination_reason": fit.message,
                        "objective": fit.penalized_objective,
                        "gradient_inf_norm": fit.gradient_infinity_norm,
                        "iterations": fit.iterations, "optimizer": fit.solver,
                        "lambda": fit.regularization_lambda,
                    },
                    "training": {
                        "snapshot_sha256": snapshot_digest, "row_count": idx,
                        "first_draw_id": rows[0]["draw_id"],
                        "last_draw_id": rows[idx - 1]["draw_id"],
                        "cutoff_draw_id": rows[idx - 1]["draw_id"],
                        "cutoff_inclusive": True,
                    },
                    "implementation": {
                        "code_revision": header["code_commit"],
                        "runtime": {"python": platform.python_version(),
                                    "implementation": platform.python_implementation()},
                        "library_versions": {},
                        "rng_algorithm": "injected_rng.random_v1",
                    },
                    "feature_schema_version": model.table.stats.feature_schema_version,
                    "candidate_feature_names": list(model.table.stats.candidate_feature_names),
                    "active_feature_names": active_features,
                    "zero_variance_features": list(model.table.stats.zero_variance_features),
                    "feature_schema_hash": _jcs_hash(feature_schema),
                    "model_configuration_hash": _jcs_hash(candidate_config),
                    "model_configuration": candidate_config,
                    "theta": list(fit.theta), "objective_scale": fit.objective_scale,
                    "regularization_lambda": fit.regularization_lambda,
                    "normalization": {"method": "full_support_logsumexp",
                                      "log_partition": model.log_partition(fit.theta),
                                      "numeric_dtype": "float64"},
                }
                artifact_bytes, artifact_id = create_artifact(candidate_payload)
                model_artifacts["candidate"] = {
                    "artifact_id": artifact_id, "payload": verify_artifact(artifact_bytes)}
            else:
                model_artifacts["candidate"] = _create_fit_failure_artifact(
                    model_family="complete_subset_exponential", zone=zone,
                    population_size=m, selection_size=k, snapshot_digest=snapshot_digest,
                    training_rows=training, code_revision=header["code_commit"],
                    feature_schema=feature_schema, model_configuration=candidate_config,
                    status=fit.terminal_status, reason=fit.message,
                    objective=fit.penalized_objective,
                    gradient_inf_norm=fit.gradient_infinity_norm,
                    iterations=fit.iterations, optimizer=fit.solver,
                    regularization_lambda=fit.regularization_lambda,
                    rng_algorithm="injected_rng.random_v1",
                )
            for baseline in ("expanding", "ewma"):
                baseline_schema = {
                    "version": "lottery-item-inclusion/v1",
                    "names": [f"item_{item}" for item in range(1, m + 1)],
                    "uniform_means": [k / m] * m,
                    "uniform_population_stds": [math.sqrt((k / m) * (1.0 - k / m))] * m,
                    "zero_variance_policy": "not_applicable_item_indicator_schema",
                }
                baseline_config = {
                    "model_family": "conditional_poisson", "baseline": baseline,
                    "zone": zone, "population_size": m, "selection_size": k,
                    "alpha": 100.0,
                    "half_life": 100.0 if baseline == "ewma" else None,
                    "weighting": "expanding" if baseline == "expanding" else "2^(-lag/100)",
                    "feature_schema_hash": _jcs_hash(baseline_schema),
                }
                try:
                    marginals = _probabilities(training, field, m, k, model=baseline,
                                               alpha=100.0, half_life=100.0)
                    calibration = ConditionalPoisson.calibrate(marginals, k)
                    statuses[baseline] = calibration.terminal_status
                    scores[baseline] = None
                    if calibration.converged:
                        conditional = ConditionalPoisson(calibration.centered_log_weights, k)
                        scores[baseline] = -conditional.log_probability(target)
                        baseline_payload = {
                            "schema_version": 1,
                            "artifact_schema": "lottery.subset-probability-model/v1",
                            "artifact_type": "fitted_model",
                            "model_family": "conditional_poisson",
                            "zone": zone, "population_size": m, "selection_size": k,
                            "training_snapshot_sha256": snapshot_digest,
                            "training_first_draw_id": rows[0]["draw_id"],
                            "training_last_draw_id": rows[idx - 1]["draw_id"],
                            "training_cutoff_draw_id": rows[idx - 1]["draw_id"],
                            "training_row_count": idx, "code_revision": header["code_commit"],
                            "runtime": {"python": platform.python_version(),
                                        "implementation": platform.python_implementation()},
                            "fit_diagnostics": {
                                "terminal_status": calibration.terminal_status,
                                "converged": calibration.converged,
                                "message": calibration.message,
                                "iterations": calibration.iterations,
                                "gradient_infinity_norm": calibration.gradient_infinity_norm,
                                "calibration_residual": calibration.maximum_absolute_residual,
                                "objective": calibration.objective,
                            },
                            "forecast_ready": False,
                            "support": {"population_size": m, "selection_size": k,
                                        "support_count": math.comb(m, k),
                                        "subset_order": "lexicographic_ascending"},
                            "feature_schema": baseline_schema,
                            "parameters": {
                                "centered_log_weights": list(calibration.centered_log_weights),
                                "parameter_order": "feature_schema.names",
                            },
                            "model_configuration": baseline_config,
                            "fit": {
                                "status": calibration.terminal_status,
                                "termination_reason": calibration.message,
                                "objective": calibration.objective,
                                "gradient_inf_norm": calibration.gradient_infinity_norm,
                                "iterations": calibration.iterations,
                                "optimizer": calibration.solver,
                                "lambda": None,
                            },
                            "training": {
                                "snapshot_sha256": snapshot_digest, "row_count": idx,
                                "first_draw_id": rows[0]["draw_id"],
                                "last_draw_id": rows[idx - 1]["draw_id"],
                                "cutoff_draw_id": rows[idx - 1]["draw_id"],
                                "cutoff_inclusive": True,
                            },
                            "implementation": {
                                "code_revision": header["code_commit"],
                                "runtime": {"python": platform.python_version(),
                                            "implementation": platform.python_implementation()},
                                "library_versions": {},
                                "rng_algorithm": "conditional_poisson_backward_dp_with_injected_rng_v1",
                            },
                            "baseline": baseline, "alpha": 100.0,
                            "half_life": 100.0 if baseline == "ewma" else None,
                            "target_marginals": list(calibration.target_marginals),
                            "achieved_marginals": list(calibration.achieved_marginals),
                            "centered_log_weights": list(calibration.centered_log_weights),
                            "solver_status": calibration.terminal_status,
                            "calibration_residual": calibration.maximum_absolute_residual,
                            "feature_schema_hash": _jcs_hash(baseline_schema),
                            "model_configuration_hash": _jcs_hash(baseline_config),
                            "normalization": {
                                "method": "exact_conditional_poisson_log_space_dp",
                                "log_partition": conditional.log_normalizer,
                                "numeric_dtype": "float64",
                            },
                        }
                        artifact_bytes, artifact_id = create_artifact(baseline_payload)
                        model_artifacts[baseline] = {
                            "artifact_id": artifact_id, "payload": verify_artifact(artifact_bytes)}
                    else:
                        model_artifacts[baseline] = _create_fit_failure_artifact(
                            model_family="conditional_poisson", zone=zone,
                            population_size=m, selection_size=k, snapshot_digest=snapshot_digest,
                            training_rows=training, code_revision=header["code_commit"],
                            feature_schema=baseline_schema, model_configuration=baseline_config,
                            status=calibration.terminal_status, reason=calibration.message,
                            objective=calibration.objective,
                            gradient_inf_norm=calibration.gradient_infinity_norm,
                            iterations=calibration.iterations,
                            optimizer=calibration.solver,
                            regularization_lambda=None,
                            rng_algorithm="conditional_poisson_backward_dp_with_injected_rng_v1",
                        )
                except (ValueError, ArithmeticError, OverflowError) as exc:
                    statuses[baseline] = "failed:" + type(exc).__name__
                    scores[baseline] = None
                    model_artifacts[baseline] = _create_fit_failure_artifact(
                        model_family="conditional_poisson", zone=zone,
                        population_size=m, selection_size=k, snapshot_digest=snapshot_digest,
                        training_rows=training, code_revision=header["code_commit"],
                        feature_schema=baseline_schema, model_configuration=baseline_config,
                        status=statuses[baseline], reason=str(exc),
                        objective=None, gradient_inf_norm=None, iterations=0,
                        optimizer=calibration.solver,
                        regularization_lambda=None,
                        rng_algorithm="conditional_poisson_backward_dp_with_injected_rng_v1",
                    )
            scores["exponential_family"] = candidate
            training_dates_strict = all(item["draw_date"] < rows[idx]["draw_date"] for item in training)
            if not training_dates_strict:
                raise ValueError(f"training date is not strictly earlier than target {rows[idx]['draw_id']}")
            record = {
                "record_type": "target", "target_draw_id": rows[idx]["draw_id"],
                "target_draw_date": rows[idx]["draw_date"],
                "training_count": idx, "training_first_draw_id": rows[0]["draw_id"],
                "training_last_draw_id": rows[idx - 1]["draw_id"],
                "training_cutoff_draw_id": rows[idx - 1]["draw_id"],
                "training_cutoff_date": rows[idx - 1]["draw_date"],
                "training_dates_strictly_before_target": True,
                "observed_subset": list(target),
                "fit_statuses": statuses, "exact_set_nll": scores,
                "model_artifacts": model_artifacts,
                "candidate_iterations": fit.iterations,
                "candidate_gradient_infinity_norm": fit.gradient_infinity_norm,
            }
            record["record_sha256"] = _checkpoint_record_hash(record)
            checkpoint.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
            checkpoint.flush()
            os.fsync(checkpoint.fileno())
            _validate_checkpoint_record(
                record, row=rows[idx], zone=zone, training_count=idx,
                uniform_nll=uniform_nll,
            )
            records.append(record)
            count_status(record)
            completed = idx - MIN_TRAIN + 1
            if completed % 50 == 0 or completed == expected:
                print(f"EXACT_SUBSET_PROGRESS zone={zone} completed={completed}/{expected}", flush=True)

    references = ("uniform", "expanding", "ewma")
    deltas = {name: [] for name in references}
    scored = {name: 0 for name in ("uniform", "expanding", "ewma", "exponential_family")}
    sums = {name: 0.0 for name in scored}
    for record in records:
        for name, value in record["exact_set_nll"].items():
            if value is not None:
                scored[name] += 1
                sums[name] += value
        candidate = record["exact_set_nll"]["exponential_family"]
        if candidate is not None:
            for name in references:
                baseline = record["exact_set_nll"][name]
                if baseline is not None:
                    deltas[name].append(candidate - baseline)
    complete = (len(records) == expected and all(v == expected for v in scored.values())
                and all(len(v) == expected for v in deltas.values()))
    comparisons = {
        name: _moving_block_bootstrap(values, seed + index)
        if len(values) == expected else None
        for index, (name, values) in enumerate(deltas.items())
    }
    return {
        "zone": zone, "population_size": m, "selection_size": k,
        "active_feature_names": list(model.table.stats.feature_names),
        "candidate_feature_names": list(model.table.stats.candidate_feature_names),
        "zero_variance_features": list(model.table.stats.zero_variance_features),
        "uniform_feature_means": list(model.table.stats.means),
        "uniform_feature_standard_deviations": list(model.table.stats.standard_deviations),
        "target_count": expected, "scored_target_counts": scored,
        "fit_status_counts": status_counts, "complete_coverage": complete,
        "mean_exact_set_nll": {name: sums[name] / scored[name] if scored[name] else None for name in sums},
        "paired_candidate_minus_baseline": comparisons,
        "target_records": records, "checkpoint_path": str(checkpoint_path),
    }


def run(snapshot_path: Path, output_path: Path, checkpoint_dir: Path | None = None) -> dict:
    rows, digest = _load_and_validate(snapshot_path)
    checkpoint_dir = checkpoint_dir or output_path.parent / "subset-model-checkpoints"
    front = _evaluate_zone(rows, "front", FRONT_POPULATION, FRONT_SELECTION, True,
                           BOOTSTRAP_SEED, checkpoint_dir / "front.jsonl", digest)
    back = _evaluate_zone(rows, "back", BACK_POPULATION, BACK_SELECTION, False,
                          BOOTSTRAP_SEED + 1, checkpoint_dir / "back.jsonl", digest)
    # The mathematical solver and two-hypothesis Holm policy are implemented.
    # Non-regression uses a conservative zero-NLL margin against both fixed
    # marginal comparators; see the preregistration clarification.
    solver_policy_approved = True
    multiplicity_policy_approved = True
    non_regression_policy_approved = True
    descriptive_ci_pass = all(
        zone["complete_coverage"] and all(
            zone["paired_candidate_minus_baseline"][ref] is not None
            and zone["paired_candidate_minus_baseline"][ref]["ci_95_upper"] < 0.0
            for ref in ("uniform", "expanding", "ewma"))
        for zone in (front, back))
    # The preregistered confirmatory family is exactly candidate-vs-uniform
    # for front and back. Expanding/EWMA remain fixed comparators, not extra
    # hypotheses in the Holm family.
    primary_comparisons = {
        "front": front["paired_candidate_minus_baseline"]["uniform"],
        "back": back["paired_candidate_minus_baseline"]["uniform"],
    }
    primary_p_values = {
        zone: comparison["one_sided_null_centered_p_value"]
        for zone, comparison in primary_comparisons.items()
        if comparison is not None
    }
    # Missing/failed targets leave the inferential family incomplete; do not
    # invent a p-value or shrink the preregistered family.
    holm_adjusted = (
        _holm_adjust(primary_p_values, alpha=0.05)
        if len(primary_p_values) == 2 else {}
    )
    zone_inferential_pass = {
        zone: (
            comparison is not None
            and zone in holm_adjusted
            and (zone == "front" and front["complete_coverage"]
                 or zone == "back" and back["complete_coverage"])
            and comparison["ci_95_upper"] < 0.0
            and holm_adjusted.get(zone, 1.0) < 0.05
        )
        for zone, comparison in primary_comparisons.items()
    }
    primary_inferential_pass = all(zone_inferential_pass.values())
    non_regression_pass = {
        zone: (
            (front if zone == "front" else back)["complete_coverage"]
            and all(
                (front if zone == "front" else back)["paired_candidate_minus_baseline"][reference] is not None
                and (front if zone == "front" else back)["paired_candidate_minus_baseline"][reference]["ci_95_upper"] <= 0.0
                for reference in ("expanding", "ewma")
            )
        )
        for zone in ("front", "back")
    }
    # This optimizer repair follows an observed failed-fit run. Issue #27
    # registers it as a child exploratory diagnostic, so it cannot inherit the
    # original LOT-055 confirmatory label even if all numerical gates pass.
    experiment_registration_approved = False
    passed = _confirmatory_gate(
        primary_inferential_pass,
        experiment_registration_approved=experiment_registration_approved,
        solver_policy_approved=solver_policy_approved,
        multiplicity_policy_approved=multiplicity_policy_approved,
        non_regression_policy_approved=non_regression_policy_approved,
        non_regression_pass=all(non_regression_pass.values()),
    )
    result = {
        "run_type": "LOT-055-equipment-blind-exact-subset-rolling-origin",
        "snapshot_sha256": digest, "snapshot_rows": len(rows),
        "snapshot_source_commit": os.environ.get("RESEARCH_SNAPSHOT_COMMIT", "unverified-local-input"),
        "snapshot_trust_status": os.environ.get("RESEARCH_SNAPSHOT_TRUST_STATUS", "not_verified_by_runner"),
        "code_commit": os.environ.get("RESEARCH_CODE_COMMIT", os.environ.get("GITHUB_SHA", "local")),
        "snapshot_first_draw": rows[0]["draw_id"], "snapshot_last_draw": rows[-1]["draw_id"],
        "first_target_draw": rows[MIN_TRAIN]["draw_id"], "last_target_draw": rows[-1]["draw_id"],
        "target_count_per_zone": len(rows) - MIN_TRAIN, "minimum_training_rows": MIN_TRAIN,
        "model_comparison": ["uniform", "expanding", "ewma", "exponential_family"],
        "objective_scale": "mean_nll", "regularization_lambda": 1.0,
        "solver": "deterministic_unbounded_lbfgsb_strong_wolfe_v1",
        "solver_policy_note": "Unbounded L-BFGS-B specialization: this model has no box constraints, so the active-set step reduces to L-BFGS; deterministic strong-Wolfe line search is used.",
        "bootstrap": {
            "replicates": BOOTSTRAP_REPLICATES,
            "block_length": BOOTSTRAP_BLOCK,
            "seed": BOOTSTRAP_SEED,
            "seeds_by_zone_and_comparison": {
                "front": {"uniform": BOOTSTRAP_SEED, "expanding": BOOTSTRAP_SEED + 1,
                          "ewma": BOOTSTRAP_SEED + 2},
                "back": {"uniform": BOOTSTRAP_SEED + 1, "expanding": BOOTSTRAP_SEED + 2,
                         "ewma": BOOTSTRAP_SEED + 3},
            },
            "seed_policy": "zone base seed plus comparator index in uniform/expanding/ewma order",
            "method": "paired non-circular moving-block percentile CI and null-centered one-sided bootstrap test",
        },
        "front": front, "back": back,
        "descriptive_ci_pass": bool(descriptive_ci_pass),
        "confirmatory_family": {
            "status": "descriptive_only_post_outcome_child_experiment",
            "hypotheses": ["candidate_vs_uniform_front", "candidate_vs_uniform_back"],
            "family_size": 2,
            "method": "Holm step-down",
            "alpha": 0.05,
            "raw_one_sided_p_values": primary_p_values,
            "holm_adjusted_p_values": holm_adjusted,
            "zone_inferential_pass": zone_inferential_pass,
            "all_zones_inferential_pass": bool(primary_inferential_pass),
        },
        "solver_policy_approved": solver_policy_approved,
        "multiplicity_policy_approved": multiplicity_policy_approved,
        "non_regression_policy_approved": non_regression_policy_approved,
        "non_regression_policy": {
            "approved": non_regression_policy_approved,
            "margin_nll": 0.0,
            "criterion": "candidate-minus-comparator 95% paired block-bootstrap CI upper <= 0 in each zone",
            "comparators": ["expanding", "ewma"],
            "zone_pass": non_regression_pass,
            "all_zones_pass": bool(all(non_regression_pass.values())),
            "multiplicity_note": "intersection-union non-regression gate; all four zone-by-comparator conditions must pass",
        },
        "experiment_id": "LOT055-OPT-DIAG-20261120",
        "experiment_class": "exploratory_diagnostic",
        "confirmatory_eligible": False,
        "experiment_registration_approved": False,
        "confirmatory_ineligibility_reason": "post-outcome optimizer repair; see Issue #27 child registration",
        "confirmatory_candidate_pass": bool(passed),
        "production_ready": False,
        "limitations": ["pooled equipment-blind model only", "snapshot not officially authenticated",
                        "no LOT-042 access", "no promotion or serving",
                        ("candidate optimizer has line_search_failed fits; see per-zone fit_status_counts"
                         if any(zone["fit_status_counts"]["candidate"].get("line_search_failed", 0)
                                for zone in (front, back))
                         else "candidate optimizer had no line_search_failed fits"),
                        "Holm statistics are descriptive only for this post-outcome optimizer-repair child experiment",
                        "not eligible for confirmatory claims under LOT-064/Issue #27"],
    }
    immutable_outputs = write_immutable_outputs(result, rows, snapshot_path, output_path)
    result["immutable_outputs"] = immutable_outputs
    # The canonical model payloads live in model-artifacts.jsonl and the
    # checkpoint ledgers. Keep only their content IDs in the human report.
    for zone in ("front", "back"):
        for target_record in result[zone]["target_records"]:
            target_record["model_artifact_ids"] = {
                name: (entry["artifact_id"] if entry is not None else None)
                for name, entry in target_record.pop("model_artifacts").items()
            }
            target_record["checkpoint_record_sha256"] = target_record.pop("record_sha256")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                           encoding="utf-8")
    print("SUBSET_MODEL_ROLLING_ORIGIN_RESULT=" + json.dumps({
        "snapshot_sha256": digest, "target_count_per_zone": result["target_count_per_zone"],
        "front_complete": front["complete_coverage"], "back_complete": back["complete_coverage"],
        "front_scores": front["mean_exact_set_nll"], "back_scores": back["mean_exact_set_nll"],
        "confirmatory_candidate_pass": result["confirmatory_candidate_pass"], "production_ready": False,
    }, sort_keys=True))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint-dir", type=Path)
    args = parser.parse_args()
    run(args.snapshot, args.output, args.checkpoint_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
