import hashlib
import tempfile
import unittest
from pathlib import Path

from lottery.experiment_registry import (
    EVENT_SCHEMA,
    EXPERIMENT_SCHEMA,
    ExperimentApprovalError,
    ExperimentRegistry,
    ExperimentRegistryError,
)
from lottery.execution_context import execution_context_from_env
from lottery.subset_model.artifact import canonicalize


def digest(label):
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def execution_context(*, attempt="1"):
    repository = "Be90nia/Lottery"
    workflow_path = ".github/workflows/subset-research.yml"
    commit = "a" * 40
    env = {
        "GITHUB_REPOSITORY": repository,
        "GITHUB_REPOSITORY_ID": "1461523125",
        "GITHUB_WORKFLOW_REF": f"{repository}/{workflow_path}@refs/heads/feature",
        "GITHUB_RUN_ID": "45130000000",
        "GITHUB_RUN_ATTEMPT": attempt,
        "GITHUB_JOB": "run-evaluation",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/feature",
        "GITHUB_SHA": commit,
        "GITHUB_ACTOR": "research-operator",
    }
    return execution_context_from_env(
        env, checked_out_sha=commit,
        expected_repository=repository,
        expected_repository_id="1461523125",
        expected_workflow_path=workflow_path,
    )


def experiment_spec(*, experiment_class="confirmatory", parent=None, outcomes_observed=False):
    return {
        "schema": EXPERIMENT_SCHEMA,
        "experiment_name": "exact-subset-candidate-v1",
        "experiment_class": experiment_class,
        "parent_experiment_id": parent,
        "hypothesis": "candidate exact-set NLL is lower than uniform",
        "model_family": "complete_subset_exponential",
        "population_key": "pooled_equipment_blind",
        "zone": "joint",
        "training_snapshot_sha256": digest("training-snapshot"),
        "training_cutoff_draw_id": "26130",
        "target_draw_ids": ["26131", "26132"],
        "target_manifest_sha256": digest("target-manifest"),
        "source_evidence_sha256": digest("source-evidence"),
        "feature_schema_sha256": digest("feature-schema"),
        "trial_plan": [
            {"regularization_lambda": 1.0, "optimizer": "lbfgs"},
            {"regularization_lambda": 0.5, "optimizer": "lbfgs"},
        ],
        "primary_metric": "exact_set_nll",
        "multiplicity_family": ["front_candidate_vs_uniform", "back_candidate_vs_uniform"],
        "bootstrap_replicates": 1000,
        "block_length": 50,
        "seed_commitment_sha256": digest("protected-seed-commitment"),
        "holdout_accessed": False,
        "outcomes_observed": outcomes_observed,
        "population_claim": "pooled",
        "population_evidence_sha256": None,
    }


class ExperimentRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.registry = ExperimentRegistry(Path(self.temp.name) / "experiments")
        self.verifier = lambda approval, expected: (
            approval.get("experiment_id") == expected["experiment_id"]
            and approval.get("spec_sha256") == expected["spec_sha256"]
            and expected["policy"] == "LOT-064-confirmatory-v1"
        )

    def tearDown(self):
        self.temp.cleanup()

    def register_confirmatory(self, spec=None):
        spec = spec or experiment_spec()
        experiment_id = hashlib.sha256(canonicalize(spec)).hexdigest()
        approval = {
            "experiment_id": experiment_id,
            "spec_sha256": experiment_id,
            "approver_id": "protected-reviewer",
            "issued_at_utc": "2026-11-20T10:00:00+00:00",
            "signature": "test-only-signature",
        }
        result = self.registry.register_experiment(
            spec, actor="test-suite", approval=approval,
            approval_verifier=self.verifier,
        )
        return result

    def test_confirmatory_registration_requires_protected_approval(self):
        with self.assertRaises(ExperimentApprovalError):
            self.registry.register_experiment(
                experiment_spec(), actor="test-suite",
                approval_verifier=None,
            )
        result = self.register_confirmatory()
        self.assertEqual(result["experiment_id"], result["spec_sha256"])
        self.assertEqual(len(self.registry.snapshot()["experiments"]), 1)

    def test_trial_start_and_finish_bind_exact_approval_receipt(self):
        registered = self.register_confirmatory()
        experiment_id = registered["experiment_id"]
        config = experiment_spec()["trial_plan"][0]
        started = self.registry.start_trial(
            experiment_id=experiment_id,
            attempt_id="approval-bound-001",
            config=config,
            actor="test-suite",
        )
        self.assertEqual(started["approval_sha256"], registered["approval_sha256"])
        finished = self.registry.finish_trial(
            experiment_id=experiment_id,
            attempt_id="approval-bound-001",
            terminal_status="succeeded",
            result_sha256=digest("approval-bound-result"),
            artifact_sha256=digest("approval-bound-artifact"),
            actor="test-suite",
        )
        self.assertEqual(finished["approval_sha256"], registered["approval_sha256"])

    def test_new_event_writes_reject_unknown_fields(self):
        event = {
            "schema": EVENT_SCHEMA,
            "event_id": "register:unknown-field-test",
            "event_type": "experiment_registered",
            "occurred_at_utc": "2026-11-23T00:00:00+00:00",
            "actor": "test-suite",
            "experiment_id": digest("unknown-field-experiment"),
            "approval_sha256": None,
            "untrusted_extra": "must fail",
        }
        with self.assertRaisesRegex(ExperimentRegistryError, "closed event schema"):
            self.registry._append_event_locked(event)

    def test_registration_retry_is_idempotent(self):
        first = self.register_confirmatory()
        second = self.registry.register_experiment(
            experiment_spec(), actor="retry-without-new-approval"
        )
        self.assertEqual(first, second)
        self.assertEqual(self.registry.snapshot()["event_count"], 1)

    def test_trial_must_match_preregistered_configuration_and_failures_are_retained(self):
        registered = self.register_confirmatory()
        experiment_id = registered["experiment_id"]
        with self.assertRaisesRegex(ExperimentRegistryError, "not included"):
            self.registry.start_trial(
                experiment_id=experiment_id,
                attempt_id="unregistered-config",
                config={"regularization_lambda": 99.0},
                actor="test-suite",
            )
        config = experiment_spec()["trial_plan"][0]
        started = self.registry.start_trial(
            experiment_id=experiment_id,
            attempt_id="attempt-001",
            config=config,
            actor="test-suite",
        )
        self.assertEqual(started["status"], "running")
        failed = self.registry.finish_trial(
            experiment_id=experiment_id,
            attempt_id="attempt-001",
            terminal_status="fit_failed",
            failure_code="line_search_failed",
            actor="test-suite",
        )
        self.assertEqual(failed["status"], "fit_failed")
        self.assertEqual(failed["failure_code"], "line_search_failed")
        with self.assertRaisesRegex(ExperimentRegistryError, "cannot be overwritten"):
            self.registry.finish_trial(
                experiment_id=experiment_id,
                attempt_id="attempt-001",
                terminal_status="succeeded",
                result_sha256=digest("result"),
                actor="test-suite",
            )
        self.assertEqual(
            self.registry.snapshot()["experiments"][experiment_id]["attempts"]["attempt-001"]["status"],
            "fit_failed",
        )

    def test_every_retry_attempt_is_preserved_separately(self):
        registered = self.register_confirmatory()
        experiment_id = registered["experiment_id"]
        config = experiment_spec()["trial_plan"][0]
        for attempt_id, failure in (("attempt-001", "timeout"), ("attempt-002", "line_search_failed")):
            self.registry.start_trial(
                experiment_id=experiment_id, attempt_id=attempt_id,
                config=config, actor="test-suite",
            )
            self.registry.finish_trial(
                experiment_id=experiment_id, attempt_id=attempt_id,
                terminal_status="runner_error" if failure == "timeout" else "fit_failed",
                failure_code=failure, actor="test-suite",
            )
        attempts = self.registry.snapshot()["experiments"][experiment_id]["attempts"]
        self.assertEqual(set(attempts), {"attempt-001", "attempt-002"})
        self.assertEqual(attempts["attempt-001"]["failure_code"], "timeout")
        self.assertEqual(attempts["attempt-002"]["failure_code"], "line_search_failed")

    def test_successful_trial_requires_result_digest(self):
        registered = self.register_confirmatory()
        experiment_id = registered["experiment_id"]
        self.registry.start_trial(
            experiment_id=experiment_id, attempt_id="success-001",
            config=experiment_spec()["trial_plan"][0], actor="test-suite",
        )
        with self.assertRaisesRegex(ExperimentRegistryError, "result digest"):
            self.registry.finish_trial(
                experiment_id=experiment_id, attempt_id="success-001",
                terminal_status="succeeded", actor="test-suite",
            )
        result = self.registry.finish_trial(
            experiment_id=experiment_id, attempt_id="success-001",
            terminal_status="succeeded", result_sha256=digest("result"),
            artifact_sha256=digest("artifact"), actor="test-suite",
        )
        self.assertEqual(result["status"], "succeeded")

    def test_execution_identity_is_bound_to_trial_start_and_terminal_event(self):
        registered = self.register_confirmatory()
        experiment_id = registered["experiment_id"]
        config = experiment_spec()["trial_plan"][0]
        context = execution_context()
        started = self.registry.start_trial(
            experiment_id=experiment_id,
            attempt_id="actions-45130000000-attempt-1",
            config=config,
            actor="research-operator",
            execution_context=context,
            expected_repository="Be90nia/Lottery",
            expected_repository_id="1461523125",
            expected_workflow_path=".github/workflows/subset-research.yml",
        )
        self.assertEqual(started["execution_id"], context["execution_id"])
        self.assertEqual(started["trial_id"], started["config_sha256"])
        with self.assertRaisesRegex(ExperimentRegistryError, "does not match trial start"):
            self.registry.finish_trial(
                experiment_id=experiment_id,
                attempt_id="actions-45130000000-attempt-1",
                terminal_status="succeeded",
                result_sha256=digest("result"),
                artifact_sha256=digest("artifact"),
                execution_id="f" * 64,
                actor="research-operator",
            )
        with self.assertRaisesRegex(ExperimentRegistryError, "requires an artifact digest"):
            self.registry.finish_trial(
                experiment_id=experiment_id,
                attempt_id="actions-45130000000-attempt-1",
                terminal_status="succeeded",
                result_sha256=digest("result"),
                execution_id=context["execution_id"],
                actor="research-operator",
            )
        finished = self.registry.finish_trial(
            experiment_id=experiment_id,
            attempt_id="actions-45130000000-attempt-1",
            terminal_status="succeeded",
            result_sha256=digest("result"),
            artifact_sha256=digest("artifact"),
            execution_id=context["execution_id"],
            actor="research-operator",
        )
        self.assertEqual(finished["execution_id"], context["execution_id"])
        self.assertEqual(finished["status"], "succeeded")

    def test_execution_context_requires_explicit_workflow_allowlist(self):
        registered = self.register_confirmatory()
        with self.assertRaisesRegex(ExperimentRegistryError, "explicit repository/workflow allowlist"):
            self.registry.start_trial(
                experiment_id=registered["experiment_id"],
                attempt_id="actions-no-allowlist",
                config=experiment_spec()["trial_plan"][0],
                actor="research-operator",
                execution_context=execution_context(),
            )

    def test_holdout_access_and_training_target_leakage_are_rejected(self):
        bad_holdout = experiment_spec()
        bad_holdout["holdout_accessed"] = True
        with self.assertRaisesRegex(ExperimentRegistryError, "holdout"):
            self.registry.register_experiment(bad_holdout, actor="test-suite")
        leaked = experiment_spec()
        leaked["target_draw_ids"] = ["26130", "26131"]
        with self.assertRaisesRegex(ExperimentRegistryError, "strictly after"):
            self.registry.register_experiment(leaked, actor="test-suite")

    def test_post_result_child_must_be_exploratory(self):
        parent_spec = experiment_spec(experiment_class="exploratory")
        parent = self.registry.register_experiment(parent_spec, actor="test-suite")
        parent_id = parent["experiment_id"]
        self.registry.start_trial(
            experiment_id=parent_id, attempt_id="parent-attempt",
            config=parent_spec["trial_plan"][0], actor="test-suite",
        )
        self.registry.finish_trial(
            experiment_id=parent_id, attempt_id="parent-attempt",
            terminal_status="succeeded", result_sha256=digest("parent-result"),
            actor="test-suite",
        )
        confirmatory_child = experiment_spec(parent=parent_id)
        with self.assertRaisesRegex(ExperimentRegistryError, "must be exploratory"):
            self.registry.register_experiment(confirmatory_child, actor="test-suite")
        exploratory_child = experiment_spec(
            experiment_class="exploratory", parent=parent_id, outcomes_observed=True
        )
        child = self.registry.register_experiment(exploratory_child, actor="test-suite")
        self.assertIn(child["experiment_id"], self.registry.snapshot()["experiments"])

    def test_event_hash_chain_detects_tampering(self):
        registered = self.register_confirmatory()
        self.registry.start_trial(
            experiment_id=registered["experiment_id"], attempt_id="tamper",
            config=experiment_spec()["trial_plan"][0], actor="test-suite",
        )
        raw = self.registry.events_path.read_bytes()
        self.registry.events_path.write_bytes(raw.replace(b"trial_started", b"trial_corrupt", 1))
        with self.assertRaisesRegex(ExperimentRegistryError, "hash chain failed"):
            self.registry.snapshot()


if __name__ == "__main__":
    unittest.main()
