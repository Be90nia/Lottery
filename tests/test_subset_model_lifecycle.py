import hashlib
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lottery.subset_model.artifact import canonicalize
from lottery.subset_model.lifecycle import (
    APPROVAL_SCHEMA,
    EVALUATION_SCHEMA,
    SHADOW_SCHEMA,
    ChampionLifecycle,
    LifecycleError,
    StaleRegistryError,
    _write_once,
)


def model_payload(zone="front", snapshot_hash="a" * 64):
    population, selection = (35, 5) if zone == "front" else (12, 2)
    names = ["sum", "odd_count", "range", "adjacent_count"]
    runtime = {"python": "3.12"}
    training = {
        "snapshot_sha256": snapshot_hash,
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
        "training_snapshot_sha256": snapshot_hash,
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


def evaluation_receipt(artifact_id, population_key, zone, *, passed=True,
                       snapshot_hash="a" * 64, population_eligibility="pooled_equipment_blind",
                       population_evidence_sha256=None):
    return {
        "schema_version": EVALUATION_SCHEMA,
        "artifact_id": artifact_id,
        "population_key": population_key,
        "zone": zone,
        "evaluation_manifest_sha256": "b" * 64,
        "target_list_sha256": "c" * 64,
        "target_count": 100,
        "training_population_sha256": snapshot_hash,
        "population_eligibility": population_eligibility,
        "population_evidence_sha256": population_evidence_sha256,
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


def shadow_receipt(artifact_id, population_key, zone, champion_artifact_id, *,
                   first_target_draw_id="26131", last_target_draw_id="26140",
                   full_coverage=True):
    return {
        "schema_version": SHADOW_SCHEMA,
        "shadow_manifest_sha256": "d" * 64,
        "artifact_id": artifact_id,
        "population_key": population_key,
        "zone": zone,
        "champion_artifact_id": champion_artifact_id,
        "target_list_sha256": "e" * 64,
        "source_evidence_sha256": "f" * 64,
        "first_target_draw_id": first_target_draw_id,
        "last_target_draw_id": last_target_draw_id,
        "target_count": 10,
        "full_coverage": full_coverage,
        "targets_after_training_cutoff": True,
        "holdout_accessed": False,
        "champion_non_regression_pass": True,
        "uniform_non_regression_pass": True,
        "calibration_pass": True,
        "probability_integrity_pass": True,
        "stability_pass": True,
        "decision": "PASS" if full_coverage else "FAIL",
        "reason_code": "" if full_coverage else "incomplete_shadow_coverage",
    }


def approval_for(artifact_id, population_key, zone, receipt, *, action="promote",
                 expected_champion_artifact_id=None, shadow_receipt_sha256=None):
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
        "shadow_receipt_sha256": shadow_receipt_sha256,
        "policy_version": "LOT-060-v1",
        "issued_at_utc": "2026-11-20T10:00:00+00:00",
        "signer_id": "fixture-signer",
        "signature": "fixture-signature-not-for-production",
    }


class AtomicImmutableObjectTests(unittest.TestCase):
    def test_publication_failure_never_exposes_a_partial_object(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "objects" / "model.json"
            with patch(
                "lottery.subset_model.lifecycle.os.link",
                side_effect=OSError("simulated atomic publication failure"),
            ):
                with self.assertRaisesRegex(OSError, "simulated atomic publication failure"):
                    _write_once(target, b'{"complete":true}')
            self.assertFalse(target.exists())
            self.assertEqual(list(target.parent.iterdir()), [])

    def test_write_once_is_idempotent_but_rejects_content_collision(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "objects" / "model.json"
            _write_once(target, b"immutable")
            _write_once(target, b"immutable")
            self.assertEqual(target.read_bytes(), b"immutable")
            with self.assertRaisesRegex(LifecycleError, "immutable object collision"):
                _write_once(target, b"different")
            self.assertEqual(target.read_bytes(), b"immutable")


class ChampionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ChampionLifecycle(Path(self.temp.name) / "lifecycle")
        self.verifier = lambda approval, expected: True

    def tearDown(self):
        self.temp.cleanup()

    def register_and_validate(self, population_key="regime-a|reported-1", zone="front", passed=True,
                              snapshot_hash="a" * 64, population_eligibility="pooled_equipment_blind",
                              population_evidence_sha256=None):
        artifact_payload = model_payload(zone, snapshot_hash)
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
        receipt = evaluation_receipt(
            artifact_id, population_key, zone, passed=passed, snapshot_hash=snapshot_hash,
            population_eligibility=population_eligibility,
            population_evidence_sha256=population_evidence_sha256,
        )
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


    def test_replacement_requires_complete_prospective_shadow_receipt(self):
        population = "pooled_equipment_blind"
        first_id, first_receipt, first_validation = self.register_and_validate(
            population, snapshot_hash="a" * 64
        )
        first_approval = approval_for(first_id, population, "front", first_receipt)
        first_promoted = self.store.promote_candidate(
            population_key=population, zone="front", artifact_id=first_id,
            expected_champion_artifact_id=None,
            expected_generation=first_validation["generation"],
            approval=first_approval, approval_verifier=self.verifier, actor="test-suite",
        )

        second_id, second_receipt, second_validation = self.register_and_validate(
            population, snapshot_hash="d" * 64
        )
        failed_shadow = shadow_receipt(
            second_id, population, "front", first_id, full_coverage=False
        )
        failed = self.store.mark_shadow(
            population_key=population, zone="front", artifact_id=second_id,
            shadow_receipt=failed_shadow,
            expected_generation=second_validation["generation"], actor="test-suite",
        )
        slot = failed["slots"][f"{population}|front"]
        self.assertEqual(slot["challenger_artifact_id"], second_id)
        self.assertIsNone(slot["shadow_artifact_id"])
        with self.assertRaisesRegex(LifecycleError, "prospective shadow receipt"):
            self.store.promote_candidate(
                population_key=population, zone="front", artifact_id=second_id,
                expected_champion_artifact_id=first_id,
                expected_generation=failed["generation"],
                approval=approval_for(
                    second_id, population, "front", second_receipt,
                    expected_champion_artifact_id=first_id,
                ),
                approval_verifier=self.verifier, actor="test-suite",
            )

        passing_shadow = shadow_receipt(second_id, population, "front", first_id)
        shadowed = self.store.mark_shadow(
            population_key=population, zone="front", artifact_id=second_id,
            shadow_receipt=passing_shadow,
            expected_generation=failed["generation"], actor="test-suite",
        )
        shadow_hash = hashlib.sha256(canonicalize(passing_shadow)).hexdigest()
        approval = approval_for(
            second_id, population, "front", second_receipt,
            expected_champion_artifact_id=first_id,
            shadow_receipt_sha256=shadow_hash,
        )
        promoted = self.store.promote_candidate(
            population_key=population, zone="front", artifact_id=second_id,
            expected_champion_artifact_id=first_id,
            expected_generation=shadowed["generation"],
            approval=approval, approval_verifier=self.verifier, actor="test-suite",
        )
        self.assertEqual(
            promoted["slots"][f"{population}|front"]["champion_artifact_id"],
            second_id,
        )

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



    def test_compatible_retired_champion_can_be_restored_with_new_approval(self):
        population = "regime-a|reported-1"
        first_id, first_receipt, first_validation = self.register_and_validate(
            population, snapshot_hash="a" * 64
        )
        first_approval = approval_for(first_id, population, "front", first_receipt)
        first_promoted = self.store.promote_candidate(
            population_key=population, zone="front", artifact_id=first_id,
            expected_champion_artifact_id=None,
            expected_generation=first_validation["generation"],
            approval=first_approval, approval_verifier=self.verifier, actor="test-suite",
        )

        second_id, second_receipt, second_validation = self.register_and_validate(
            population, snapshot_hash="d" * 64
        )
        prospective_shadow = shadow_receipt(second_id, population, "front", first_id)
        shadowed = self.store.mark_shadow(
            population_key=population, zone="front", artifact_id=second_id,
            shadow_receipt=prospective_shadow,
            expected_generation=second_validation["generation"], actor="test-suite",
        )
        shadow_hash = hashlib.sha256(canonicalize(prospective_shadow)).hexdigest()
        second_approval = approval_for(
            second_id, population, "front", second_receipt,
            expected_champion_artifact_id=first_id,
            shadow_receipt_sha256=shadow_hash,
        )
        second_promoted = self.store.promote_candidate(
            population_key=population, zone="front", artifact_id=second_id,
            expected_champion_artifact_id=first_id,
            expected_generation=shadowed["generation"],
            approval=second_approval, approval_verifier=self.verifier, actor="test-suite",
        )
        restore_approval = approval_for(
            first_id, population, "front", first_receipt,
            action="restore", expected_champion_artifact_id=second_id,
        )
        restored = self.store.restore_retired(
            population_key=population, zone="front", artifact_id=first_id,
            expected_champion_artifact_id=second_id,
            expected_generation=second_promoted["generation"],
            approval=restore_approval, approval_verifier=self.verifier,
            actor="test-suite",
        )
        self.assertEqual(
            restored["slots"][f"{population}|front"]["champion_artifact_id"],
            first_id,
        )

    def test_write_ahead_journal_recovers_registry_commit_without_event(self):
        root = Path(self.temp.name) / "crash-recovery"
        store = ChampionLifecycle(root)
        artifact_payload = model_payload("front")
        from lottery.subset_model.artifact import create_artifact
        _, artifact_id = create_artifact(artifact_payload)
        store._append_event_locked = lambda body: (_ for _ in ()).throw(RuntimeError("simulated crash"))
        with self.assertRaisesRegex(RuntimeError, "simulated crash"):
            store.register_challenger(
                artifact_payload,
                population_key="pooled_equipment_blind",
                zone="front",
                expected_generation=0,
                actor="crash-test",
            )
        recovered = ChampionLifecycle(root)
        slot = recovered.snapshot()["slots"]["pooled_equipment_blind|front"]
        self.assertEqual(slot["challenger_artifact_id"], artifact_id)
        self.assertEqual(recovered._read_events()[0]["event_type"], "challenger_registered")
        self.assertEqual(list(recovered.journals.glob("*.json")), [])

    def test_three_slot_generation_requires_three_verified_distinct_populations(self):
        population_keys = [
            "regime-2020|reported_set_index=1",
            "regime-2020|reported_set_index=2",
            "regime-2020|reported_set_index=3",
        ]
        generation = self.store.snapshot()["generation"]
        evidence_hash = hashlib.sha256(b"shared-regime-evidence-manifest").hexdigest()
        first_transitions = []
        first_artifacts = {}
        first_receipts = {}
        for population_key in population_keys:
            training_hash = hashlib.sha256(population_key.encode("utf-8")).hexdigest()
            for zone in ("front", "back"):
                artifact_payload = model_payload(zone, training_hash)
                from lottery.subset_model.artifact import create_artifact
                _, artifact_id = create_artifact(artifact_payload)
                registered = self.store.register_challenger(
                    artifact_payload, population_key=population_key, zone=zone,
                    expected_generation=generation, actor="test-suite",
                )
                receipt = evaluation_receipt(
                    artifact_id, population_key, zone,
                    snapshot_hash=training_hash,
                    population_eligibility="verified_regime",
                    population_evidence_sha256=evidence_hash,
                )
                validated = self.store.validate_candidate(
                    population_key=population_key, zone=zone, artifact_id=artifact_id,
                    receipt=receipt, expected_generation=registered["generation"],
                    actor="test-suite",
                )
                if not first_transitions:
                    with self.assertRaisesRegex(LifecycleError, "atomic three-slot generation"):
                        self.store.promote_candidate(
                            population_key=population_key, zone=zone, artifact_id=artifact_id,
                            expected_champion_artifact_id=None,
                            expected_generation=validated["generation"],
                            approval=approval_for(artifact_id, population_key, zone, receipt),
                            approval_verifier=self.verifier, actor="test-suite",
                        )
                first_artifacts[(population_key, zone)] = artifact_id
                first_receipts[(population_key, zone)] = receipt
                first_transitions.append({
                    "population_key": population_key,
                    "zone": zone,
                    "artifact_id": artifact_id,
                    "expected_champion_artifact_id": None,
                    "approval": approval_for(artifact_id, population_key, zone, receipt),
                })
                generation = validated["generation"]
        first_promoted = self.store.promote_three_slot_generation(
            first_transitions, expected_generation=generation,
            approval_verifier=self.verifier, actor="test-suite",
        )

        second_transitions = []
        second_artifacts = {}
        generation = first_promoted["generation"]
        for population_key in population_keys:
            training_hash = hashlib.sha256(("second:" + population_key).encode("utf-8")).hexdigest()
            for zone in ("front", "back"):
                artifact_payload = model_payload(zone, training_hash)
                from lottery.subset_model.artifact import create_artifact
                _, artifact_id = create_artifact(artifact_payload)
                registered = self.store.register_challenger(
                    artifact_payload, population_key=population_key, zone=zone,
                    expected_generation=generation, actor="test-suite",
                )
                receipt = evaluation_receipt(
                    artifact_id, population_key, zone,
                    snapshot_hash=training_hash,
                    population_eligibility="verified_regime",
                    population_evidence_sha256=evidence_hash,
                )
                validated = self.store.validate_candidate(
                    population_key=population_key, zone=zone, artifact_id=artifact_id,
                    receipt=receipt, expected_generation=registered["generation"],
                    actor="test-suite",
                )
                old_id = first_artifacts[(population_key, zone)]
                prospective_shadow = shadow_receipt(
                    artifact_id, population_key, zone, old_id
                )
                shadowed = self.store.mark_shadow(
                    population_key=population_key, zone=zone, artifact_id=artifact_id,
                    shadow_receipt=prospective_shadow,
                    expected_generation=validated["generation"], actor="test-suite",
                )
                shadow_hash = hashlib.sha256(canonicalize(prospective_shadow)).hexdigest()
                second_artifacts[(population_key, zone)] = artifact_id
                second_transitions.append({
                    "population_key": population_key,
                    "zone": zone,
                    "artifact_id": artifact_id,
                    "expected_champion_artifact_id": old_id,
                    "approval": approval_for(
                        artifact_id, population_key, zone, receipt,
                        expected_champion_artifact_id=old_id,
                        shadow_receipt_sha256=shadow_hash,
                    ),
                })
                generation = shadowed["generation"]
        second_promoted = self.store.promote_three_slot_generation(
            second_transitions, expected_generation=generation,
            approval_verifier=self.verifier, actor="test-suite",
        )

        restore_transitions = []
        for population_key in population_keys:
            for zone in ("front", "back"):
                first_id = first_artifacts[(population_key, zone)]
                second_id = second_artifacts[(population_key, zone)]
                first_receipt = first_receipts[(population_key, zone)]
                restore_transitions.append({
                    "population_key": population_key,
                    "zone": zone,
                    "artifact_id": first_id,
                    "expected_champion_artifact_id": second_id,
                    "approval": approval_for(
                        first_id, population_key, zone, first_receipt,
                        action="restore", expected_champion_artifact_id=second_id,
                    ),
                })
        restored = self.store.restore_three_slot_generation(
            restore_transitions, expected_generation=second_promoted["generation"],
            approval_verifier=self.verifier, actor="test-suite",
        )
        resolved = self.store.resolve_three_slot_generation(
            population_keys, approval_verifier=self.verifier
        )
        self.assertEqual(len(resolved["slots"]), 6)
        self.assertEqual(resolved["registry_generation"], restored["generation"])
        self.assertEqual(resolved["champion_generation"], restored["generation"])
        resolved_ids = {
            (item["population_key"], item["zone"]): item["artifact_id"]
            for item in resolved["slots"]
        }
        self.assertEqual(resolved_ids, first_artifacts)


    def test_boolean_generation_is_rejected_as_invalid_compare_and_swap_token(self):
        with self.assertRaisesRegex(LifecycleError, "non-negative integer"):
            self.store.register_challenger(
                model_payload("front"),
                population_key="pooled_equipment_blind",
                zone="front",
                expected_generation=True,
                actor="test-suite",
            )

    def test_event_hash_chain_detects_tampering(self):
        artifact_id, _, _ = self.register_and_validate()
        raw = self.store.events_path.read_bytes()
        self.store.events_path.write_bytes(raw.replace(artifact_id.encode("ascii"), b"sha256:" + b"0" * 64, 1))
        with self.assertRaisesRegex(LifecycleError, "event hash chain failed"):
            self.store.snapshot()

    def test_three_slot_resolution_is_all_or_none_and_reverifies_approval(self):
        with self.assertRaisesRegex(LifecycleError, "exactly three distinct"):
            self.store.resolve_three_slot_generation(["only-one"], approval_verifier=self.verifier)
        with self.assertRaisesRegex(LifecycleError, "reported indices 1/2/3"):
            self.store.resolve_three_slot_generation(
                [
                    "regime-a|reported_set_index=1",
                    "regime-a|reported_set_index=2",
                    "regime-b|reported_set_index=3",
                ],
                approval_verifier=self.verifier,
            )
        with self.assertRaisesRegex(LifecycleError, "protected approval verifier"):
            self.store.resolve_three_slot_generation(
                [
                    "regime-a|reported_set_index=1",
                    "regime-a|reported_set_index=2",
                    "regime-a|reported_set_index=3",
                ],
                approval_verifier=None,
            )


if __name__ == "__main__":
    unittest.main()
