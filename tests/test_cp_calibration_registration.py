import sys
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
    def test_post_outcome_child_registration_binds_exact_solver_and_snapshot(self):
        snapshot = ROOT / "data/processed/draws-20261118.jsonl"
        registration = ROOT / "docs/LOT055_CP_CALIBRATION_REGISTRATION_2026-11-26.json"
        rows, digest = _load_and_validate(snapshot)
        spec, trial = _build_cp_calibration_registry_spec(rows, digest, registration)

        effective = calibration_configuration()
        self.assertEqual(spec["experiment_name"], "LOT055-CP-CALIBRATION-DIAG-20261126")
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

    def test_registration_rejects_armijo_or_unregistered_solver_settings(self):
        snapshot = ROOT / "data/processed/draws-20261118.jsonl"
        registration = ROOT / "docs/LOT055_CP_CALIBRATION_REGISTRATION_2026-11-26.json"
        rows, digest = _load_and_validate(snapshot)
        original = registration.read_text(encoding="utf-8")
        changed = original.replace('"method": "strong_wolfe"', '"method": "armijo"')
        self.assertNotEqual(original, changed)
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / registration.name
            candidate.write_text(changed, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "registered solver settings"):
                _build_cp_calibration_registry_spec(rows, digest, candidate)


if __name__ == "__main__":
    unittest.main()
