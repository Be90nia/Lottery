"""Typed, offline readiness receipt verification for LOT-074.

This verifies receipt integrity and contract binding. It does not authenticate
who produced a receipt; SHA-256 is integrity, not source authenticity.
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
import math
import re
import random
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from lottery.subset_model.artifact import canonicalize

GATE_TYPES = {
    "G0": "source-build-integrity",
    "G1": "canonical-data-source-evidence",
    "G2": "numerical-engine",
    "G3": "experimental-validity",
    "G4": "population-regime-validity",
    "G5": "champion-lifecycle-serving",
    "G6": "feedback-monitoring",
    "G7": "durable-storage-recovery",
    "G8": "security-operations",
}
FAULTS = tuple(f"F{i:02d}" for i in range(1, 16))
GATE_REQUIRED_CHECKS = {
    "G0": ("source_commit", "workflow_action_pins", "dependency_lock", "runtime_toolchain", "sbom", "security_scan"),
    "G1": ("canonical_snapshot", "raw_source_bytes", "source_authority", "parser_lineage", "outcome_validation", "coverage"),
    "G2": ("full_support", "normalization", "exact_subset_probability", "conditional_poisson", "deterministic_sampler", "numerical_stability"),
    "G3": ("preregistration", "chronological_targets", "complete_denominator", "baseline_comparison", "multiplicity_control", "calibration"),
    "G4": ("row_level_labels", "regime_adjudication", "minimum_history", "same_target_comparison", "no_cross_regime_merge"),
    "G5": ("three_slot_registry", "single_registry_generation", "front_back_pairing", "immutable_artifacts", "sampler_cardinality", "no_fit_on_request"),
    "G6": ("frozen_forecast", "official_outcome_validation", "append_only_corrections", "statistical_unit", "monitoring_thresholds"),
    "G7": ("conditional_create", "readback_hash", "fencing_tokens", "immutable_registry", "independent_backup", "restore_drill", "measured_rpo_rto"),
    "G8": ("least_privilege", "secret_scan", "incident_response", "artifact_integrity", "rollback_drill", "operational_monitoring"),
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class ReceiptVerificationError(ValueError):
    """A readiness receipt is malformed, mismatched, or unverifiable."""


def _strict_json(raw: bytes, label: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ReceiptVerificationError(f"{label}: duplicate JSON key {key}")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReceiptVerificationError(f"{label}: invalid strict JSON") from exc
    if not isinstance(value, dict):
        raise ReceiptVerificationError(f"{label}: receipt must be an object")
    return value


def _safe_file(root: Path, reference: Any, label: str) -> tuple[bytes, str]:
    if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
        raise ReceiptVerificationError(f"{label}: file reference shape invalid")
    path, expected = reference["path"], reference["sha256"]
    if (
        not isinstance(path, str) or not path or "\\" in path or ":" in path
        or not isinstance(expected, str) or not SHA256.fullmatch(expected)
    ):
        raise ReceiptVerificationError(f"{label}: invalid path or digest")
    relative = PurePosixPath(path)
    if relative.is_absolute() or relative.as_posix() != path or any(
        part in ("", ".", "..") for part in relative.parts
    ):
        raise ReceiptVerificationError(f"{label}: non-canonical or traversal path")
    candidate = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ReceiptVerificationError(f"{label}: symlink forbidden")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
        if not resolved.is_file():
            raise OSError("not a regular file")
        raw = resolved.read_bytes()
    except (OSError, ValueError) as exc:
        raise ReceiptVerificationError(f"{label}: file missing or outside evidence root") from exc
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise ReceiptVerificationError(f"{label}: SHA-256 mismatch")
    return raw, actual


def _utc_timestamp(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ReceiptVerificationError(f"{label}: timestamp must be UTC RFC3339 with Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ReceiptVerificationError(f"{label}: invalid timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise ReceiptVerificationError(f"{label}: timestamp must be UTC")


def _verify_g2_evidence(check_id: str, raw: bytes) -> None:
    """Validate numerical-engine evidence values, not merely their file hashes."""
    report = _strict_json(raw, "G2 " + check_id)
    zones = {"front": (35, 5, 324632), "back": (12, 2, 66)}

    def finite_number(value: Any) -> bool:
        return type(value) in (int, float) and math.isfinite(value)

    def require(condition: bool, message: str) -> None:
        if not condition:
            raise ReceiptVerificationError("G2 " + check_id + ": " + message)

    if check_id in ("full_support", "normalization", "exact_subset_probability"):
        require(set(report) == {"schema", "zones"}, "report fields invalid")
        expected_schema = {
            "full_support": "lottery.g2-full-support/v1",
            "normalization": "lottery.g2-normalization/v1",
            "exact_subset_probability": "lottery.g2-exact-probability/v1",
        }[check_id]
        require(report["schema"] == expected_schema, "unsupported evidence schema")
        entries = report["zones"]
        require(isinstance(entries, list) and len(entries) == 2, "must contain front and back zones")
        indexed = {entry.get("zone"): entry for entry in entries if isinstance(entry, dict)}
        require(set(indexed) == set(zones), "front/back zone inventory mismatch")
        for zone, (m, k, support_count) in zones.items():
            entry = indexed[zone]
            if check_id == "full_support":
                require(
                    set(entry) == {"zone", "population_size", "selection_size", "expected_support_count", "enumerated_support_count"}
                    and entry["population_size"] == m and entry["selection_size"] == k
                    and entry["expected_support_count"] == support_count
                    and entry["enumerated_support_count"] == support_count,
                    f"{zone} support coverage is not exact",
                )
            else:
                expected_fields = (
                    {"zone", "probability_sum", "minimum_probability", "max_abs_error"}
                    if check_id == "normalization"
                    else {"zone", "enumerated_subset_count", "probability_sum", "minimum_probability", "max_abs_oracle_error"}
                )
                require(set(entry) == expected_fields, f"{zone} numerical fields invalid")
                count_field = "enumerated_subset_count"
                if check_id == "exact_subset_probability":
                    require(entry[count_field] == support_count, f"{zone} probability oracle did not cover full support")
                error_field = "max_abs_error" if check_id == "normalization" else "max_abs_oracle_error"
                require(
                    finite_number(entry["probability_sum"])
                    and abs(entry["probability_sum"] - 1.0) <= 1e-12
                    and finite_number(entry["minimum_probability"])
                    and entry["minimum_probability"] >= 0.0
                    and finite_number(entry[error_field])
                    and entry[error_field] <= 1e-12,
                    f"{zone} probabilities are not normalized/nonnegative within 1e-12",
                )
        return

    contracts = {
        "conditional_poisson": (
            {"schema", "algorithm", "oracle_cases", "max_abs_probability_error", "max_abs_marginal_error", "all_finite"},
            "lottery.g2-conditional-poisson/v1", "log_elementary_symmetric_dp",
        ),
        "deterministic_sampler": (
            {"schema", "algorithm", "seed", "samples_per_zone", "replay_identical", "invalid_sample_count"},
            "lottery.g2-deterministic-sampler/v1", "backward_dp",
        ),
        "numerical_stability": (
            {"schema", "stress_cases", "non_finite_count", "max_abs_normalization_error", "minimum_probability"},
            "lottery.g2-numerical-stability/v1", None,
        ),
    }
    fields, schema, algorithm = contracts[check_id]
    require(set(report) == fields and report["schema"] == schema, "report schema/fields invalid")
    if check_id == "conditional_poisson":
        require(
            report["algorithm"] == algorithm and type(report["oracle_cases"]) is int
            and report["oracle_cases"] >= 100
            and finite_number(report["max_abs_probability_error"])
            and report["max_abs_probability_error"] <= 1e-12
            and finite_number(report["max_abs_marginal_error"])
            and report["max_abs_marginal_error"] <= 1e-12
            and report["all_finite"] is True,
            "conditional-Poisson oracle checks failed",
        )
    elif check_id == "deterministic_sampler":
        require(
            report["algorithm"] == algorithm and type(report["seed"]) is int
            and report["seed"] >= 0
            and type(report["samples_per_zone"]) is int and report["samples_per_zone"] >= 1000
            and report["replay_identical"] is True
            and report["invalid_sample_count"] == 0,
            "deterministic sampler replay/support checks failed",
        )
    else:
        require(
            type(report["stress_cases"]) is int and report["stress_cases"] >= 100
            and report["non_finite_count"] == 0
            and finite_number(report["max_abs_normalization_error"])
            and report["max_abs_normalization_error"] <= 1e-10
            and finite_number(report["minimum_probability"])
            and report["minimum_probability"] >= 0.0,
            "numerical stability stress checks failed",
        )




@lru_cache(maxsize=24)
def _g3_moving_block_bootstrap(values: tuple[float, ...], seed: int) -> tuple[float, float, float]:
    """Replay the frozen 1,000 × 50 non-circular bootstrap exactly."""
    n = len(values)
    if n < 50 or any(not math.isfinite(value) for value in values):
        raise ReceiptVerificationError("G3: invalid paired values for moving-block bootstrap")
    rng = random.Random(seed)
    observed = sum(values) / n
    centered = [value - observed for value in values]
    means: list[float] = []
    null_means: list[float] = []
    for _ in range(1000):
        indices: list[int] = []
        while len(indices) < n:
            start = rng.randrange(0, n - 50 + 1)
            indices.extend(range(start, start + 50))
        indices = indices[:n]
        means.append(sum(values[index] for index in indices) / n)
        null_means.append(sum(centered[index] for index in indices) / n)
    ordered = sorted(means)
    def percentile(probability: float) -> float:
        position = (len(ordered) - 1) * probability
        lower, upper = math.floor(position), math.ceil(position)
        if lower == upper:
            return ordered[lower]
        weight = position - lower
        return ordered[lower] * (1.0 - weight) + ordered[upper] * weight
    p_value = (1 + sum(value <= observed for value in null_means)) / 1001
    return percentile(0.025), percentile(0.975), p_value



def _verify_g3_evidence_bundle(
    raw_by_check: dict[str, bytes], root: Path, release_manifest: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Verify LOT-055 chronological evaluation evidence and its complete ledger."""
    def require(condition: bool, message: str) -> None:
        if not condition:
            raise ReceiptVerificationError("G3: " + message)

    expected_ids = {
        "preregistration", "chronological_targets", "complete_denominator",
        "baseline_comparison", "multiplicity_control", "calibration",
    }
    require(set(raw_by_check) == expected_ids, "evidence inventory mismatch")
    reports = {key: _strict_json(raw, "G3 " + key) for key, raw in raw_by_check.items()}
    prereg = reports["preregistration"]
    require(set(prereg) == {
        "schema", "protocol_id", "experiment_id", "experiment_class",
        "outcomes_observed_at_registration", "snapshot_sha256",
        "target_manifest_sha256", "model_ids", "bootstrap_replicates",
        "block_length", "bootstrap_seed", "bootstrap_seeds_by_zone",
        "bootstrap_seeds_by_zone_and_comparison", "multiplicity_family",
        "alpha", "calibration_method", "calibration_tolerance",
        "holdout_accessed",
    }, "preregistration fields invalid")
    require(
        prereg["schema"] == "lottery.g3-preregistration/v1"
        and prereg["protocol_id"] == "LOT-055-v1"
        and prereg["experiment_class"] == "confirmatory"
        and prereg["outcomes_observed_at_registration"] is False
        and prereg["holdout_accessed"] is False,
        "protocol is not a pre-outcome confirmatory LOT-055 registration",
    )
    require(
        isinstance(prereg["experiment_id"], str) and SHA256.fullmatch(prereg["experiment_id"])
        and isinstance(prereg["snapshot_sha256"], str)
        and prereg["snapshot_sha256"] == "9f4cc51b76fd258dd056e0b86f675192d3d9a41c2901f771cab778c65ec2b6aa"
        and isinstance(prereg["target_manifest_sha256"], str)
        and SHA256.fullmatch(prereg["target_manifest_sha256"]),
        "experiment or frozen snapshot identity invalid",
    )
    model_ids = prereg["model_ids"]
    require(
        isinstance(model_ids, dict) and model_ids == {
            "candidate": "exponential_family", "uniform": "uniform",
            "expanding": "expanding", "ewma": "ewma",
        },
        "the single candidate and three fixed comparators must have unique identities",
    )
    require(
        type(prereg["bootstrap_replicates"]) is int and prereg["bootstrap_replicates"] == 1000
        and type(prereg["block_length"]) is int and prereg["block_length"] == 50
        and type(prereg["bootstrap_seed"]) is int and prereg["bootstrap_seed"] >= 0
        and prereg["bootstrap_seeds_by_zone"] == {"front": prereg["bootstrap_seed"], "back": prereg["bootstrap_seed"] + 1}
        and prereg["bootstrap_seeds_by_zone_and_comparison"] == {
            "front": {"uniform": prereg["bootstrap_seed"], "expanding": prereg["bootstrap_seed"] + 1, "ewma": prereg["bootstrap_seed"] + 2},
            "back": {"uniform": prereg["bootstrap_seed"] + 1, "expanding": prereg["bootstrap_seed"] + 2, "ewma": prereg["bootstrap_seed"] + 3},
        }
        and type(prereg["alpha"]) in (int, float) and prereg["alpha"] == 0.05
        and isinstance(prereg["multiplicity_family"], list)
        and prereg["multiplicity_family"] == [
            "candidate_vs_uniform:front", "candidate_vs_uniform:back"
        ]
        and isinstance(prereg["calibration_method"], str) and prereg["calibration_method"]
        and type(prereg["calibration_tolerance"]) in (int, float)
        and math.isfinite(prereg["calibration_tolerance"])
        and 0 < prereg["calibration_tolerance"] <= 1,
        "frozen bootstrap, multiplicity or calibration policy invalid",
    )

    chronology = reports["chronological_targets"]
    require(set(chronology) == {
        "schema", "snapshot_sha256", "target_manifest_sha256", "snapshot_row_count",
        "target_ids", "target_ids_sha256", "target_dates", "training_cutoff_ids",
        "training_cutoff_dates", "minimum_training_draws",
        "strictly_before_target", "equipment_fields_used", "holdout_accessed",
    }, "chronological target fields invalid")
    target_ids = chronology["target_ids"]
    require(
        chronology["schema"] == "lottery.g3-chronological-targets/v1"
        and chronology["snapshot_sha256"] == prereg["snapshot_sha256"]
        and chronology["target_manifest_sha256"] == prereg["target_manifest_sha256"]
        and chronology["snapshot_row_count"] == 2949
        and isinstance(target_ids, list) and len(target_ids) == 2649
        and all(isinstance(value, str) and re.fullmatch(r"\d{5}", value) for value in target_ids)
        and target_ids == sorted(set(target_ids))
        and target_ids[0] == "09054" and target_ids[-1] == "26131"
        and chronology["target_ids_sha256"] == hashlib.sha256(canonicalize(target_ids)).hexdigest()
        and chronology["minimum_training_draws"] == 300
        and chronology["strictly_before_target"] is True
        and chronology["equipment_fields_used"] is False
        and chronology["holdout_accessed"] is False,
        "frozen 2,649-target chronology, source identity or leakage boundary invalid",
    )
    target_dates = chronology["target_dates"]
    cutoff_ids = chronology["training_cutoff_ids"]
    cutoff_dates = chronology["training_cutoff_dates"]
    require(
        isinstance(target_dates, list) and len(target_dates) == 2649
        and all(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) for value in target_dates)
        and target_dates == sorted(target_dates) and len(set(target_dates)) == 2649
        and isinstance(cutoff_ids, list) and len(cutoff_ids) == 2649
        and all(isinstance(value, str) and re.fullmatch(r"\d{5}", value) for value in cutoff_ids)
        and cutoff_ids[0] < target_ids[0] and cutoff_ids[1:] == target_ids[:-1]
        and isinstance(cutoff_dates, list) and len(cutoff_dates) == 2649
        and all(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) for value in cutoff_dates)
        and cutoff_dates[0] < target_dates[0] and cutoff_dates[1:] == target_dates[:-1]
        and all(cutoff_ids[index] < target_ids[index] and cutoff_dates[index] < target_dates[index]
                for index in range(2649)),
        "per-target training cutoffs do not match the frozen chronological predecessor sequence",
    )
    target_index = {target: index for index, target in enumerate(target_ids)}

    denominator = reports["complete_denominator"]
    require(set(denominator) == {
        "schema", "target_ids_sha256", "model_ids", "zones",
        "expected_target_count", "expected_record_count", "terminal_record_count",
        "status_counts", "ledger", "run_manifest",
    }, "complete-denominator fields invalid")
    expected_records = 2649 * 4 * 2
    require(
        denominator["schema"] == "lottery.g3-terminal-ledger-index/v1"
        and denominator["target_ids_sha256"] == chronology["target_ids_sha256"]
        and denominator["model_ids"] == model_ids
        and denominator["zones"] == ["front", "back"]
        and denominator["expected_target_count"] == 2649
        and denominator["expected_record_count"] == expected_records
        and denominator["terminal_record_count"] == expected_records,
        "full model × zone × target denominator is incomplete or mismatched",
    )
    status_counts = denominator["status_counts"]
    allowed_statuses = {"scored", "fit_failed", "artifact_invalid", "probability_invalid", "runner_error"}
    require(
        isinstance(status_counts, dict) and set(status_counts) <= allowed_statuses
        and status_counts and all(type(value) is int and value >= 0 for value in status_counts.values())
        and sum(status_counts.values()) == expected_records
        and status_counts.get("scored", 0) == expected_records,
        "failed or missing target fits prevent confirmatory full-coverage acceptance",
    )
    ledger_raw, ledger_digest = _safe_file(root, denominator["ledger"], "G3 terminal ledger")
    run_manifest_raw, run_manifest_digest = _safe_file(
        root, denominator["run_manifest"], "G3 run manifest"
    )
    run_manifest = _strict_json(run_manifest_raw, "G3 run manifest")
    run_manifest_body = {
        key: value for key, value in run_manifest.items() if key != "manifest_sha256"
    }
    expected_run_manifest_digest = "sha256:" + hashlib.sha256(
        canonicalize(run_manifest_body)
    ).hexdigest()
    expected_target_list_digest = "sha256:" + hashlib.sha256(canonicalize({
        "targets": [
            {"target_draw_id": target, "target_draw_date": target_dates[index]}
            for index, target in enumerate(target_ids)
        ]
    })).hexdigest()
    expected_snapshot_digest = None
    if isinstance(release_manifest, dict):
        if release_manifest.get("schema") == "lottery.release-manifest/v2":
            snapshot_ref = release_manifest.get("evidence", {}).get("canonical_snapshot", {})
            expected_snapshot_digest = snapshot_ref.get("sha256") if isinstance(snapshot_ref, dict) else None
        else:
            expected_snapshot_digest = release_manifest.get("snapshot_sha256")
    require(
        run_manifest.get("schema") == "lot-055-run-manifest-v1"
        and run_manifest.get("manifest_sha256") == expected_run_manifest_digest
        and run_manifest.get("run_id")
        and run_manifest.get("experiment_class") == "confirmatory"
        and run_manifest.get("confirmatory_eligible") is True
        and run_manifest.get("confirmatory_ineligibility_reason") in (None, "")
        and isinstance(run_manifest.get("snapshot"), dict)
        and run_manifest["snapshot"].get("sha256") == prereg["snapshot_sha256"]
        and run_manifest["snapshot"].get("row_count") == chronology["snapshot_row_count"]
        and isinstance(run_manifest.get("target_manifest"), dict)
        and run_manifest["target_manifest"].get("target_count_per_zone") == 2649
        and run_manifest["target_manifest"].get("first_target_draw_id") == target_ids[0]
        and run_manifest["target_manifest"].get("last_target_draw_id") == target_ids[-1]
        and run_manifest["target_manifest"].get("target_list_sha256") == expected_target_list_digest
        and run_manifest.get("expected_target_record_count") == expected_records
        and run_manifest.get("actual_target_record_count") == expected_records
        and run_manifest.get("terminal_status_counts") == {
            status: status_counts.get(status, 0)
            for status in ("scored", "fit_failed", "artifact_invalid", "probability_invalid", "runner_error")
        }
        and isinstance(run_manifest.get("output_files"), dict)
        and isinstance(run_manifest["output_files"].get("target-score-ledger.jsonl"), dict)
        and run_manifest["output_files"]["target-score-ledger.jsonl"].get("sha256") == ledger_digest
        and run_manifest["output_files"]["target-score-ledger.jsonl"].get("bytes") == len(ledger_raw)
        and run_manifest.get("bootstrap", {}).get("replicates") == prereg["bootstrap_replicates"]
        and run_manifest.get("bootstrap", {}).get("block_length") == prereg["block_length"]
        and run_manifest.get("bootstrap", {}).get("seed") == prereg["bootstrap_seed"]
        and run_manifest.get("bootstrap", {}).get("seeds_by_zone_and_comparison")
            == prereg["bootstrap_seeds_by_zone_and_comparison"]
        and expected_snapshot_digest == prereg["snapshot_sha256"],
        "run manifest is missing, non-confirmatory, tampered, or inconsistent with the frozen release/protocol",
    )
    require(
        isinstance(run_manifest.get("experiment_id"), str)
        and hashlib.sha256(run_manifest["experiment_id"].encode("utf-8")).hexdigest()
            == prereg["experiment_id"],
        "preregistration experiment identity does not bind the run manifest",
    )
    ledger_lines = ledger_raw.splitlines()
    require(len(ledger_lines) == expected_records, "terminal ledger line count differs from frozen denominator")
    seen: set[tuple[str, str, str]] = set()
    scores: dict[tuple[str, str, str], float] = {}
    status_totals = {key: 0 for key in allowed_statuses}
    run_id = None
    for line_number, line in enumerate(ledger_lines, 1):
        record = _strict_json(line, f"G3 terminal ledger line {line_number}")
        expected_record_fields = {
            "run_id", "target_draw_id", "target_draw_date", "zone", "model_family",
            "model_name", "artifact_id", "diagnostic_ref", "snapshot_sha256",
            "training_first_draw_id", "training_last_draw_id", "training_row_count",
            "training_dates_strictly_before_target", "model_configuration_hash",
            "feature_schema_hash", "optimizer_solver_status", "converged",
            "failure_reason", "terminal_status", "observed_subset",
            "predicted_log_probability", "negative_log_score", "pairing_key",
            "record_sha256",
        }
        require(
            set(record) == expected_record_fields,
            f"terminal ledger line {line_number} fields invalid; missing={sorted(expected_record_fields - set(record))}, extra={sorted(set(record) - expected_record_fields)}",
        )
        model_id, zone, target = record["model_name"], record["zone"], record["target_draw_id"]
        index = target_index.get(target)
        require(
            model_id in model_ids.values() and zone in ("front", "back")
            and index is not None
            and record["target_draw_date"] == target_dates[index]
            and record["snapshot_sha256"] == prereg["snapshot_sha256"]
            and isinstance(record["run_id"], str) and record["run_id"]
            and record["pairing_key"] == record["run_id"] + ":" + zone + ":" + target
            and type(record["training_row_count"]) is int
            and record["training_row_count"] == 300 + index
            and record["training_first_draw_id"] == "07001"
            and record["training_last_draw_id"] == cutoff_ids[index]
            and record["training_dates_strictly_before_target"] is True
            and isinstance(record["model_configuration_hash"], str)
            and record["model_configuration_hash"].startswith("sha256:")
            and isinstance(record["feature_schema_hash"], str)
            and record["feature_schema_hash"].startswith("sha256:")
            and isinstance(record["optimizer_solver_status"], str)
            and type(record["converged"]) is bool,
            f"terminal ledger line {line_number} violates target/cutoff/model identity",
        )
        if run_id is None:
            run_id = record["run_id"]
        require(record["run_id"] == run_id, "terminal ledger mixes multiple run IDs")
        key = (model_id, zone, target)
        require(key not in seen, f"duplicate terminal ledger record {key}")
        seen.add(key)
        status = record["terminal_status"]
        require(status in allowed_statuses, f"unknown terminal status at line {line_number}")
        status_totals[status] += 1
        body = {key: value for key, value in record.items() if key != "record_sha256"}
        expected_record_hash = "sha256:" + hashlib.sha256(canonicalize(body)).hexdigest()
        require(record["record_sha256"] == expected_record_hash, f"terminal ledger record hash mismatch at line {line_number}")
        expected_family = {
            "uniform": "uniform_analytic",
            "expanding": "conditional_poisson",
            "ewma": "conditional_poisson",
            "exponential_family": "complete_subset_exponential",
        }[model_id]
        require(record["model_family"] == expected_family, f"model family mismatch at line {line_number}")
        if status == "scored":
            require(
                type(record["negative_log_score"]) in (int, float)
                and math.isfinite(record["negative_log_score"])
                and record["negative_log_score"] >= 0
                and type(record["predicted_log_probability"]) in (int, float)
                and math.isfinite(record["predicted_log_probability"])
                and abs(record["predicted_log_probability"] + record["negative_log_score"]) <= 1e-12
                and record["converged"] is True
                and record["failure_reason"] is None
                and ((model_id == "uniform" and record["artifact_id"] is None)
                     or (model_id != "uniform" and isinstance(record["artifact_id"], str) and record["artifact_id"])),
                f"scored ledger record {key} has invalid NLL/probability/artifact",
            )
            scores[key] = float(record["negative_log_score"])
        else:
            require(
                record["negative_log_score"] is None
                and record["predicted_log_probability"] is None
                and isinstance(record["failure_reason"], str) and record["failure_reason"],
                f"failed ledger record {key} must not contain a fabricated score",
            )
    require(
        run_id == run_manifest["run_id"],
        "terminal ledger run ID does not match immutable run manifest",
    )
    require(len(seen) == expected_records and status_totals == {
        key: status_counts.get(key, 0) for key in allowed_statuses
    }, "terminal ledger inventory/status counts do not reconcile")
    for model_id in model_ids.values():
        for zone in ("front", "back"):
            for target in target_ids:
                require((model_id, zone, target) in seen, "missing model × zone × target terminal record")
    uniform_id = model_ids["uniform"]
    uniform_nll = {"front": math.log(324632), "back": math.log(66)}
    for zone in ("front", "back"):
        for target in target_ids:
            require(
                abs(scores[(uniform_id, zone, target)] - uniform_nll[zone]) <= 1e-10,
                "uniform exact-set baseline does not equal the legal-support constant",
            )

    baseline = reports["baseline_comparison"]
    require(set(baseline) == {
        "schema", "target_ids_sha256", "target_count", "candidate_model_id",
        "baseline_model_ids", "zones",
    }, "baseline comparison fields invalid")
    require(
        baseline["schema"] == "lottery.g3-baseline-comparison/v1"
        and baseline["target_ids_sha256"] == chronology["target_ids_sha256"]
        and baseline["target_count"] == 2649
        and baseline["candidate_model_id"] == model_ids["candidate"]
        and baseline["baseline_model_ids"] == {
            "uniform": model_ids["uniform"], "expanding": model_ids["expanding"], "ewma": model_ids["ewma"]
        }
        and isinstance(baseline["zones"], dict) and set(baseline["zones"]) == {"front", "back"},
        "baseline comparison is not paired to the frozen target family",
    )
    mean_values: dict[str, dict[str, float]] = {}
    replayed_primary_p_values: dict[str, float] = {}
    for zone in ("front", "back"):
        entry = baseline["zones"][zone]
        require(set(entry) == {
            "scored_pairs", "mean_nll", "candidate_vs_uniform_mean_delta",
            "candidate_vs_uniform_ci95", "candidate_vs_expanding_ci95_upper",
            "candidate_vs_ewma_ci95_upper",
        }, f"{zone} baseline fields invalid")
        require(entry["scored_pairs"] == 2649, f"{zone} paired baseline coverage is incomplete")
        mean_values[zone] = {}
        for role, model_id in model_ids.items():
            values = [scores[(model_id, zone, target)] for target in target_ids]
            mean_values[zone][role] = sum(values) / len(values)
        reported_means = entry["mean_nll"]
        require(
            isinstance(reported_means, dict) and set(reported_means) == set(model_ids)
            and all(type(reported_means[role]) in (int, float)
                    and math.isfinite(reported_means[role])
                    and abs(reported_means[role] - mean_values[zone][role]) <= 1e-10
                    for role in model_ids),
            f"{zone} absolute baseline means do not reconcile to terminal ledger",
        )
        delta = mean_values[zone]["candidate"] - mean_values[zone]["uniform"]
        interval = entry["candidate_vs_uniform_ci95"]
        require(
            type(entry["candidate_vs_uniform_mean_delta"]) in (int, float)
            and abs(entry["candidate_vs_uniform_mean_delta"] - delta) <= 1e-10
            and isinstance(interval, list) and len(interval) == 2
            and all(type(value) in (int, float) and math.isfinite(value) for value in interval)
            and interval[0] - 1e-10 <= delta <= interval[1] + 1e-10
            and type(entry["candidate_vs_expanding_ci95_upper"]) in (int, float)
            and math.isfinite(entry["candidate_vs_expanding_ci95_upper"])
            and type(entry["candidate_vs_ewma_ci95_upper"]) in (int, float)
            and math.isfinite(entry["candidate_vs_ewma_ci95_upper"]),
            f"{zone} paired uncertainty/non-regression report invalid",
        )
        paired = {
            role: [
                scores[(model_ids["candidate"], zone, target)]
                - scores[(model_ids[role], zone, target)]
                for target in target_ids
            ]
            for role in ("uniform", "expanding", "ewma")
        }
        uniform_ci = _g3_moving_block_bootstrap(
            tuple(paired["uniform"]), prereg["bootstrap_seeds_by_zone_and_comparison"][zone]["uniform"]
        )
        expanding_ci = _g3_moving_block_bootstrap(
            tuple(paired["expanding"]), prereg["bootstrap_seeds_by_zone_and_comparison"][zone]["expanding"]
        )
        ewma_ci = _g3_moving_block_bootstrap(
            tuple(paired["ewma"]), prereg["bootstrap_seeds_by_zone_and_comparison"][zone]["ewma"]
        )
        require(
            abs(interval[0] - uniform_ci[0]) <= 1e-10
            and abs(interval[1] - uniform_ci[1]) <= 1e-10
            and abs(entry["candidate_vs_expanding_ci95_upper"] - expanding_ci[1]) <= 1e-10
            and abs(entry["candidate_vs_ewma_ci95_upper"] - ewma_ci[1]) <= 1e-10,
            f"{zone} moving-block bootstrap intervals do not replay from paired target ledger",
        )
        replayed_primary_p_values[zone] = uniform_ci[2]
        require(
            entry["candidate_vs_expanding_ci95_upper"] <= 0
            and entry["candidate_vs_ewma_ci95_upper"] <= 0,
            f"{zone} candidate fails the frozen non-regression margin",
        )

    multiplicity = reports["multiplicity_control"]
    require(set(multiplicity) == {
        "schema", "target_ids_sha256", "bootstrap_replicates", "block_length",
        "bootstrap_seed", "bootstrap_seeds_by_zone", "bootstrap_seeds_by_zone_and_comparison",
        "method", "alpha", "hypotheses",
    }, "multiplicity report fields invalid")
    require(
        multiplicity["schema"] == "lottery.g3-holm-control/v1"
        and multiplicity["target_ids_sha256"] == chronology["target_ids_sha256"]
        and multiplicity["bootstrap_replicates"] == prereg["bootstrap_replicates"]
        and multiplicity["block_length"] == prereg["block_length"]
        and multiplicity["bootstrap_seed"] == prereg["bootstrap_seed"]
        and multiplicity["bootstrap_seeds_by_zone"] == prereg["bootstrap_seeds_by_zone"]
        and multiplicity["bootstrap_seeds_by_zone_and_comparison"] == prereg["bootstrap_seeds_by_zone_and_comparison"]
        and multiplicity["method"] == "holm-step-down-one-sided-centered-moving-block-bootstrap"
        and multiplicity["alpha"] == prereg["alpha"]
        and isinstance(multiplicity["hypotheses"], list) and len(multiplicity["hypotheses"]) == 2,
        "bootstrap or Holm policy differs from preregistration",
    )
    hypotheses = {item.get("hypothesis_id"): item for item in multiplicity["hypotheses"] if isinstance(item, dict)}
    expected_hypotheses = ("candidate_vs_uniform:front", "candidate_vs_uniform:back")
    require(set(hypotheses) == set(expected_hypotheses), "confirmatory hypothesis family is not exactly two co-primary zones")
    raw_p: dict[str, float] = {}
    for hypothesis_id in expected_hypotheses:
        item = hypotheses[hypothesis_id]
        require(set(item) == {"hypothesis_id", "p_value", "holm_adjusted_p_value", "ci95_lower", "ci95_upper"}, "Holm hypothesis fields invalid")
        values = (item["p_value"], item["holm_adjusted_p_value"], item["ci95_lower"], item["ci95_upper"])
        require(all(type(value) in (int, float) and math.isfinite(value) for value in values), "Holm numeric value invalid")
        require(0 <= item["p_value"] <= 1 and 0 <= item["holm_adjusted_p_value"] <= 1
                and item["ci95_lower"] <= item["ci95_upper"], "Holm p-value/interval out of range")
        raw_p[hypothesis_id] = float(item["p_value"])
        zone = hypothesis_id.split(":")[1]
        require(
            abs(item["p_value"] - replayed_primary_p_values[zone]) <= 1e-12,
            f"{zone} one-sided bootstrap p-value does not replay from paired target ledger",
        )
        expected_interval = baseline["zones"][zone]["candidate_vs_uniform_ci95"]
        require(
            abs(item["ci95_lower"] - expected_interval[0]) <= 1e-12
            and abs(item["ci95_upper"] - expected_interval[1]) <= 1e-12
            and item["ci95_upper"] < 0
            and item["holm_adjusted_p_value"] < prereg["alpha"],
            f"{zone} candidate does not pass the co-primary inferential gate",
        )
    ordered = sorted(raw_p.items(), key=lambda pair: pair[1])
    expected_adjusted: dict[str, float] = {}
    running = 0.0
    for rank, (hypothesis_id, p_value) in enumerate(ordered):
        running = max(running, min(1.0, (2 - rank) * p_value))
        expected_adjusted[hypothesis_id] = running
    require(
        all(abs(hypotheses[key]["holm_adjusted_p_value"] - expected_adjusted[key]) <= 1e-12
            for key in expected_hypotheses),
        "reported Holm adjusted p-values do not match step-down correction",
    )

    calibration = reports["calibration"]
    require(set(calibration) == {
        "schema", "target_ids_sha256", "method", "zones",
    }, "calibration report fields invalid")
    require(
        calibration["schema"] == "lottery.g3-calibration/v1"
        and calibration["target_ids_sha256"] == chronology["target_ids_sha256"]
        and calibration["method"] == prereg["calibration_method"]
        and isinstance(calibration["zones"], dict) and set(calibration["zones"]) == {"front", "back"},
        "calibration report does not bind the preregistered method/targets",
    )
    for zone in ("front", "back"):
        entry = calibration["zones"][zone]
        require(set(entry) == {"target_count", "per_target_abs_errors", "max_abs_error"}, f"{zone} calibration fields invalid")
        errors = entry["per_target_abs_errors"]
        require(
            entry["target_count"] == 2649
            and isinstance(errors, list) and len(errors) == 2649
            and all(type(value) in (int, float) and math.isfinite(value) and value >= 0 for value in errors)
            and type(entry["max_abs_error"]) in (int, float)
            and math.isfinite(entry["max_abs_error"])
            and abs(entry["max_abs_error"] - max(errors)) <= 1e-12
            and 0 <= entry["max_abs_error"] <= prereg["calibration_tolerance"],
            f"{zone} calibration evidence fails the preregistered tolerance or target coverage",
        )
    return [
        {"path": denominator["ledger"]["path"], "sha256": ledger_digest},
        {"path": denominator["run_manifest"]["path"], "sha256": run_manifest_digest},
    ]



def _checks_pass(
    checks: Any, label: str, root: Path, release_manifest: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    required = GATE_REQUIRED_CHECKS[label]
    if not isinstance(checks, list):
        raise ReceiptVerificationError(f"{label}: checks must be an array")
    indexed: dict[str, dict[str, Any]] = {}
    for check in checks:
        if not isinstance(check, dict) or set(check) != {"check_id", "status", "evidence"}:
            raise ReceiptVerificationError(f"{label}: check shape invalid")
        check_id = check["check_id"]
        if not isinstance(check_id, str) or check_id in indexed:
            raise ReceiptVerificationError(f"{label}: check ID missing or duplicated")
        indexed[check_id] = check
    if set(indexed) != set(required):
        raise ReceiptVerificationError(f"{label}: required check inventory mismatch")
    verified: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    raw_by_check: dict[str, bytes] = {}
    for check_id in required:
        check = indexed[check_id]
        if check["status"] != "PASS":
            raise ReceiptVerificationError(f"{label}: check {check_id} did not pass")
        evidence_raw, digest = _safe_file(root, check["evidence"], label + " " + check_id)
        if label == "G2":
            _verify_g2_evidence(check_id, evidence_raw)
        if label == "G3":
            raw_by_check[check_id] = evidence_raw
        path = check["evidence"]["path"]
        if path in seen_paths:
            raise ReceiptVerificationError(f"{label}: check evidence must be unique")
        seen_paths.add(path)
        verified.append({"path": path, "sha256": digest})
    if label == "G3":
        nested = _verify_g3_evidence_bundle(raw_by_check, root, release_manifest=release_manifest)
        for item in nested:
            if item["path"] in seen_paths or item["sha256"] in {entry["sha256"] for entry in verified}:
                raise ReceiptVerificationError("G3 terminal ledger evidence must be unique")
            verified.append(item)
    return verified


def verify_gate_receipt(
    manifest: dict[str, Any], gate_result: dict[str, Any], evidence_root: str | Path,
) -> dict[str, Any]:
    """Verify one gate's typed receipt; gate status is derived, never caller-supplied."""
    if not isinstance(gate_result, dict):
        raise ReceiptVerificationError("gate result must be an object")
    gate_id = gate_result.get("gate_id")
    if not isinstance(gate_id, str) or gate_id not in GATE_TYPES or set(gate_result) != {"gate_id", "receipt"}:
        raise ReceiptVerificationError("gate result must contain only gate_id and receipt")
    root = Path(evidence_root).resolve(strict=True)
    raw, digest = _safe_file(root, gate_result["receipt"], gate_id)
    receipt = _strict_json(raw, gate_id)
    required = {
        "schema", "receipt_type", "gate_id", "release_id", "source_commit",
        "release_manifest_sha256", "result", "checks", "generated_at_utc",
    }
    if set(receipt) != required:
        raise ReceiptVerificationError(f"{gate_id}: gate receipt fields invalid")
    expected_manifest = "sha256:" + hashlib.sha256(canonicalize(manifest)).hexdigest()
    if (
        receipt["schema"] != "lottery.gate-receipt/v1"
        or receipt["receipt_type"] != GATE_TYPES[gate_id]
        or receipt["gate_id"] != gate_id
        or receipt["release_id"] != manifest.get("release_id")
        or receipt["source_commit"] != manifest.get("source_commit")
        or receipt["release_manifest_sha256"] != expected_manifest
        or receipt["result"] != "PASS"
    ):
        raise ReceiptVerificationError(f"{gate_id}: receipt does not bind this release and gate")
    if not GIT_SHA.fullmatch(str(receipt["source_commit"])):
        raise ReceiptVerificationError(f"{gate_id}: source commit must be full Git SHA")
    check_evidence = _checks_pass(receipt["checks"], gate_id, root, release_manifest=manifest)
    _utc_timestamp(receipt["generated_at_utc"], gate_id)
    return {
        "gate_id": gate_id, "receipt_sha256": digest, "status": "PASS",
        "check_evidence": check_evidence,
    }


def verify_fault_receipt(
    manifest: dict[str, Any], fault_result: dict[str, Any], evidence_root: str | Path,
) -> dict[str, str]:
    """Verify a fault-specific recovery receipt, including no partial output."""
    if not isinstance(fault_result, dict):
        raise ReceiptVerificationError("fault result must be an object")
    fault_id = fault_result.get("fault_id")
    if not isinstance(fault_id, str) or fault_id not in FAULTS or set(fault_result) != {"fault_id", "receipt"}:
        raise ReceiptVerificationError("fault result must contain only fault_id and receipt")
    root = Path(evidence_root).resolve(strict=True)
    raw, digest = _safe_file(root, fault_result["receipt"], fault_id)
    receipt = _strict_json(raw, fault_id)
    required = {
        "schema", "fault_id", "release_id", "source_commit",
        "release_manifest_sha256", "injection_method", "expected_state",
        "observed_state", "recovery_action", "output_publication",
        "runner_commit", "evidence", "generated_at_utc",
    }
    if set(receipt) != required:
        raise ReceiptVerificationError(f"{fault_id}: fault receipt fields invalid")
    expected_manifest = "sha256:" + hashlib.sha256(canonicalize(manifest)).hexdigest()
    if (
        receipt["schema"] != "lottery.fault-receipt/v1"
        or receipt["fault_id"] != fault_id
        or receipt["release_id"] != manifest.get("release_id")
        or receipt["source_commit"] != manifest.get("source_commit")
        or receipt["release_manifest_sha256"] != expected_manifest
        or not isinstance(receipt["injection_method"], str) or not receipt["injection_method"].strip()
        or not isinstance(receipt["expected_state"], str) or not receipt["expected_state"].strip()
        or receipt["observed_state"] != receipt["expected_state"]
        or not isinstance(receipt["recovery_action"], str) or not receipt["recovery_action"].strip()
        or receipt["output_publication"] != "none"
        or not isinstance(receipt["runner_commit"], str)
        or not GIT_SHA.fullmatch(receipt["runner_commit"])
    ):
        raise ReceiptVerificationError(f"{fault_id}: fault receipt contract mismatch")
    _utc_timestamp(receipt["generated_at_utc"], fault_id)
    evidence_raw, evidence_digest = _safe_file(root, receipt["evidence"], fault_id + " evidence")
    if not evidence_raw:
        raise ReceiptVerificationError(f"{fault_id}: fault evidence must not be empty")
    return {
        "fault_id": fault_id, "receipt_sha256": digest,
        "evidence_sha256": evidence_digest, "status": "PASS",
    }


V2_SCALAR_REFS = (
    "workflow_policy", "dependency_lock", "readiness_policy", "canonical_snapshot",
    "source_evidence_ledger", "runtime_toolchain", "sbom", "security_scan",
    "experiment_registration", "champion_registry_snapshot", "sampler_rng",
    "storage_commit_receipts", "backup_generation", "independent_restore_receipt",
)


def verify_release_manifest_v2(
    manifest: dict[str, Any], evidence_root: str | Path,
) -> dict[str, Any]:
    """Verify every immutable release-tuple reference against its actual bytes."""
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema", "release_id", "release_ref", "source_commit", "lot042_accessed", "evidence",
    }:
        raise ReceiptVerificationError("v2 release manifest has missing or unknown fields")
    if manifest["schema"] != "lottery.release-manifest/v2":
        raise ReceiptVerificationError("unsupported v2 release manifest schema")
    if (
        not isinstance(manifest["release_id"], str) or not manifest["release_id"]
        or not isinstance(manifest["source_commit"], str)
        or not GIT_SHA.fullmatch(manifest["source_commit"])
        or manifest["release_ref"] != manifest["source_commit"]
        or type(manifest["lot042_accessed"]) is not bool
    ):
        raise ReceiptVerificationError("v2 release identity, immutable ref or LOT-042 flag invalid")
    evidence = manifest["evidence"]
    required = set(V2_SCALAR_REFS) | {"evaluation_manifests", "model_artifacts"}
    if not isinstance(evidence, dict) or set(evidence) != required:
        raise ReceiptVerificationError("v2 release evidence inventory has missing or unknown refs")
    root = Path(evidence_root).resolve(strict=True)
    references: list[tuple[str, Any]] = [(key, evidence[key]) for key in V2_SCALAR_REFS]
    for collection in ("evaluation_manifests", "model_artifacts"):
        values = evidence[collection]
        if not isinstance(values, list) or not values:
            raise ReceiptVerificationError(f"v2 {collection} must be a non-empty array")
        references.extend((f"{collection}[{i}]", item) for i, item in enumerate(values))
    verified: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for label, reference in references:
        _, digest = _safe_file(root, reference, "manifest " + label)
        path = reference["path"]
        if path in seen_paths:
            raise ReceiptVerificationError("v2 manifest evidence paths must be unique")
        seen_paths.add(path)
        verified.append({"name": label, "path": path, "sha256": digest})
    return {
        "release_manifest_sha256": "sha256:" + hashlib.sha256(canonicalize(manifest)).hexdigest(),
        "verified_evidence": verified,
    }


def verify_receipt_set(
    manifest: dict[str, Any],
    gate_results: list[dict[str, Any]],
    fault_results: list[dict[str, Any]],
    evidence_root: str | Path,
) -> dict[str, Any]:
    """Verify complete, non-reused typed receipt inventory and derive readiness."""
    if not isinstance(manifest, dict):
        raise ReceiptVerificationError("release manifest must be an object")
    manifest_evidence: list[dict[str, str]] = []
    if manifest.get("schema") == "lottery.release-manifest/v2":
        manifest_evidence = verify_release_manifest_v2(manifest, evidence_root)["verified_evidence"]
    elif manifest.get("schema") == "lottery.release-manifest/v1":
        if (
            not isinstance(manifest.get("release_id"), str) or not manifest["release_id"]
            or not isinstance(manifest.get("source_commit"), str)
            or not GIT_SHA.fullmatch(manifest["source_commit"])
            or manifest.get("release_ref") != manifest.get("source_commit")
        ):
            raise ReceiptVerificationError("manifest release identity/ref is invalid or mutable")
        for field in ("workflow_policy_sha256", "dependency_lock_sha256", "readiness_policy_sha256", "snapshot_sha256"):
            if not isinstance(manifest.get(field), str) or not SHA256.fullmatch(manifest[field]):
                raise ReceiptVerificationError(f"manifest {field} must be a lowercase SHA-256")
        if type(manifest.get("lot042_accessed")) is not bool:
            raise ReceiptVerificationError("manifest LOT-042 isolation must be explicit")
    else:
        raise ReceiptVerificationError("unsupported release manifest schema")
    if not isinstance(gate_results, list) or not isinstance(fault_results, list):
        raise ReceiptVerificationError("gate and fault receipt inventories must be arrays")
    if any(not isinstance(item, dict) or not isinstance(item.get("gate_id"), str) for item in gate_results):
        raise ReceiptVerificationError("gate receipt inventory contains a malformed entry")
    if any(not isinstance(item, dict) or not isinstance(item.get("fault_id"), str) for item in fault_results):
        raise ReceiptVerificationError("fault receipt inventory contains a malformed entry")
    gates = {item["gate_id"]: item for item in gate_results}
    faults = {item["fault_id"]: item for item in fault_results}
    if len(gates) != len(gate_results) or set(gates) != set(GATE_TYPES):
        raise ReceiptVerificationError("gate receipt inventory must contain each G0-G8 exactly once")
    if len(faults) != len(fault_results) or set(faults) != set(FAULTS):
        raise ReceiptVerificationError("fault receipt inventory must contain each F01-F15 exactly once")
    verified_gates = [
        verify_gate_receipt(manifest, gates[key], evidence_root) for key in GATE_TYPES
    ]
    verified_faults = [
        verify_fault_receipt(manifest, faults[key], evidence_root) for key in FAULTS
    ]
    identities = [item["receipt_sha256"] for item in verified_gates + verified_faults]
    paths = [gates[key]["receipt"]["path"] for key in GATE_TYPES]
    paths += [faults[key]["receipt"]["path"] for key in FAULTS]
    evidence_records = [
        entry
        for gate in verified_gates for entry in gate["check_evidence"]
    ]
    evidence_records += manifest_evidence
    for key in FAULTS:
        fault_raw, _ = _safe_file(
            Path(evidence_root).resolve(strict=True), faults[key]["receipt"], key
        )
        fault_receipt = _strict_json(fault_raw, key)
        evidence_records.append({
            "path": fault_receipt["evidence"]["path"],
            "sha256": fault_receipt["evidence"]["sha256"],
        })
    evidence_paths = [entry["path"] for entry in evidence_records]
    evidence_digests = [entry["sha256"] for entry in evidence_records]
    if (
        len(set(identities)) != len(identities)
        or len(set(paths)) != len(paths)
        or len(set(evidence_paths)) != len(evidence_paths)
        or len(set(evidence_digests)) != len(evidence_digests)
        or set(evidence_paths) & set(paths)
    ):
        raise ReceiptVerificationError("receipt and evidence files/digests must be unique per gate and fault")
    return {
        "schema": "lottery.readiness-receipt-verification/v1",
        "release_id": manifest["release_id"],
        "release_manifest_sha256": "sha256:" + hashlib.sha256(canonicalize(manifest)).hexdigest(),
        "readiness": "NOT_READY",
        "receipt_completeness": (
            "COMPLETE" if manifest["lot042_accessed"] is False else "BLOCKED_LOT042"
        ),
        "shadow_authorized": False,
        "production_ready": False,
        "release_manifest_evidence": manifest_evidence,
        "gate_receipts": verified_gates,
        "fault_receipts": verified_faults,
        "lot042_accessed": manifest["lot042_accessed"],
        "authenticity_note": "SHA-256 verifies integrity only; receipt producer authenticity and official-source authority are not established by this offline verifier.",
    }

