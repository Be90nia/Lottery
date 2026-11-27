import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from lottery.subset_model.conditional_poisson import calibration_configuration
from scripts.run_subset_rolling_origin import (
    _build_cp_calibration_registry_spec,
    _load_and_validate,
)


class ConditionalPoissonChildRegistrationTests(unittest.TestCase):
    def _write_registration_fixture(self, directory):
        source = ROOT / "docs/LOT055_CP_CALIBRATION_REGISTRATION_2026-11-27_G3-02.json"
        registration = json.loads(source.read_text(encoding="utf-8"))
        registration["solver_source_sha256"] = calibration_configuration()["source_sha256"]
        candidate = Path(directory) / source.name
        candidate.write_text(json.dumps(registration), encoding="utf-8")
        return candidate

    def test_post_outcome_child_registration_binds_exact_solver_and_snapshot(self):
        snapshot = ROOT / "data/processed/draws-20261118.jsonl"
        rows, digest = _load_and_validate(snapshot)
        with tempfile.TemporaryDirectory() as directory:
            registration = self._write_registration_fixture(directory)
            spec, trial = _build_cp_calibration_registry_spec(rows, digest, registration)

        effective = calibration_configuration()
        self.assertEqual(spec["experiment_name"], "LOT055-CP-CALIBRATION-DIAG-20261127-G3-02")
        self.assertEqual(spec["experiment_class"], "exploratory")
        self.assertIs(spec["outcomes_observed"], True)
        self.assertIs(spec["holdout_accessed"], False)
        self.assertEqual(len(spec["target_draw_ids"]), 2649)
        self.assertEqual(trial["registration_timing"], "post_outcome_exploratory")
        self.assertEqual(trial["baselines"]["calibration_solver"], effective)
        self.assertEqual(trial["baselines"]["calibration_solver"]["solver_id"],
                         "conditional_poisson_calibration_lbfgs_strong_wolfe_v2")
        self.assertEqual(trial["registration_id"], spec["experiment_name"])
        self.assertFalse(trial["candidate"].get("production_ready", False))

    def test_registration_rejects_mismatched_parent_or_governance_issue(self):
        snapshot = ROOT / "data/processed/draws-20261118.jsonl"
        rows, digest = _load_and_validate(snapshot)
        original = json.loads((ROOT / "docs/LOT055_CP_CALIBRATION_REGISTRATION_2026-11-26.json").read_text(encoding="utf-8"))
        original["solver_source_sha256"] = calibration_configuration()["source_sha256"]
        registration_name = "LOT055_CP_CALIBRATION_REGISTRATION_2026-11-26.json"
        for field, value in (
            ("parent_issue_url", "https://github.com/Be90nia/Lottery/issues/19"),
            ("governance_issue_url", "https://github.com/Be90nia/Lottery/issues/28"),
        ):
            changed = dict(original)
            changed[field] = value
            with tempfile.TemporaryDirectory() as directory:
                candidate = Path(directory) / registration_name
                candidate.write_text(json.dumps(changed), encoding="utf-8")
                with self.subTest(field=field):
                    with self.assertRaisesRegex(ValueError, "lineage is missing or mismatched"):
                        _build_cp_calibration_registry_spec(rows, digest, candidate)

    def test_registration_rejects_armijo_or_unregistered_solver_settings(self):
        snapshot = ROOT / "data/processed/draws-20261118.jsonl"
        rows, digest = _load_and_validate(snapshot)
        with tempfile.TemporaryDirectory() as directory:
            registration = self._write_registration_fixture(directory)
            original = registration.read_text(encoding="utf-8")
            changed = original.replace('"method": "strong_wolfe"', '"method": "armijo"')
            self.assertNotEqual(original, changed)
            candidate = Path(directory) / "armijo-registration.json"
            candidate.write_text(changed, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "registered solver settings"):
                _build_cp_calibration_registry_spec(rows, digest, candidate)

    def test_registration_rejects_missing_or_mismatched_solver_source_digest(self):
        snapshot = ROOT / "data/processed/draws-20261118.jsonl"
        rows, digest = _load_and_validate(snapshot)
        original = json.loads((ROOT / "docs/LOT055_CP_CALIBRATION_REGISTRATION_2026-11-26.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            for field_value, message in (
                (None, "missing or malformed"),
                ("0" * 64, "does not match the imported implementation"),
            ):
                changed = dict(original)
                if field_value is not None:
                    changed["solver_source_sha256"] = field_value
                candidate = Path(directory) / f"registration-{field_value}.json"
                candidate.write_text(json.dumps(changed), encoding="utf-8")
                with self.subTest(field_value=field_value):
                    with self.assertRaisesRegex(ValueError, message):
                        _build_cp_calibration_registry_spec(rows, digest, candidate)


if __name__ == "__main__":
    unittest.main()
