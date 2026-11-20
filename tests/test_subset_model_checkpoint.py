import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lottery.subset_model.artifact import create_artifact
from run_subset_rolling_origin import (
    _checkpoint_record_hash,
    _confirmatory_gate,
    _validate_checkpoint_record,
)


class ConfirmatoryGateTests(unittest.TestCase):
    def test_all_four_policy_and_result_gates_are_required(self):
        accepted = dict(
            experiment_registration_approved=True,
            solver_policy_approved=True,
            multiplicity_policy_approved=True,
            non_regression_policy_approved=True,
            non_regression_pass=True,
        )
        self.assertTrue(_confirmatory_gate(True, **accepted))
        for field in accepted:
            rejected = dict(accepted)
            rejected[field] = False
            with self.subTest(field=field):
                self.assertFalse(_confirmatory_gate(True, **rejected))
        self.assertFalse(_confirmatory_gate(False, **accepted))


class CheckpointIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.row = {
            "draw_id": "09054", "draw_date": "2020-01-01",
            "front_numbers": [1, 2, 3, 4, 5],
        }
        self.uniform_nll = math.log(math.comb(35, 5))
        common = {
            "schema_version": 1, "zone": "front", "population_size": 35,
            "selection_size": 5, "training_snapshot_sha256": "a" * 64,
            "training_first_draw_id": "07001", "training_last_draw_id": "09053",
            "training_cutoff_draw_id": "09053", "training_row_count": 300,
            "code_revision": "abc123", "runtime": {},
            "fit_diagnostics": {"terminal_status": "converged", "converged": True},
            "forecast_ready": False,
        }
        candidate = dict(
            common, model_family="complete_subset_exponential",
            active_feature_names=["sum", "odd_count", "range", "adjacent_count"],
            theta=[0.0, 0.0, 0.0, 0.0],
            objective_scale="mean_nll", regularization_lambda=1.0,
        )
        candidate_raw, candidate_id = create_artifact(candidate)
        conditional = dict(
            common, model_family="conditional_poisson",
            centered_log_weights=[0.0] * 35,
        )
        conditional_raw, conditional_id = create_artifact(conditional)
        self.artifacts = {
            "candidate": {"artifact_id": candidate_id, "payload": __import__("json").loads(candidate_raw)},
            "expanding": {"artifact_id": conditional_id, "payload": __import__("json").loads(conditional_raw)},
            "ewma": {"artifact_id": conditional_id, "payload": __import__("json").loads(conditional_raw)},
        }
        self.record = {
            "record_type": "target",
            "target_draw_id": "09054",
            "target_draw_date": "2020-01-01",
            "training_count": 300,
            "training_first_draw_id": "07001",
            "training_last_draw_id": "09053",
            "training_cutoff_draw_id": "09053",
            "training_cutoff_date": "2019-12-31",
            "training_dates_strictly_before_target": True,
            "observed_subset": [1, 2, 3, 4, 5],
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
            "model_artifacts": self.artifacts,
            "candidate_iterations": 20,
            "candidate_gradient_infinity_norm": 1e-9,
        }
        self.record["record_sha256"] = _checkpoint_record_hash(self.record)

    def validate(self, record=None):
        _validate_checkpoint_record(
            record or self.record,
            row=self.row,
            zone="front",
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
        changed["exact_set_nll"] = dict(changed["exact_set_nll"], exponential_family=None)
        changed["model_artifacts"] = dict(changed["model_artifacts"], candidate=None)
        changed["record_sha256"] = _checkpoint_record_hash(changed)
        self.validate(changed)

    def test_converged_fit_requires_a_finite_score(self):
        changed = dict(self.record)
        changed["exact_set_nll"] = dict(changed["exact_set_nll"], exponential_family=None)
        changed["record_sha256"] = _checkpoint_record_hash(changed)
        with self.assertRaisesRegex(ValueError, "invalid for converged fit"):
            self.validate(changed)

    def test_negative_gradient_norm_is_rejected(self):
        changed = dict(self.record, candidate_gradient_infinity_norm=-1e-8)
        changed["record_sha256"] = _checkpoint_record_hash(changed)
        with self.assertRaisesRegex(ValueError, "gradient diagnostic"):
            self.validate(changed)

    def test_corrupt_model_artifact_is_rejected(self):
        changed = dict(self.record)
        changed["model_artifacts"] = dict(changed["model_artifacts"])
        bad = dict(changed["model_artifacts"]["candidate"])
        bad["payload"] = dict(bad["payload"], theta=[0.0])
        changed["model_artifacts"]["candidate"] = bad
        changed["record_sha256"] = _checkpoint_record_hash(changed)
        with self.assertRaises(ValueError):
            self.validate(changed)


if __name__ == "__main__":
    unittest.main()
