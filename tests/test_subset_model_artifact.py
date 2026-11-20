import hashlib
import math
import json
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.subset_model.artifact import (
    ArtifactValidationError,
    canonicalize,
    create_artifact,
    create_derived_cache,
    parse_json_strict,
    verify_artifact,
    verify_derived_cache,
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
        "implementation": {"code_revision": "a" * 40, "runtime": runtime,
                           "library_versions": {}, "rng_algorithm": "injected_rng.random_v1"},
        "training_snapshot_sha256": "a" * 64,
        "training_cutoff_draw_id": "26130", "training_row_count": 2948,
        "feature_schema_hash": feature_schema_hash,
        "model_configuration_hash": model_configuration_hash,
        "model_configuration": model_configuration,
        "training_first_draw_id": "07001", "training_last_draw_id": "26130",
        "code_revision": "a" * 40, "runtime": runtime,
        "fit_diagnostics": {"terminal_status": "converged", "gradient_infinity_norm": 1e-9},
        "forecast_ready": False,
        "feature_schema_version": "lot-051-symmetric-v1",
        "active_feature_names": names, "theta": theta,
        "objective_scale": "mean_nll", "regularization_lambda": 1.0,
    }




def conditional_poisson_payload():
    population, selection = 35, 5
    names = [f"item_{item}" for item in range(1, population + 1)]
    mean = selection / population
    std = (mean * (1.0 - mean)) ** 0.5
    feature_schema = {
        "version": "lottery-item-inclusion/v1",
        "names": names,
        "uniform_means": [mean] * population,
        "uniform_population_stds": [std] * population,
        "zero_variance_policy": "not_applicable_item_indicator_schema",
    }
    feature_schema_hash = "sha256:" + hashlib.sha256(canonicalize(feature_schema)).hexdigest()
    model_configuration = {
        "model_family": "conditional_poisson",
        "zone": "front",
        "population_size": population,
        "selection_size": selection,
        "feature_schema_hash": feature_schema_hash,
        "baseline": "expanding",
        "alpha": 100.0,
        "half_life": None,
        "weighting": "expanding",
        "optimizer": "conditional_poisson_calibration_lbfgs_strong_wolfe_v2",
        "gradient_tolerance": 1e-8,
        "max_iterations": 5000,
        "history_size": 10,
    }
    config_hash = "sha256:" + hashlib.sha256(canonicalize(model_configuration)).hexdigest()
    log_partition = math.log(math.comb(population, selection))
    runtime = {"python": "3.12", "implementation": "CPython"}
    training = {
        "snapshot_sha256": "a" * 64, "row_count": 2948,
        "first_draw_id": "07001", "last_draw_id": "26130",
        "cutoff_draw_id": "26130", "cutoff_inclusive": True,
    }
    marginals = [mean] * population
    weights = [0.0] * population
    return {
        "schema_version": 1,
        "artifact_schema": "lottery.subset-probability-model/v1",
        "artifact_type": "fitted_model",
        "model_family": "conditional_poisson",
        "zone": "front",
        "population_size": population,
        "selection_size": selection,
        "training_snapshot_sha256": "a" * 64,
        "training_first_draw_id": "07001",
        "training_last_draw_id": "26130",
        "training_cutoff_draw_id": "26130",
        "training_row_count": 2948,
        "code_revision": "a" * 40,
        "runtime": runtime,
        "fit_diagnostics": {
            "terminal_status": "converged", "converged": True,
            "message": "marginal residual reached tolerance", "iterations": 0,
            "gradient_infinity_norm": 0.0, "calibration_residual": 0.0,
            "objective": log_partition,
        },
        "forecast_ready": False,
        "support": {
            "population_size": population, "selection_size": selection,
            "support_count": math.comb(population, selection),
            "subset_order": "lexicographic_ascending",
        },
        "feature_schema": feature_schema,
        "parameters": {"centered_log_weights": weights, "parameter_order": "feature_schema.names"},
        "model_configuration": model_configuration,
        "fit": {
            "status": "converged", "termination_reason": "marginal residual reached tolerance",
            "objective": log_partition, "gradient_inf_norm": 0.0, "iterations": 0,
            "optimizer": "conditional_poisson_calibration_lbfgs_strong_wolfe_v2", "lambda": None,
        },
        "training": training,
        "implementation": {
            "code_revision": "a" * 40, "runtime": runtime,
            "library_versions": {},
            "rng_algorithm": "conditional_poisson_backward_dp_with_injected_rng_v1",
        },
        "baseline": "expanding", "alpha": 100.0, "half_life": None,
        "target_marginals": marginals, "achieved_marginals": marginals,
        "centered_log_weights": weights, "solver_status": "converged",
        "calibration_residual": 0.0,
        "feature_schema_hash": feature_schema_hash,
        "model_configuration_hash": config_hash,
        "normalization": {
            "method": "exact_conditional_poisson_log_space_dp",
            "log_partition": log_partition, "numeric_dtype": "float64",
        },
    }


class JCSCanonicalizationTests(unittest.TestCase):
    def test_shared_cross_language_golden_fixture(self):
        fixture_path = Path(__file__).parent / "fixtures" / "jcs-golden-v1.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        canonical = canonicalize(fixture["input"])
        expected = fixture["canonical_utf8"].encode("utf-8")
        self.assertEqual(canonical, expected)
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), fixture["sha256"])

    def test_rfc8785_appendix_b_binary64_number_vectors(self):
        fixture_path = Path(__file__).parent / "fixtures" / "jcs-golden-v1.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        for vector in fixture["binary64_vectors"]:
            value = struct.unpack(">d", bytes.fromhex(vector["hex"]))[0]
            with self.subTest(hex=vector["hex"]):
                self.assertEqual(canonicalize(value).decode("ascii"), vector["expected"])
        for hex_value in fixture["invalid_binary64_vectors"]:
            value = struct.unpack(">d", bytes.fromhex(hex_value))[0]
            with self.subTest(invalid_hex=hex_value):
                with self.assertRaises(ArtifactValidationError):
                    canonicalize(value)

    def test_exactly_representable_large_integers_follow_binary64_serialization(self):
        self.assertEqual(
            canonicalize({"value": 2**68}),
            b'{"value":295147905179352830000}',
        )
        with self.assertRaises(ArtifactValidationError):
            canonicalize({"value": 2**53 + 1})

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
        for value in (float("nan"), float("inf"), -float("inf"), 2**53 + 1, object()):
            with self.subTest(value=value):
                with self.assertRaises(ArtifactValidationError):
                    canonicalize({"value": value})

    def test_unpaired_surrogate_rejected(self):
        with self.assertRaises(ArtifactValidationError):
            canonicalize({"bad": "\ud800"})


class ModelArtifactTests(unittest.TestCase):
    def test_unknown_top_level_schema_fields_are_rejected(self):
        payload = exponential_payload()
        payload["unregistered_debug_field"] = "must not be silently hashed"
        with self.assertRaisesRegex(ArtifactValidationError, "unknown artifact fields"):
            create_artifact(payload)

    def test_conditional_poisson_artifact_binds_registered_strong_wolfe_configuration(self):
        raw, artifact_id = create_artifact(conditional_poisson_payload())
        parsed = verify_artifact(raw)
        self.assertEqual(parsed["artifact_id"], artifact_id)
        self.assertEqual(
            parsed["model_configuration"]["optimizer"],
            "conditional_poisson_calibration_lbfgs_strong_wolfe_v2",
        )
        self.assertEqual(parsed["model_configuration"]["gradient_tolerance"], 1e-8)

    def test_conditional_poisson_artifact_rejects_unregistered_solver(self):
        payload = conditional_poisson_payload()
        payload["model_configuration"]["optimizer"] = "unregistered_optimizer"
        payload["model_configuration_hash"] = "sha256:" + hashlib.sha256(
            canonicalize(payload["model_configuration"])
        ).hexdigest()
        with self.assertRaisesRegex(ArtifactValidationError, "solver configuration is not registered"):
            create_artifact(payload)

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

    def test_model_artifact_rejects_non_numeric_parameters_and_cutoff_mismatch(self):
        payload = exponential_payload()
        payload["theta"][0] = "0.1"
        payload["parameters"]["theta"][0] = "0.1"
        with self.assertRaisesRegex(ArtifactValidationError, "theta/schema"):
            create_artifact(payload)

        payload = exponential_payload()
        payload["training"]["last_draw_id"] = "26129"
        with self.assertRaisesRegex(ArtifactValidationError, "training provenance"):
            create_artifact(payload)

        payload = exponential_payload()
        payload["code_revision"] = "abc123"
        payload["implementation"]["code_revision"] = "abc123"
        with self.assertRaisesRegex(ArtifactValidationError, "full lowercase 40-character"):
            create_artifact(payload)

    def test_nested_closed_schema_rejects_unknown_support_and_feature_fields(self):
        payload = exponential_payload()
        payload["support"]["surprise"] = 1
        with self.assertRaisesRegex(ArtifactValidationError, "support descriptor"):
            create_artifact(payload)

        payload = exponential_payload()
        payload["feature_schema"]["surprise"] = 1
        with self.assertRaisesRegex(ArtifactValidationError, "feature_schema"):
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

    def test_derived_cache_is_content_addressed_and_bound_to_parent(self):
        _, parent_id = create_artifact(exponential_payload())
        cache_payload = {
            "schema_version": 1,
            "artifact_schema": "lottery.derived-cache/v1",
            "cache_type": "log-partition-fixture",
            "parent_artifact_id": parent_id,
            "cache_payload": {"support_count": 324632, "log_partition": 12.0},
            "code_revision": "b" * 40,
            "runtime": {"python": "3.12"},
        }
        raw, cache_id = create_derived_cache(cache_payload)
        verified = verify_derived_cache(raw, expected_parent_artifact_id=parent_id)
        self.assertEqual(verified["artifact_id"], cache_id)
        self.assertEqual(verified["parent_artifact_id"], parent_id)

        other_payload = exponential_payload()
        other_payload["theta"] = [0.2, -0.2, 0.3, 0.0, 0.05]
        other_payload["parameters"] = dict(other_payload["parameters"], theta=other_payload["theta"])
        _, other_parent_id = create_artifact(other_payload)
        with self.assertRaisesRegex(ArtifactValidationError, "parent artifact ID mismatch"):
            verify_derived_cache(raw, expected_parent_artifact_id=other_parent_id)

    def test_derived_cache_rejects_unknown_fields_and_tampering(self):
        _, parent_id = create_artifact(exponential_payload())
        cache_payload = {
            "schema_version": 1,
            "artifact_schema": "lottery.derived-cache/v1",
            "cache_type": "test",
            "parent_artifact_id": parent_id,
            "cache_payload": {"value": 1},
            "code_revision": "b" * 40,
            "runtime": {},
            "mutable_latest": True,
        }
        with self.assertRaisesRegex(ArtifactValidationError, "registered schema"):
            create_derived_cache(cache_payload)

        cache_payload.pop("mutable_latest")
        raw, _ = create_derived_cache(cache_payload)
        altered = json.loads(raw)
        altered["cache_payload"]["value"] = 2
        with self.assertRaises(ArtifactValidationError):
            verify_derived_cache(canonicalize(altered), expected_parent_artifact_id=parent_id)

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
            "implementation": {"code_revision": "a" * 40, "runtime": runtime,
                               "library_versions": {},
                               "rng_algorithm": "conditional_poisson_backward_dp_with_injected_rng_v1"},
            "training_snapshot_sha256": "b" * 64, "training_cutoff_draw_id": "26130",
            "training_row_count": 2948, "feature_schema_hash": "sha256:" + "c" * 64,
            "model_configuration_hash": "sha256:" + "d" * 64,
            "training_first_draw_id": "07001",
            "training_last_draw_id": "26130", "code_revision": "a" * 40,
            "runtime": runtime, "fit_diagnostics": {"terminal_status": "converged"},
            "forecast_ready": False, "centered_log_weights": [0.0] * 12,
            "baseline": "expanding", "alpha": 100.0, "half_life": None,
            "target_marginals": [p] * 12, "achieved_marginals": [p] * 12,
            "solver_status": "converged", "calibration_residual": 0.0,
        }
        payload["feature_schema_hash"] = "sha256:" + hashlib.sha256(canonicalize(payload["feature_schema"])).hexdigest()
        model_configuration = {
            "model_family": "conditional_poisson", "baseline": "expanding", "zone": "back",
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
        payload["centered_log_weights"] = ["0.0"] * 12
        payload["parameters"]["centered_log_weights"] = ["0.0"] * 12
        with self.assertRaisesRegex(ArtifactValidationError, "finite numeric"):
            create_artifact(payload)


if __name__ == "__main__":
    unittest.main()
