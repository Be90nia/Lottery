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
    return {
        "schema_version": 1,
        "model_family": "complete_subset_exponential",
        "zone": "front",
        "population_size": 35,
        "selection_size": 5,
        "training_snapshot_sha256": "a" * 64,
        "training_cutoff_draw_id": "26130",
        "training_row_count": 2948,
        "code_revision": "abc123",
        "runtime": {"python": "3.12"},
        "fit_diagnostics": {"terminal_status": "converged", "gradient_infinity_norm": 1e-9},
        "forecast_ready": False,
        "feature_schema_version": "lot-051-symmetric-v1",
        "active_feature_names": ["sum", "odd_count", "range", "adjacent_count", "gap_variance"],
        "theta": [0.1, -0.2, 0.3, 0.0, 0.05],
        "objective_scale": "mean_nll",
        "regularization_lambda": 1.0,
    }


class JCSCanonicalizationTests(unittest.TestCase):
    def test_shared_cross_language_golden_fixture(self):
        fixture_path = Path(__file__).parent / "fixtures" / "jcs-golden-v1.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        canonical = canonicalize(fixture["input"])
        expected = fixture["canonical_utf8"].encode("utf-8")
        self.assertEqual(canonical, expected)
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), fixture["sha256"])

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
    def test_unknown_top_level_schema_fields_are_rejected(self):
        payload = exponential_payload()
        payload["unregistered_debug_field"] = "must not be silently hashed"
        with self.assertRaisesRegex(ArtifactValidationError, "unknown artifact fields"):
            create_artifact(payload)

        conditional = {
            "schema_version": 1,
            "model_family": "conditional_poisson",
            "zone": "back",
            "population_size": 12,
            "selection_size": 2,
            "training_snapshot_sha256": "b" * 64,
            "training_cutoff_draw_id": "26130",
            "training_row_count": 2948,
            "code_revision": "abc123",
            "runtime": {},
            "fit_diagnostics": {"terminal_status": "converged"},
            "forecast_ready": False,
            "centered_log_weights": [0.0] * 12,
            "unregistered_debug_field": "must not be silently hashed",
        }
        with self.assertRaisesRegex(ArtifactValidationError, "unknown artifact fields"):
            create_artifact(conditional)

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

    def test_conditional_poisson_family_requires_centered_weights(self):
        payload = {
            "schema_version": 1,
            "model_family": "conditional_poisson",
            "zone": "back",
            "population_size": 12,
            "selection_size": 2,
            "training_snapshot_sha256": "b" * 64,
            "training_cutoff_draw_id": "26130",
            "training_row_count": 2948,
            "code_revision": "abc123",
            "runtime": {},
            "fit_diagnostics": {"terminal_status": "converged"},
            "forecast_ready": False,
            "centered_log_weights": [0.0] * 12,
        }
        raw, artifact_id = create_artifact(payload)
        self.assertEqual(verify_artifact(raw)["artifact_id"], artifact_id)
        payload["centered_log_weights"] = [1.0] * 12
        with self.assertRaises(ArtifactValidationError):
            create_artifact(payload)


if __name__ == "__main__":
    unittest.main()
