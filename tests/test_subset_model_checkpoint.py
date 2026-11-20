import hashlib
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lottery.subset_model.artifact import canonicalize, create_artifact
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
        runtime = {}
        training = {
            "snapshot_sha256": "a" * 64, "row_count": 300,
            "first_draw_id": "07001", "last_draw_id": "09053",
            "cutoff_draw_id": "09053", "cutoff_inclusive": True,
        }
        common = {
            "schema_version": 1,
            "artifact_schema": "lottery.subset-probability-model/v1",
                    "artifact_type": "fitted_model",
            "zone": "front", "population_size": 35, "selection_size": 5,
            "support": {"population_size": 35, "selection_size": 5,
                        "support_count": 324632, "subset_order": "lexicographic_ascending"},
            "training_snapshot_sha256": "a" * 64,
            "feature_schema_hash": "sha256:" + "c" * 64,
            "model_configuration_hash": "sha256:" + "d" * 64,
            "training_first_draw_id": "07001", "training_last_draw_id": "09053",
            "training_cutoff_draw_id": "09053", "training_row_count": 300,
            "code_revision": "a" * 40, "runtime": runtime,
            "fit_diagnostics": {"terminal_status": "converged", "converged": True},
            "forecast_ready": False, "training": training,
            "implementation": {"code_revision": "a" * 40, "runtime": runtime,
                               "library_versions": {}, "rng_algorithm": "injected_rng.random_v1"},
            "normalization": {"method": "full_support_logsumexp",
                              "log_partition": 0.0, "numeric_dtype": "float64"},
            "fit": {"status": "converged", "termination_reason": "gradient_tolerance",
                    "objective": 0.0, "gradient_inf_norm": 0.0, "iterations": 20,
                    "optimizer": "L-BFGS-B", "lambda": 1.0},
        }
        names = ["sum", "odd_count", "range", "adjacent_count"]
        candidate = dict(
            common, model_family="complete_subset_exponential",
            feature_schema={
                "version": "lot-051-symmetric-v1", "names": names,
                "uniform_means": [0.0] * 4, "uniform_population_stds": [1.0] * 4,
                "zero_variance_policy": "drop_and_record",
                "candidate_names": names, "zero_variance_features": [],
            },
            parameters={"theta": [0.0, 0.0, 0.0, 0.0],
                        "parameter_order": "feature_schema.names"},
            active_feature_names=names, theta=[0.0, 0.0, 0.0, 0.0],
            objective_scale="mean_nll", regularization_lambda=1.0,
        )
        candidate["feature_schema_hash"] = "sha256:" + hashlib.sha256(canonicalize(candidate["feature_schema"])).hexdigest()
        candidate_config = {
            "model_family": "complete_subset_exponential", "zone": "front",
            "population_size": 35, "selection_size": 5,
            "feature_schema_hash": candidate["feature_schema_hash"],
            "objective_scale": "mean_nll", "regularization_lambda": 1.0,
            "solver": "L-BFGS-B", "max_iterations": 5000, "gradient_tolerance": 1e-8,
        }
        candidate["model_configuration"] = candidate_config
        candidate["model_configuration_hash"] = "sha256:" + hashlib.sha256(canonicalize(candidate_config)).hexdigest()
        candidate_raw, candidate_id = create_artifact(candidate)
        p = 5 / 35
        item_names = [f"item_{item}" for item in range(1, 36)]
        conditional = dict(
            common, model_family="conditional_poisson",
            feature_schema={
                "version": "lottery-item-inclusion/v1", "names": item_names,
                "uniform_means": [p] * 35,
                "uniform_population_stds": [(p * (1 - p)) ** 0.5] * 35,
                "zero_variance_policy": "not_applicable_item_indicator_schema",
            },
            parameters={"centered_log_weights": [0.0] * 35,
                        "parameter_order": "feature_schema.names"},
            fit=dict(common["fit"]),
            centered_log_weights=[0.0] * 35,
            target_marginals=[p] * 35, achieved_marginals=[p] * 35,
            solver_status="converged", calibration_residual=0.0,
        )
        conditional["fit"]["lambda"] = None
        conditional["fit"]["optimizer"] = "conditional_poisson_calibration_lbfgs_v1"
        conditional["implementation"] = {
            "code_revision": "a" * 40, "runtime": runtime, "library_versions": {},
            "rng_algorithm": "conditional_poisson_backward_dp_with_injected_rng_v1",
        }
        conditional["feature_schema_hash"] = "sha256:" + hashlib.sha256(canonicalize(conditional["feature_schema"])).hexdigest()
        conditional_config = {
            "model_family": "conditional_poisson", "zone": "front",
            "population_size": 35, "selection_size": 5,
            "feature_schema_hash": conditional["feature_schema_hash"],
        }
        conditional["model_configuration"] = conditional_config
        conditional["model_configuration_hash"] = "sha256:" + hashlib.sha256(canonicalize(conditional_config)).hexdigest()
        conditional["normalization"] = {
            "method": "exact_conditional_poisson_log_space_dp",
            "log_partition": 0.0, "numeric_dtype": "float64",
        }
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

    def test_failed_fit_cannot_carry_a_score_and_has_failure_artifact(self):
        import json
        changed = dict(self.record)
        changed["fit_statuses"] = dict(changed["fit_statuses"], candidate="line_search_failed")
        changed["exact_set_nll"] = dict(changed["exact_set_nll"], exponential_family=None)
        changed["model_artifacts"] = dict(changed["model_artifacts"])
        entry = changed["model_artifacts"]["candidate"]
        failure = dict(entry["payload"])
        failure["artifact_type"] = "fit_failure"
        failure["fit"] = dict(failure["fit"], status="line_search_failed",
                              termination_reason="line search failed",
                              objective=None, gradient_inf_norm=None)
        failure["fit_diagnostics"] = {
            "terminal_status": "line_search_failed", "converged": False,
            "message": "line search failed",
        }
        failure["parameters"] = {
            "parameter_order": "feature_schema.names", "parameters_available": False,
        }
        failure["normalization"] = {
            "method": "not_computed", "log_partition": None, "numeric_dtype": "float64",
        }
        failure["failure_reason"] = "line_search_failed"
        failure.pop("theta", None)
        raw, artifact_id = create_artifact(failure)
        changed["model_artifacts"]["candidate"] = {
            "artifact_id": artifact_id, "payload": json.loads(raw),
        }
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
