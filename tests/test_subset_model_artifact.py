import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.subset_model.artifact import (
    ArtifactValidationError,
    canonicalize,
    create_artifact,
    parse_json_strict,
    verify_artifact,
)


def exponential_payload():
    names = ["sum", "odd_count", "range", "adjacent_count", "gap_variance"]
    runtime = {"python": "3.12"}
    training = {
        "snapshot_sha256": "a" * 64, "row_count": 2948,
        "first_draw_id": "07001", "last_draw_id": "26130",
        "cutoff_draw_id": "26130", "cutoff_inclusive": True,
    }
    feature_schema = {
        "version": "lot-051-symmetric-v1", "names": names,
        "uniform_means": [0.0] * 5, "uniform_population_stds": [1.0] * 5,
        "zero_variance_policy": "drop_and_record",
        "candidate_names": names, "zero_variance_features": [],
    }
    theta = [0.1, -0.2, 0.3, 0.0, 0.05]
    feature_schema_hash = "sha256:" + hashlib.sha256(canonicalize(feature_schema)).hexdigest()
    model_configuration = {
        "model_family": "complete_subset_exponential", "zone": "front",
        "population_size": 35, "selection_size": 5,
        "feature_schema_hash": feature_schema_hash,
        "objective_scale": "mean_nll", "regularization_lambda": 1.0,
        "solver": "L-BFGS-B", "max_iterations": 5000, "gradient_tolerance": 1e-8,
    }
    model_configuration_hash = "sha256:" + hashlib.sha256(canonicalize(model_configuration)).hexdigest()
    return {
        "schema_version": 1,
        "artifact_schema": "lottery.subset-probability-model/v1",
                    "artifact_type": "fitted_model",
        "model_family": "complete_subset_exponential",
        "zone": "front", "population_size": 35, "selection_size": 5,
        "support": {"population_size": 35, "selection_size": 5,
                    "support_count": 324632, "subset_order": "lexicographic_ascending"},
        "feature_schema": feature_schema,
        "parameters": {"theta": theta, "parameter_order": "feature_schema.names"},
        "normalization": {"method": "full_support_logsumexp",
                          "log_partition": 12.0, "numeric_dtype": "float64"},
        "fit": {"status": "converged", "termination_reason": "gradient_tolerance",
                "objective": 1.0, "gradient_inf_norm": 1e-9, "iterations": 10,
                "optimizer": "L-BFGS-B", "lambda": 1.0},
        "training": training,
        "implementation": {"code_revision": "abc123", "runtime": runtime,
                           "library_versions": {}, "rng_algorithm": "injected_rng.random_v1"},
        "training_snapshot_sha256": "a" * 64,
        "training_cutoff_draw_id": "26130", "training_row_count": 2948,
        "feature_schema_hash": feature_schema_hash,
        "model_configuration_hash": model_configuration_hash,
        "model_configuration": model_configuration,
        "training_first_draw_id": "07001", "training_last_draw_id": "26130",
        "code_revision": "abc123", "runtime": runtime,
        "fit_diagnostics": {"terminal_status": "converged", "gradient_infinity_norm": 1e-9},
        "forecast_ready": False,
        "feature_schema_version": "lot-051-symmetric-v1",
        "active_feature_names": names, "theta": theta,
        "objective_scale": "mean_nll", "regularization_lambda": 1.0,
    }



class JCSCanonicalizationTests(unittest.TestCase):
    def test_ecmascript_number_formatting_vectors(self):
        value = {
            "numbers": [
                333333333.33333329, 1e30, 4.5, 2e-3, 1e-27,
                1e-6, 1e-7, 1e20, 1e21, -0.0,
            ]
        }
        expected = (
            b'{"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27,'
            b'0.000001,1e-7,100000000000000000000,1e+21,0]}'
        )
        self.assertEqual(canonicalize(value), expected)

    def test_object_keys_sort_by_utf16_code_units(self):
        value = {"\ue000": 2, "😀": 1}
        self.assertEqual(canonicalize(value), '{"😀":1,"":2}'.encode("utf-8"))

    def test_strings_and_nested_values_are_canonical(self):
        value = {"z": [True, None, "quote\" slash/ newline\n"], "a": -3}
        self.assertEqual(
            canonicalize(value),
            b'{"a":-3,"z":[true,null,"quote\\" slash/ newline\\n"]}',
        )

    def test_nonfinite_unsafe_or_unsupported_values_rejected(self):
        for value in (float("nan"), float("inf"), -float("inf"), 2**53, object()):
            with self.subTest(value=value):
                with self.assertRaises(ArtifactValidationError):
                    canonicalize({"value": value})

    def test_unpaired_surrogate_rejected(self):
        with self.assertRaises(ArtifactValidationError):
            canonicalize({"bad": "\ud800"})


class ModelArtifactTests(unittest.TestCase):
    def test_create_verify_and_content_address(self):
        raw, artifact_id = create_artifact(exponential_payload())
        parsed = verify_artifact(raw)
        self.assertEqual(parsed["artifact_id"], artifact_id)
        self.assertTrue(artifact_id.startswith("sha256:"))
        self.assertEqual(len(artifact_id), 71)

    def test_key_insertion_order_does_not_change_artifact_identity(self):
        payload = exponential_payload()
        reversed_payload = dict(reversed(list(payload.items())))
        raw_a, id_a = create_artifact(payload)
        raw_b, id_b = create_artifact(reversed_payload)
        self.assertEqual(raw_a, raw_b)
        self.assertEqual(id_a, id_b)

    def test_semantic_change_changes_identity(self):
        payload = exponential_payload()
        raw_a, id_a = create_artifact(payload)
        changed = dict(payload)
        changed["theta"] = [0.1, -0.2, 0.3, 0.0, 0.06]
        changed["parameters"] = dict(changed["parameters"], theta=changed["theta"])
        raw_b, id_b = create_artifact(changed)
        self.assertNotEqual(id_a, id_b)
        self.assertNotEqual(raw_a, raw_b)

    def test_tampered_or_noncanonical_bytes_rejected(self):
        raw, _ = create_artifact(exponential_payload())
        payload = json.loads(raw)
        payload["theta"][0] = 0.9
        with self.assertRaises(ArtifactValidationError):
            verify_artifact(canonicalize(payload))
        with self.assertRaises(ArtifactValidationError):
            verify_artifact(b"{ " + raw + b" }")

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaises(ArtifactValidationError):
            parse_json_strict('{"schema_version":1,"schema_version":1}')

    def test_serialization_cannot_grant_forecast_readiness(self):
        payload = exponential_payload()
        payload["forecast_ready"] = True
        with self.assertRaises(ArtifactValidationError):
            create_artifact(payload)

    def test_wrong_zone_dimensions_and_feature_dimensions_rejected(self):
        payload = exponential_payload()
        payload["population_size"] = 12
        with self.assertRaises(ArtifactValidationError):
            create_artifact(payload)
        payload = exponential_payload()
        payload["theta"] = [0.1]
        with self.assertRaises(ArtifactValidationError):
            create_artifact(payload)

    def test_failed_fit_has_content_addressed_diagnostic_artifact(self):
        payload = exponential_payload()
        payload["artifact_type"] = "fit_failure"
        payload["fit"] = dict(
            payload["fit"], status="line_search_failed",
            termination_reason="strong-Wolfe search exhausted",
            objective=None, gradient_inf_norm=None,
        )
        payload["fit_diagnostics"] = {
            "terminal_status": "line_search_failed", "converged": False,
            "message": "strong-Wolfe search exhausted",
        }
        payload["parameters"] = {
            "parameter_order": "feature_schema.names", "parameters_available": False,
        }
        payload["normalization"] = {
            "method": "not_computed", "log_partition": None, "numeric_dtype": "float64",
        }
        payload["failure_reason"] = "line_search_failed"
        payload.pop("theta", None)
        raw, artifact_id = create_artifact(payload)
        verified = verify_artifact(raw)
        self.assertEqual(verified["artifact_id"], artifact_id)
        self.assertEqual(verified["artifact_type"], "fit_failure")
        self.assertFalse(verified["forecast_ready"])

    def test_conditional_poisson_family_requires_centered_weights(self):
        p = 2 / 12
        runtime = {}
        training = {
            "snapshot_sha256": "b" * 64, "row_count": 2948,
            "first_draw_id": "07001", "last_draw_id": "26130",
            "cutoff_draw_id": "26130", "cutoff_inclusive": True,
        }
        names = [f"item_{item}" for item in range(1, 13)]
        payload = {
            "schema_version": 1, "artifact_schema": "lottery.subset-probability-model/v1",
                    "artifact_type": "fitted_model",
            "model_family": "conditional_poisson", "zone": "back",
            "population_size": 12, "selection_size": 2,
            "support": {"population_size": 12, "selection_size": 2,
                        "support_count": 66, "subset_order": "lexicographic_ascending"},
            "feature_schema": {
                "version": "lottery-item-inclusion/v1", "names": names,
                "uniform_means": [p] * 12,
                "uniform_population_stds": [(p * (1 - p)) ** 0.5] * 12,
                "zero_variance_policy": "not_applicable_item_indicator_schema",
            },
            "parameters": {"centered_log_weights": [0.0] * 12,
                           "parameter_order": "feature_schema.names"},
            "normalization": {"method": "exact_conditional_poisson_log_space_dp",
                              "log_partition": 0.0, "numeric_dtype": "float64"},
            "fit": {"status": "converged", "termination_reason": "gradient_tolerance",
                    "objective": 0.0, "gradient_inf_norm": 0.0, "iterations": 1,
                    "optimizer": "conditional_poisson_calibration_lbfgs_v1", "lambda": None},
            "training": training,
            "implementation": {"code_revision": "abc123", "runtime": runtime,
                               "library_versions": {},
                               "rng_algorithm": "conditional_poisson_backward_dp_with_injected_rng_v1"},
            "training_snapshot_sha256": "b" * 64, "training_cutoff_draw_id": "26130",
            "training_row_count": 2948, "feature_schema_hash": "sha256:" + "c" * 64,
            "model_configuration_hash": "sha256:" + "d" * 64,
            "training_first_draw_id": "07001",
            "training_last_draw_id": "26130", "code_revision": "abc123",
            "runtime": runtime, "fit_diagnostics": {"terminal_status": "converged"},
            "forecast_ready": False, "centered_log_weights": [0.0] * 12,
            "target_marginals": [p] * 12, "achieved_marginals": [p] * 12,
            "solver_status": "converged", "calibration_residual": 0.0,
        }
        payload["feature_schema_hash"] = "sha256:" + hashlib.sha256(canonicalize(payload["feature_schema"])).hexdigest()
        model_configuration = {
            "model_family": "conditional_poisson", "zone": "back",
            "population_size": 12, "selection_size": 2, "alpha": 100.0,
            "half_life": None, "weighting": "expanding",
            "feature_schema_hash": payload["feature_schema_hash"],
        }
        payload["model_configuration"] = model_configuration
        payload["model_configuration_hash"] = "sha256:" + hashlib.sha256(canonicalize(model_configuration)).hexdigest()
        raw, artifact_id = create_artifact(payload)
        self.assertEqual(verify_artifact(raw)["artifact_id"], artifact_id)
        payload["centered_log_weights"] = [1.0] * 12
        with self.assertRaises(ArtifactValidationError):
            create_artifact(payload)


if __name__ == "__main__":
    unittest.main()
