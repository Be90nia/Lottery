"""Immutable LOT-055 run manifest, model artifacts, and normalized score ledger."""
from __future__ import annotations

import hashlib
import json
import platform
import sys
from pathlib import Path

from lottery.subset_model.artifact import canonicalize, verify_artifact


MODEL_ORDER = ("uniform", "expanding", "ewma", "exponential_family")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_object(value: dict) -> str:
    return "sha256:" + _sha256(canonicalize(value))


def _model_identity(zone: str, name: str, m: int, k: int,
                    active_features: list[str], candidate_features: list[str],
                    zero_variance_features: list[str], uniform_means: list[float],
                    uniform_stds: list[float]) -> tuple[str, str, dict]:
    if name == "uniform":
        family = "uniform_analytic"
        config = {"model_family": family, "zone": zone, "population_size": m,
                  "selection_size": k, "probability": "1/C(m,k)"}
        schema = {"schema": "uniform-subset-v1", "population_size": m, "selection_size": k}
    elif name in ("expanding", "ewma"):
        family = "conditional_poisson"
        schema = {
            "version": "lottery-item-inclusion/v1",
            "names": [f"item_{item}" for item in range(1, m + 1)],
            "uniform_means": [k / m] * m,
            "uniform_population_stds": [((k / m) * (1.0 - k / m)) ** 0.5] * m,
            "zero_variance_policy": "not_applicable_item_indicator_schema",
        }
        config = {"model_family": family, "baseline": name, "zone": zone,
                  "population_size": m, "selection_size": k, "alpha": 100.0,
                  "half_life": 100.0 if name == "ewma" else None,
                  "weighting": "expanding" if name == "expanding" else "2^(-lag/100)",
                  "feature_schema_hash": _hash_object(schema)}
    else:
        family = "complete_subset_exponential"
        schema = {
            "version": "lot-051-symmetric-v1",
            "names": active_features,
            "uniform_means": uniform_means,
            "uniform_population_stds": uniform_stds,
            "zero_variance_policy": "drop_and_record",
            "candidate_names": candidate_features,
            "zero_variance_features": zero_variance_features,
        }
        config = {
            "model_family": "complete_subset_exponential", "zone": zone,
            "population_size": m, "selection_size": k,
            "feature_schema_hash": _hash_object(schema),
            "objective_scale": "mean_nll", "regularization_lambda": 1.0,
            "solver": "deterministic_unbounded_lbfgsb_strong_wolfe_v1",
            "max_iterations": 5000, "gradient_tolerance": 1e-8,
        }
    return family, _hash_object(config), schema


def write_immutable_outputs(result: dict, rows: list[dict], snapshot_path: Path,
                            output_path: Path) -> dict:
    """Validate and write one row per model × zone × target, plus artifacts/manifest."""
    code_revision = result["code_commit"]
    snapshot_digest = result["snapshot_sha256"]
    expected_seed_schedule = {
        "front": {"uniform": 20261118, "expanding": 20261119, "ewma": 20261120},
        "back": {"uniform": 20261119, "expanding": 20261120, "ewma": 20261121},
    }
    bootstrap = result.get("bootstrap", {})
    if (bootstrap.get("replicates") != 1000 or bootstrap.get("block_length") != 50
            or bootstrap.get("seed") != 20261118
            or bootstrap.get("seeds_by_zone_and_comparison") != expected_seed_schedule):
        raise ValueError("bootstrap settings or per-zone seed schedule differ from frozen LOT-055 child protocol")
    target_rows = rows[300:]
    target_list = [{"target_draw_id": row["draw_id"], "target_draw_date": row["draw_date"]}
                   for row in target_rows]
    target_list_hash = _hash_object({"targets": target_list})
    model_specs = {
        zone: {
            "m": result[zone]["population_size"], "k": result[zone]["selection_size"],
            "features": result[zone]["active_feature_names"],
            "candidate_features": result[zone]["candidate_feature_names"],
            "zero_variance_features": result[zone]["zero_variance_features"],
            "uniform_means": result[zone]["uniform_feature_means"],
            "uniform_stds": result[zone]["uniform_feature_standard_deviations"],
        }
        for zone in ("front", "back")
    }
    identity = {
        "protocol": "LOT-055",
        "snapshot_sha256": snapshot_digest,
        "target_list_sha256": target_list_hash,
        "code_revision": code_revision,
        "model_spec_revision": "PR-16@aec3a864ea14d84b8b9fac971e0d4b08e72cb0c0",
        "preregistration_revision": "Be90nia/Lottery#18",
        "experiment_registration_revision": "Be90nia/Lottery#27-comment-7028060751",
        "bootstrap": result["bootstrap"],
        "models": model_specs,
    }
    run_id = "lot055-" + _sha256(canonicalize(identity))[:24]
    model_config_hashes = {}
    feature_schema_hashes = {}
    families = {}
    for zone, spec in model_specs.items():
        for name in MODEL_ORDER:
            family, config_hash, schema = _model_identity(
                zone, name, spec["m"], spec["k"], spec["features"],
                spec["candidate_features"], spec["zero_variance_features"],
                spec["uniform_means"], spec["uniform_stds"])
            model_config_hashes[(zone, name)] = config_hash
            feature_schema_hashes[(zone, name)] = _hash_object(schema)
            families[(zone, name)] = family

    ledger = []
    artifact_lines = []
    artifact_ids = set()
    expected = len(target_rows) * len(model_specs) * len(MODEL_ORDER)
    for zone in ("front", "back"):
        zone_result = result[zone]
        m, k = model_specs[zone]["m"], model_specs[zone]["k"]
        active_features = zone_result.get("active_feature_names", model_specs[zone]["features"])
        records = zone_result["target_records"]
        if len(records) != len(target_rows):
            raise ValueError(f"{zone}: target checkpoint denominator mismatch")
        for offset, (record, target_row) in enumerate(zip(records, target_rows)):
            if record.get("target_draw_id") != target_row["draw_id"]:
                raise ValueError(f"{zone}: target order mismatch at {offset}")
            if record.get("target_draw_date") != target_row["draw_date"]:
                raise ValueError(f"{zone}: target date mismatch at {offset}")
            if record.get("training_dates_strictly_before_target") is not True:
                raise ValueError(f"{zone}: target {target_row['draw_id']} lacks strict cutoff assertion")
            if record.get("observed_subset") != target_row[f"{zone}_numbers"]:
                raise ValueError(f"{zone}: observed subset mismatch at {target_row['draw_id']}")
            training = rows[:300 + offset]
            if not training or training[0]["draw_id"] != record["training_first_draw_id"] \
                    or training[-1]["draw_id"] != record["training_last_draw_id"] \
                    or len(training) != record["training_count"]:
                raise ValueError(f"{zone}: training range mismatch at {target_row['draw_id']}")
            if any(item["draw_date"] >= target_row["draw_date"] for item in training):
                raise ValueError(f"{zone}: chronological leakage at {target_row['draw_id']}")
            pairing_key = f"{run_id}:{zone}:{target_row['draw_id']}"
            scores = record["exact_set_nll"]
            statuses = record["fit_statuses"]
            artifacts = record["model_artifacts"]
            for name in MODEL_ORDER:
                score = scores[name if name != "exponential_family" else "exponential_family"]
                family = families[(zone, name)]
                artifact_entry = None if name == "uniform" else artifacts.get(
                    "candidate" if name == "exponential_family" else name)
                artifact_id = None
                solver_status = "analytic_closed_form" if name == "uniform" else statuses[
                    "candidate" if name == "exponential_family" else name]
                converged = name == "uniform" or solver_status == "converged"
                failure_reason = None
                status = "scored" if score is not None else "fit_failed"
                if name != "uniform" and artifact_entry is None:
                    status, failure_reason = "artifact_invalid", "fit_attempt_missing_diagnostic_artifact"
                elif artifact_entry is not None:
                    payload = artifact_entry.get("payload")
                    if not isinstance(payload, dict):
                        status, failure_reason = "artifact_invalid", "artifact_payload_missing"
                    else:
                        verified = verify_artifact(canonicalize(payload))
                        artifact_id = verified["artifact_id"]
                        expected_artifact_type = "fitted_model" if score is not None else "fit_failure"
                        expected_family = "complete_subset_exponential" if name == "exponential_family" else "conditional_poisson"
                        if artifact_id != artifact_entry.get("artifact_id"):
                            status, failure_reason = "artifact_invalid", "artifact_id_mismatch"
                        elif (verified.get("artifact_type") != expected_artifact_type
                              or verified.get("zone") != zone
                              or verified.get("model_family") != expected_family
                              or verified.get("population_size") != m
                              or verified.get("selection_size") != k
                              or verified.get("training_snapshot_sha256") != snapshot_digest
                              or verified.get("training_cutoff_draw_id") != record["training_cutoff_draw_id"]
                              or verified.get("training_row_count") != record["training_count"]
                              or verified.get("model_configuration_hash") != model_config_hashes[(zone, name)]
                              or verified.get("feature_schema_hash") != feature_schema_hashes[(zone, name)]):
                            status, failure_reason = "artifact_invalid", "artifact_provenance_or_schema_mismatch"
                        else:
                            artifact_bytes = canonicalize(verified)
                            if artifact_id not in artifact_ids:
                                artifact_lines.append(artifact_bytes)
                                artifact_ids.add(artifact_id)
                if score is None and failure_reason is None:
                    failure_reason = str(solver_status)
                log_probability = None if score is None else -float(score)
                if log_probability is not None and (not math_isfinite(log_probability) or log_probability > 1e-12):
                    status, failure_reason, log_probability, score = (
                        "probability_invalid", "non_finite_or_positive_log_probability", None, None)
                if status == "artifact_invalid":
                    log_probability, score = None, None
                row = {
                    "run_id": run_id,
                    "target_draw_id": target_row["draw_id"],
                    "target_draw_date": target_row["draw_date"],
                    "zone": zone,
                    "model_family": family,
                    "model_name": name,
                    "artifact_id": artifact_id,
                    "diagnostic_ref": artifact_id if status != "scored" else None,
                    "snapshot_sha256": snapshot_digest,
                    "training_first_draw_id": record["training_first_draw_id"],
                    "training_last_draw_id": record["training_last_draw_id"],
                    "training_row_count": record["training_count"],
                    "training_dates_strictly_before_target": True,
                    "model_configuration_hash": model_config_hashes[(zone, name)],
                    "feature_schema_hash": feature_schema_hashes[(zone, name)],
                    "optimizer_solver_status": solver_status,
                    "converged": bool(converged),
                    "failure_reason": failure_reason,
                    "terminal_status": status,
                    "observed_subset": record["observed_subset"],
                    "predicted_log_probability": log_probability,
                    "negative_log_score": score,
                    "pairing_key": pairing_key,
                }
                row["record_sha256"] = _hash_object(row)
                ledger.append(row)

    keys = [(row["zone"], row["model_name"], row["target_draw_id"]) for row in ledger]
    if len(ledger) != expected or len(set(keys)) != expected:
        raise ValueError("normalized target ledger has missing or duplicate model × zone × target rows")
    for zone in ("front", "back"):
        for name in MODEL_ORDER:
            count = sum(1 for row in ledger if row["zone"] == zone and row["model_name"] == name)
            if count != len(target_rows):
                raise ValueError(f"ledger denominator mismatch for {zone}/{name}")

    ledger_bytes = b"".join(canonicalize(row) + b"\n" for row in ledger)
    artifact_file_bytes = b"".join(line + b"\n" for line in artifact_lines)
    artifact_code_revisions = sorted({
        json.loads(line.decode("utf-8"))["code_revision"]
        for line in artifact_lines
    })
    manifest = {
        "schema": "lot-055-run-manifest-v1",
        "run_id": run_id,
        "protocol": "LOT-055 frozen rolling-origin exact-subset evaluation",
        "experiment_id": "LOT055-OPT-DIAG-20261120",
        "experiment_class": "exploratory_diagnostic",
        "confirmatory_eligible": False,
        "confirmatory_ineligibility_reason": "post-outcome optimizer repair; see Issue #27 child registration",
        "snapshot": {
            "path": str(snapshot_path),
            "sha256": snapshot_digest,
            "row_count": len(rows),
            "first_draw_id": rows[0]["draw_id"],
            "last_draw_id": rows[-1]["draw_id"],
            "trust_status": result["snapshot_trust_status"],
            "source_commit": result["snapshot_source_commit"],
        },
        "target_manifest": {
            "target_count_per_zone": len(target_rows),
            "first_target_draw_id": target_rows[0]["draw_id"],
            "last_target_draw_id": target_rows[-1]["draw_id"],
            "target_list_sha256": target_list_hash,
        },
        "code_revision": code_revision,
        "artifact_code_revisions": artifact_code_revisions,
        "model_spec_revision": identity["model_spec_revision"],
        "preregistration_revision": identity["preregistration_revision"],
        "experiment_registration_revision": identity["experiment_registration_revision"],
        "runtime": {
            "python_version": sys.version,
            "python_implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "dependencies": {},
            "dependency_lock_sha256": None,
        },
        "models": [
            {"zone": zone, "model_name": name, "model_family": families[(zone, name)],
             "model_configuration_hash": model_config_hashes[(zone, name)],
             "feature_schema_hash": feature_schema_hashes[(zone, name)]}
            for zone in ("front", "back") for name in MODEL_ORDER
        ],
        "bootstrap": result["bootstrap"],
        "metrics": {
            "primary": "exact observed unordered-subset negative log probability",
            "paired_difference": "candidate NLL minus comparator NLL; negative favors candidate",
            "comparators": ["uniform", "expanding", "ewma"],
            "confidence_interval": "two-sided 95% paired non-circular moving-block percentile interval",
            "block_boundary": "sample contiguous non-circular blocks with starts 0..n-50, concatenate, truncate to n",
        },
        "expected_target_record_count": expected,
        "actual_target_record_count": len(ledger),
        "model_artifact_count": len(artifact_lines),
        "output_files": {
            "target-score-ledger.jsonl": {"sha256": _sha256(ledger_bytes), "bytes": len(ledger_bytes)},
            "model-artifacts.jsonl": {"sha256": _sha256(artifact_file_bytes), "bytes": len(artifact_file_bytes)},
        },
        "terminal_status_counts": {
            status: sum(1 for row in ledger if row["terminal_status"] == status)
            for status in ("scored", "fit_failed", "artifact_invalid", "probability_invalid", "runner_error")
        },
        "status": "complete" if all(row["terminal_status"] == "scored" for row in ledger) else "complete_with_explicit_failures",
    }
    manifest["manifest_sha256"] = _hash_object(manifest)
    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "run_manifest.json").write_bytes(canonicalize(manifest) + b"\n")
    (output_dir / "target-score-ledger.jsonl").write_bytes(ledger_bytes)
    (output_dir / "model-artifacts.jsonl").write_bytes(artifact_file_bytes)
    return {
        "run_id": run_id,
        "manifest_sha256": manifest["manifest_sha256"],
        "expected_target_record_count": expected,
        "actual_target_record_count": len(ledger),
        "model_artifact_count": len(artifact_lines),
        "terminal_status_counts": manifest["terminal_status_counts"],
    }


def math_isfinite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))
