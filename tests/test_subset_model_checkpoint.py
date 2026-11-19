import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_subset_rolling_origin import (
    _checkpoint_record_hash,
    _validate_checkpoint_record,
)


class CheckpointIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.row = {"draw_id": "09054"}
        self.uniform_nll = math.log(math.comb(35, 5))
        self.record = {
            "record_type": "target",
            "target_draw_id": "09054",
            "training_count": 300,
            "training_cutoff_draw_id": "09053",
            "fit_statuses": {
                "candidate": "converged",
                "expanding": "converged",
                "ewma": "converged",
            },
            "exact_set_nll": {
                "uniform": self.uniform_nll,
                "expanding": 8.0,
                "ewma": 8.1,
                "exponential_family": 7.9,
            },
            "candidate_iterations": 20,
            "candidate_gradient_infinity_norm": 1e-9,
        }
        self.record["record_sha256"] = _checkpoint_record_hash(self.record)

    def validate(self, record=None):
        _validate_checkpoint_record(
            record or self.record,
            row=self.row,
            training_count=300,
            uniform_nll=self.uniform_nll,
        )

    def test_valid_checkpoint_record_is_accepted(self):
        self.validate()

    def test_tampered_score_is_rejected_by_record_hash(self):
        changed = dict(self.record)
        changed["exact_set_nll"] = dict(changed["exact_set_nll"])
        changed["exact_set_nll"]["exponential_family"] = -100.0
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            self.validate(changed)

    def test_unknown_fields_are_rejected_even_with_recomputed_hash(self):
        changed = dict(self.record, injected=True)
        changed["record_sha256"] = _checkpoint_record_hash(changed)
        with self.assertRaisesRegex(ValueError, "invalid shape"):
            self.validate(changed)

    def test_uniform_score_must_match_legal_subset_support(self):
        changed = dict(self.record)
        changed["exact_set_nll"] = dict(changed["exact_set_nll"], uniform=1.0)
        changed["record_sha256"] = _checkpoint_record_hash(changed)
        with self.assertRaisesRegex(ValueError, "uniform NLL"):
            self.validate(changed)

    def test_failed_fit_cannot_carry_a_score(self):
        changed = dict(self.record)
        changed["fit_statuses"] = dict(changed["fit_statuses"], candidate="line_search_failed")
        changed["record_sha256"] = _checkpoint_record_hash(changed)
        with self.assertRaisesRegex(ValueError, "must be null"):
            self.validate(changed)

    def test_converged_fit_requires_a_finite_score(self):
        changed = dict(self.record)
        changed["exact_set_nll"] = dict(changed["exact_set_nll"], exponential_family=None)
        changed["record_sha256"] = _checkpoint_record_hash(changed)
        with self.assertRaisesRegex(ValueError, "invalid for converged fit"):
            self.validate(changed)


    def test_converged_fit_must_meet_gradient_tolerance(self):
        changed = dict(self.record, candidate_gradient_infinity_norm=1e-5)
        changed["record_sha256"] = _checkpoint_record_hash(changed)
        with self.assertRaisesRegex(ValueError, "exceeds the convergence tolerance"):
            self.validate(changed)

    def test_candidate_iteration_count_is_bounded_by_frozen_solver_budget(self):
        changed = dict(self.record, candidate_iterations=5001)
        changed["record_sha256"] = _checkpoint_record_hash(changed)
        with self.assertRaisesRegex(ValueError, "iteration count"):
            self.validate(changed)

    def test_negative_gradient_norm_is_rejected(self):
        changed = dict(self.record, candidate_gradient_infinity_norm=-1e-8)
        changed["record_sha256"] = _checkpoint_record_hash(changed)
        with self.assertRaisesRegex(ValueError, "gradient diagnostic"):
            self.validate(changed)

if __name__ == "__main__":
    unittest.main()
