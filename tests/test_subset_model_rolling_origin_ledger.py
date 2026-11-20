import datetime
import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

from lottery.subset_model.artifact import create_artifact
from lottery.subset_model.rolling_origin_ledger import (
    MODEL_ORDER,
    _hash_object,
    _model_identity,
    write_immutable_outputs,
)


def _fixture(fail_candidate=False):
    rows = []
    first = datetime.date(2007, 1, 1)
    for index in range(301):
        day = first + datetime.timedelta(days=index)
        rows.append({
            "draw_id": f"{7001 + index:05d}",
            "draw_date": day.isoformat(),
            "front_numbers": [1, 7, 13, 21, 35],
            "back_numbers": [2, 11],
        })
    snapshot_hash = "a" * 64
    records = {}
    for zone, m, k, active, candidate_features in (
        ("front", 35, 5, ["sum", "odd_count", "range", "adjacent_count", "gap_variance"],
         ["sum", "odd_count", "range", "adjacent_count", "gap_variance"]),
        ("back", 12, 2, ["sum", "odd_count", "range", "adjacent_count"],
         ["sum", "odd_count", "range", "adjacent_count"]),
    ):
        zero_variance = []
        means = [0.0] * len(active)
        stds = [1.0] * len(active)
        target = rows[300][f"{zone}_numbers"]
        feature_schema = {
            "version": "lot-051-symmetric-v1", "names": active,
            "uniform_means": means, "uniform_population_stds": stds,
            "zero_variance_policy": "drop_and_record",
            "candidate_names": candidate_features,
            "zero_variance_features": zero_variance,
        }
        _, candidate_config_hash, _ = _model_identity(
            zone, "exponential_family", m, k, active, candidate_features,
            zero_variance, means, stds)
        feature_schema_hash = _hash_object(feature_schema)
        candidate_config = {
            "model_family": "complete_subset_exponential", "zone": zone,
            "population_size": m, "selection_size": k,
            "feature_schema_hash": feature_schema_hash,
            "objective_scale": "mean_nll", "regularization_lambda": 1.0,
            "solver": "deterministic_unbounded_lbfgsb_strong_wolfe_v1",
            "max_iterations": 5000, "gradient_tolerance": 1e-8,
        }
        runtime = {"python": "3.12"}
        training = {
            "snapshot_sha256": snapshot_hash, "row_count": 300,
            "first_draw_id": rows[0]["draw_id"],
            "last_draw_id": rows[299]["draw_id"],
            "cutoff_draw_id": rows[299]["draw_id"], "cutoff_inclusive": True,
        }
        support = {
            "population_size": m, "selection_size": k,
            "support_count": math.comb(m, k), "subset_order": "lexicographic_ascending",
        }
        theta = [0.0] * len(active)
        candidate_payload = {
            "schema_version": 1, "artifact_schema": "lottery.subset-probability-model/v1",
                    "artifact_type": "fitted_model",
            "model_family": "complete_subset_exponential",
            "zone": zone, "population_size": m, "selection_size": k,
            "support": support, "feature_schema": feature_schema,
            "parameters": {"theta": theta, "parameter_order": "feature_schema.names"},
            "model_configuration": candidate_config,
            "normalization": {"method": "full_support_logsumexp",
                              "log_partition": 0.0, "numeric_dtype": "float64"},
            "fit": {"status": "converged", "termination_reason": "gradient_tolerance",
                    "objective": 0.0, "gradient_inf_norm": 0.0, "iterations": 1,
                    "optimizer": "L-BFGS-B", "lambda": 1.0},
            "training": training,
            "implementation": {
                "code_revision": "abc123", "runtime": runtime, "library_versions": {},
                "rng_algorithm": "injected_rng.random_v1",
            },
            "training_snapshot_sha256": snapshot_hash,
            "training_first_draw_id": rows[0]["draw_id"],
            "training_last_draw_id": rows[299]["draw_id"],
            "training_cutoff_draw_id": rows[299]["draw_id"],
            "training_row_count": 300, "code_revision": "abc123", "runtime": runtime,
            "fit_diagnostics": {"terminal_status": "converged", "converged": True,
                                "gradient_infinity_norm": 0.0},
            "forecast_ready": False,
            "feature_schema_version": "lot-051-symmetric-v1",
            "candidate_feature_names": candidate_features,
            "active_feature_names": active, "zero_variance_features": zero_variance,
            "feature_schema_hash": feature_schema_hash,
            "model_configuration_hash": candidate_config_hash,
            "theta": theta, "objective_scale": "mean_nll", "regularization_lambda": 1.0,
        }
        candidate_bytes, candidate_id = create_artifact(candidate_payload)
        artifacts = {"candidate": {
            "artifact_id": candidate_id, "payload": json.loads(candidate_bytes)
        }}
        statuses = {"candidate": "converged", "expanding": "converged", "ewma": "converged"}
        scores = {
            "uniform": math.log(math.comb(m, k)),
            "expanding": math.log(math.comb(m, k)) - 0.1,
            "ewma": math.log(math.comb(m, k)) - 0.05,
            "exponential_family": math.log(math.comb(m, k)) - 0.2,
        }
        p = k / m
        baseline_schema = {
            "version": "lottery-item-inclusion/v1",
            "names": [f"item_{item}" for item in range(1, m + 1)],
            "uniform_means": [p] * m,
            "uniform_population_stds": [(p * (1.0 - p)) ** 0.5] * m,
            "zero_variance_policy": "not_applicable_item_indicator_schema",
        }
        for baseline in ("expanding", "ewma"):
            _, config_hash, schema = _model_identity(
                zone, baseline, m, k, active, candidate_features,
                zero_variance, means, stds)
            baseline_config = {
                "model_family": "conditional_poisson", "baseline": baseline,
                "zone": zone, "population_size": m, "selection_size": k,
                "alpha": 100.0, "half_life": 100.0 if baseline == "ewma" else None,
                "weighting": "expanding" if baseline == "expanding" else "2^(-lag/100)",
                "feature_schema_hash": _hash_object(schema),
            }
            baseline_payload = {
                "schema_version": 1, "artifact_schema": "lottery.subset-probability-model/v1",
                    "artifact_type": "fitted_model",
                "model_family": "conditional_poisson",
                "zone": zone, "population_size": m, "selection_size": k,
                "support": support, "feature_schema": schema,
                "parameters": {"centered_log_weights": [0.0] * m,
                               "parameter_order": "feature_schema.names"},
                "model_configuration": baseline_config,
                "normalization": {"method": "exact_conditional_poisson_log_space_dp",
                                  "log_partition": 0.0, "numeric_dtype": "float64"},
                "fit": {"status": "converged", "termination_reason": "gradient_tolerance",
                        "objective": 0.0, "gradient_inf_norm": 0.0, "iterations": 1,
                        "optimizer": "conditional_poisson_calibration_lbfgs_v1", "lambda": None},
                "training": training,
                "implementation": {
                    "code_revision": "abc123", "runtime": runtime, "library_versions": {},
                    "rng_algorithm": "conditional_poisson_backward_dp_with_injected_rng_v1",
                },
                "training_snapshot_sha256": snapshot_hash,
                "training_first_draw_id": rows[0]["draw_id"],
                "training_last_draw_id": rows[299]["draw_id"],
                "training_cutoff_draw_id": rows[299]["draw_id"],
                "training_row_count": 300, "code_revision": "abc123", "runtime": runtime,
                "fit_diagnostics": {"terminal_status": "converged", "converged": True},
                "forecast_ready": False,
                "centered_log_weights": [0.0] * m,
                "target_marginals": [p] * m, "achieved_marginals": [p] * m,
                "solver_status": "converged", "calibration_residual": 0.0,
                "feature_schema_hash": _hash_object(schema),
                "model_configuration_hash": config_hash,
            }
            raw, artifact_id = create_artifact(baseline_payload)
            artifacts[baseline] = {"artifact_id": artifact_id, "payload": json.loads(raw)}
        if fail_candidate:
            statuses["candidate"] = "line_search_failed"
            scores["exponential_family"] = None
            failure_payload = dict(candidate_payload)
            failure_payload["artifact_type"] = "fit_failure"
            failure_payload["fit"] = dict(
                failure_payload["fit"], status="line_search_failed",
                termination_reason="line search failed", objective=None,
                gradient_inf_norm=None,
            )
            failure_payload["fit_diagnostics"] = {
                "terminal_status": "line_search_failed", "converged": False,
                "message": "line search failed",
            }
            failure_payload["parameters"] = {
                "parameter_order": "feature_schema.names", "parameters_available": False,
            }
            failure_payload["normalization"] = {
                "method": "not_computed", "log_partition": None, "numeric_dtype": "float64",
            }
            failure_payload["failure_reason"] = "line_search_failed"
            failure_payload.pop("theta", None)
            failure_raw, failure_id = create_artifact(failure_payload)
            artifacts["candidate"] = {
                "artifact_id": failure_id, "payload": json.loads(failure_raw)
            }
        records[zone] = {
            "target_draw_id": rows[300]["draw_id"],
            "target_draw_date": rows[300]["draw_date"],
            "training_count": 300,
            "training_first_draw_id": rows[0]["draw_id"],
            "training_last_draw_id": rows[299]["draw_id"],
            "training_cutoff_draw_id": rows[299]["draw_id"],
            "training_dates_strictly_before_target": True,
            "observed_subset": target,
            "fit_statuses": statuses,
            "exact_set_nll": scores,
            "model_artifacts": artifacts,
        }
    result = {
        "snapshot_sha256": snapshot_hash,
        "code_commit": "abc123",
        "snapshot_source_commit": "def456",
        "snapshot_trust_status": "manifest_complete_not_officially_authenticated",
        "bootstrap": {
            "replicates": 1000, "block_length": 50, "seed": 20261118,
            "seeds_by_zone_and_comparison": {
                "front": {"uniform": 20261118, "expanding": 20261119, "ewma": 20261120},
                "back": {"uniform": 20261119, "expanding": 20261120, "ewma": 20261121},
            },
        },
    }
    for zone, m, k, active, candidate_features in (
        ("front", 35, 5, ["sum", "odd_count", "range", "adjacent_count", "gap_variance"],
         ["sum", "odd_count", "range", "adjacent_count", "gap_variance"]),
        ("back", 12, 2, ["sum", "odd_count", "range", "adjacent_count"],
         ["sum", "odd_count", "range", "adjacent_count"]),
    ):
        result[zone] = {
            "population_size": m, "selection_size": k,
            "active_feature_names": active,
            "candidate_feature_names": candidate_features,
            "zero_variance_features": [],
            "uniform_feature_means": [0.0] * len(active),
            "uniform_feature_standard_deviations": [1.0] * len(active),
            "target_records": [records[zone]],
        }
    return rows, result



class ImmutableRollingOriginLedgerTests(unittest.TestCase):
    def test_emits_exactly_one_record_per_model_zone_target_and_hashes_outputs(self):
        rows, result = _fixture()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            summary = write_immutable_outputs(result, rows, Path("snapshot.jsonl"), output)
            ledger_path = output.parent / "target-score-ledger.jsonl"
            manifest_path = output.parent / "run_manifest.json"
            artifacts_path = output.parent / "model-artifacts.jsonl"
            ledger = [json.loads(line) for line in ledger_path.read_text().splitlines()]
            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(len(ledger), 8)
            self.assertEqual(len({(r["zone"], r["model_name"], r["target_draw_id"]) for r in ledger}), 8)
            self.assertEqual({r["terminal_status"] for r in ledger}, {"scored"})
            self.assertTrue(all(r["pairing_key"].endswith(":07301") for r in ledger))
            self.assertEqual(summary["actual_target_record_count"], 8)
            self.assertEqual(manifest["expected_target_record_count"], 8)
            self.assertEqual(
                manifest["output_files"]["target-score-ledger.jsonl"]["sha256"],
                __import__("hashlib").sha256(ledger_path.read_bytes()).hexdigest(),
            )
            artifact_records = artifacts_path.read_text().splitlines()
            self.assertEqual(len(artifact_records), 6)

    def test_failed_fit_is_explicit_and_never_gets_a_score(self):
        rows, result = _fixture(fail_candidate=True)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            write_immutable_outputs(result, rows, Path("snapshot.jsonl"), output)
            ledger = [json.loads(line) for line in
                      (output.parent / "target-score-ledger.jsonl").read_text().splitlines()]
            candidate_rows = [r for r in ledger if r["model_name"] == "exponential_family"]
            self.assertEqual(len(candidate_rows), 2)
            self.assertTrue(all(r["terminal_status"] == "fit_failed" for r in candidate_rows))
            self.assertTrue(all(r["negative_log_score"] is None for r in candidate_rows))
            self.assertTrue(all(r["predicted_log_probability"] is None for r in candidate_rows))
            self.assertTrue(all(r["artifact_id"] and r["diagnostic_ref"] == r["artifact_id"]
                                for r in candidate_rows))

    def test_rejects_training_date_leakage_even_when_boolean_claim_is_true(self):
        rows, result = _fixture()
        rows[20]["draw_date"] = rows[300]["draw_date"]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "chronological leakage"):
                write_immutable_outputs(result, rows, Path("snapshot.jsonl"),
                                        Path(directory) / "result.json")


if __name__ == "__main__":
    unittest.main()
