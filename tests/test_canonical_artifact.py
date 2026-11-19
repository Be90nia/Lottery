"""Tests for canonical JCS serialization and immutable artifact identity."""
import unittest

from lottery.canonical_artifact import artifact_id, attach_artifact_id, canonicalize, verify_artifact


class CanonicalArtifactTests(unittest.TestCase):
    def test_object_order_does_not_affect_identity(self):
        first = {"z": 1, "a": {"b": 2, "a": 3}}
        second = {"a": {"a": 3, "b": 2}, "z": 1}
        self.assertEqual(canonicalize(first), canonicalize(second))
        self.assertEqual(artifact_id(first), artifact_id(second))

    def test_ecmascript_number_formatting_golden(self):
        value = {"numbers": [333333333.33333329, 1e30, 4.5, 2e-3, 1e-27]}
        self.assertEqual(canonicalize(value).decode("utf-8"),
                         '{"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27]}')

    def test_string_escaping_and_utf16_key_order(self):
        value = {"€": "€", "a": "line\\nfeed", "😀": "face"}
        self.assertEqual(canonicalize(value).decode("utf-8"),
                         '{"a":"line\\\\nfeed","€":"€","😀":"face"}')

    def test_artifact_id_excludes_its_own_field_and_detects_tampering(self):
        artifact = attach_artifact_id({"schema": "v1", "theta": [0.1, -0.2]})
        self.assertTrue(verify_artifact(artifact))
        artifact["theta"][0] = 0.3
        self.assertFalse(verify_artifact(artifact))

    def test_rejects_nonfinite_and_unsafe_numbers(self):
        for value in (float("nan"), float("inf"), 2 ** 53):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonicalize({"value": value})


if __name__ == "__main__":
    unittest.main()
