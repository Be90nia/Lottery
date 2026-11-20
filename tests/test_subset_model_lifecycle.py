import hashlib
import math
import tempfile
import unittest
from pathlib import Path

from lottery.subset_model.artifact import canonicalize
from lottery.subset_model.lifecycle import (
    APPROVAL_SCHEMA,
    EVALUATION_SCHEMA,
    ChampionLifecycle,
    LifecycleError,
    StaleRegistryError,
)


def model_payload(zone="front"):
    population, selection = (35, 5) if zone == "front" else (12, 2)
    names = ["sum", "odd_count", "range", "adjacent_count"]
    runtime = {"python": "3.12"}
    training = {
        "snapshot_sha256": "a" * 64,
        "row_count": 2948,
        "first_draw_id": "07001",
        "last_draw_id": "26130",
        "cutoff_draw_id": "26130",
        "cutoff_inclusive": True,
    }
    feature_schema = {
        "version": "lot-051-symmetric-v1",
        "names": names,
        "uniform_means": [0.0] * len(names),
        "uniform_population_stds": [1.0] * len(names),
        "zero_variance_policy": "drop_and_record",
        "candidate_names": names,
        "zero_variance_features": [],
    }
    feature_hash = "sha256:" + hashlib.sha256(canonicalize(feature_schema)).hexdigest()
    config = {
        "model_family": "complete_subset_exponential",
        "zone": zone,
        "population_size": population,
        "selection_size": selection,
        "feature_schema_hash": feature_hash,
        "objective_scale": "mean_nll",
        "regularization_lambda": 1.0,
        "solver": "L-BFGS-B",
        "max_iterations": 5000,
        "gradient_tolerance": 1e-8,
    }
    config_hash = "sha256:" + hashlib.sha256(canonicalize(config)).hexdigest()
    theta = [0.1, -0.2, 0.3, 0.0]
    return {
        "schema_version": 1,
        "artifact_schema": "lottery.subset-probability-model/v1",
        "artifact_type": "fitted_model",
        "model_family": "complete_subset_exponential",
        "zone": zone,
        "population_size": population,
        "selection_size": selection,
        "support": {
            "population_size": population,
            "selection_size": selection,
            "support_count": math.comb(population, selection),
            "subset_order": "lexicographic_ascending",
        },
        "feature_schema": feature_schema,
        "parameters": {"theta": theta, "parameter_order": "feature_schema.names"},
        "model_configuration": config,
        "normalization": {
            "method": "full_support_logsumexp",
            "log_partition": 12.0,
            "numeric_dtype": "float64",
        },
        "fit": {
            "status": "converged",
            "termination_reason": "gradient_tolerance",
            "objective": 1.0,
            "gradient_inf_norm": 1e-9,
            "iterations": 10,
            "optimizer": "L-BFGS-B",
            "lambda": 1.0,
        },
        "training": training,
        "implementation": {
            "code_revision": "a" * 40,
            "runtime": runtime,
            "library_versions": {},
            "rng_algorithm": "injected_rng.random_v1",
        },
        "training_snapshot_sha256": "a" * 64,
        "training_cutoff_draw_id": "26130",
        "training_row_count": 2948,
        "feature_schema_hash": feature_hash,
        "model_configuration_hash": config_hash,
        "training_first_draw_id": "07001",
        "training_last_draw_id": "26130",
        "code_revision": "a" * 40,
        "runtime": runtime,
        "fit_diagnostics": {
            "terminal_status": "converged",
            "gradient_infinity_norm": 1e-9,
        },
        "forecast_ready": False,
        "feature_schema_version": "lot-051-symmetric-v1",
        "active_feature_names": names,
        "theta": theta,
        "objective_scale": "mean_nll",
        "regularization_lambda": 1.0,
    }


def evaluation_receipt(artifact_id, population_key, zone, *, passed=True):
    return {
        "schema_version": EVALUATION_SCHEMA,
        "artifact_id": artifact_id,
        "population_key": population_key,
        "zone": zone,
        "evaluation_manifest_sha256": "b" * 64,
        "target_list_sha256": "c" * 64,
        "target_count": 100,
        "population_eligibility": "pooled_equipment_blind",
        "population_evidence_sha256": None,
        "full_coverage": passed,
        "preregistered": True,
        "holdout_accessed": False,
        "numerical_pass": True,
        "calibration_pass": True,
        "stability_pass": True,
        "front_improved": True,
        "back_improved": True,
        "multiplicity_pass": True,
        "uniform_non_regression_pass": True,
        "decision": "PASS" if passed else "FAIL",
        "reason_code": "" if passed else "incomplete_coverage",
    }


def approval_for(artifact_id, population_key, zone, receipt, *, action="promote",
                 expected_champion_artifact_id=None):
    receipt_hash = hashlib.sha256(canonicalize(receipt)).hexdigest()
    return {
        "schema_version": APPROVAL_SCHEMA,
        "approval_id": "approval-fixture",
        "action": action,
        "artifact_id": artifact_id,
        "population_key": population_key,
        "zone": zone,
        "expected_champion_artifact_id": expected_champion_artifact_id,
        "evaluation_manifest_sha256": receipt["evaluation_manifest_sha256"],
        "evaluation_receipt_sha256": receipt_hash,
        "policy_version": "LOT-060-v1",
        "issued_at_utc": "2026-11-20T10:00:00+00:00",
        "signer_id": "fixture-signer",
        "signature": "fixture-signature-not-for-production",
    }


class ChampionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ChampionLifecycle(Path(self.temp.name) / "lifecycle")
        self.verifier = lambda approval, expected: True

    def tearDown(self):
        self.temp.cleanup()

    def register_and_validate(self, population_key="regime-a|reported-1", zone="front", passed=True):
        artifact_payload = model_payload(zone)
        from lottery.subset_model.artifact import create_artifact
        _, artifact_id = create_artifact(artifact_payload)
        current = self.store.snapshot()
        registered = self.store.register_challenger(
            artifact_payload,
            population_key=population_key,
            zone=zone,
            expected_generation=current["generation"],
            actor="test-suite",
            workflow_run_id="run-fixture",
        )
        receipt = evaluation_receipt(artifact_id, population_key, zone, passed=passed)
        validated = self.store.validate_candidate(
            population_key=population_key,
            zone=zone,
            artifact_id=artifact_id,
            receipt=receipt,
            expected_generation=registered["generation"],
            actor="test-suite",
        )
        return artifact_id, receipt, validated

    def test_promotes_only_after_full_gates_and_protected_approval(self):
        population = "regime-a|reported-1"
        artifact_id, receipt, validated = self.register_and_validate(population)
        approval = approval_for(artifact_id, population, "front", receipt)
        with self.assertRaisesRegex(LifecycleError, "verifier is absent"):
            self.store.promote_candidate(
                population_key=population,
                zone="front",
                artifact_id=artifact_id,
                expected_champion_artifact_id=None,
                expected_generation=validated["generation"],
                approval=approval,
                approval_verifier=None,
                actor="test-suite",
            )
        promoted = self.store.promote_candidate(
            population_key=population,
            zone="front",
            artifact_id=artifact_id,
            expected_champion_artifact_id=None,
            expected_generation=validated["generation"],
            approval=approval,
            approval_verifier=self.verifier,
            actor="test-suite",
        )
        slot = promoted["slots"][f"{population}|front"]
        self.assertEqual(slot["champion_artifact_id"], artifact_id)
        self.assertIsNone(slot["challenger_artifact_id"])
        self.assertFalse(slot["suspended"])
        self.assertTrue(self.store.events_path.exists())

    def test_incomplete_or_unregistered_evaluation_cannot_promote(self):
        population = "regime-a|reported-1"
        artifact_id, receipt, validated = self.register_and_validate(population, passed=False)
        approval = approval_for(artifact_id, population, "front", receipt)
        with self.assertRaisesRegex(LifecycleError, "has not passed"):
            self.store.promote_candidate(
                population_key=population,
                zone="front",
                artifact_id=artifact_id,
                expected_champion_artifact_id=None,
                expected_generation=validated["generation"],
                approval=approval,
                approval_verifier=self.verifier,
                actor="test-suite",
            )

    def test_stale_compare_and_swap_cannot_overwrite_registry(self):
        population = "regime-a|reported-1"
        artifact_id, _, registered = self.register_and_validate(population)
        with self.assertRaises(StaleRegistryError):
            self.store.reject_challenger(
                population_key=population,
                zone="front",
                artifact_id=artifact_id,
                expected_generation=registered["generation"] - 1,
                actor="stale-worker",
                reason_code="stale_test",
            )
        self.assertEqual(
            self.store.snapshot()["slots"][f"{population}|front"]["challenger_artifact_id"],
            artifact_id,
        )

    def test_reject_and_suspend_preserve_champion_and_append_events(self):
        population = "regime-a|reported-1"
        artifact_id, receipt, validated = self.register_and_validate(population)
        approval = approval_for(artifact_id, population, "front", receipt)
        promoted = self.store.promote_candidate(
            population_key=population, zone="front", artifact_id=artifact_id,
            expected_champion_artifact_id=None, expected_generation=validated["generation"],
            approval=approval, approval_verifier=self.verifier, actor="test-suite",
        )
        suspended = self.store.suspend_slot(
            population_key=population, zone="front",
            expected_generation=promoted["generation"], actor="test-suite",
            reason_code="source_evidence_revoked",
        )
        slot = suspended["slots"][f"{population}|front"]
        self.assertEqual(slot["champion_artifact_id"], artifact_id)
        self.assertTrue(slot["suspended"])
        events = self.store._read_events()
        self.assertEqual([event["event_type"] for event in events],
                         ["challenger_registered", "candidate_validated", "promoted", "slot_suspended"])

    def test_three_slot_resolution_is_all_or_none_and_reverifies_approval(self):
        with self.assertRaisesRegex(LifecycleError, "exactly three distinct"):
            self.store.resolve_three_slot_generation(["only-one"], approval_verifier=self.verifier)
        with self.assertRaisesRegex(LifecycleError, "protected approval verifier"):
            self.store.resolve_three_slot_generation(
                ["set-a", "set-b", "set-c"], approval_verifier=None
            )


if __name__ == "__main__":
    unittest.main()
