import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lottery.experiment_registry import ExperimentRegistry
from scripts import reconcile_experiment_executions as reconciler


def _sha(value):
    import hashlib
    return hashlib.sha256(value.encode()).hexdigest()


class ExecutionReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "registry"
        self.registry = ExperimentRegistry(self.root)
        self.spec = {
            "schema": "lottery.experiment-preregistration/v1",
            "experiment_name": "reconcile-test",
            "experiment_class": "exploratory",
            "parent_experiment_id": None,
            "hypothesis": "test",
            "model_family": "test-model",
            "population_key": "pooled",
            "zone": "joint",
            "training_snapshot_sha256": _sha("snapshot"),
            "training_cutoff_draw_id": "09053",
            "target_draw_ids": ["09054"],
            "target_manifest_sha256": _sha("targets"),
            "source_evidence_sha256": _sha("source"),
            "feature_schema_sha256": _sha("features"),
            "trial_plan": [{"seed": 1}],
            "primary_metric": "nll",
            "multiplicity_family": [],
            "bootstrap_replicates": 1000,
            "block_length": 50,
            "seed_commitment_sha256": _sha("seed"),
            "holdout_accessed": False,
            "outcomes_observed": True,
            "population_claim": "pooled",
            "population_evidence_sha256": None,
        }
        self.registered = self.registry.register_experiment(self.spec, actor="test")
        self.context = {
            "schema": "lottery.github-actions-execution/v2",
            "repository": "Be90nia/Lottery",
            "repository_id": "1461523125",
            "workflow_id": 423307604,
            "workflow_path": ".github/workflows/subset-research.yml",
            "workflow_ref": "Be90nia/Lottery/.github/workflows/subset-research.yml@refs/heads/test",
            "run_id": 123456,
            "run_attempt": 1,
            "job": "full-rolling-origin",
            "event_name": "push",
            "ref": "refs/heads/test",
            "sha": "a" * 40,
            "actor": "test",
            "run_url": "https://github.com/Be90nia/Lottery/actions/runs/123456",
        }
        from lottery.execution_context import _execution_digest
        self.context["execution_id"] = _execution_digest(self.context)
        self.registry.start_trial(
            experiment_id=self.registered["experiment_id"],
            attempt_id="attempt-1", config=self.spec["trial_plan"][0],
            actor="test", execution_context=self.context,
            expected_repository="Be90nia/Lottery",
            expected_repository_id="1461523125",
            expected_workflow_id=423307604,
            expected_workflow_path=".github/workflows/subset-research.yml",
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_running_registry_attempt_against_completed_workflow_is_reported(self):
        run = {
            "id": 123456, "run_attempt": 1, "workflow_id": 423307604,
            "path": ".github/workflows/subset-research.yml@refs/heads/test", "head_sha": "a" * 40,
            "event": "push", "ref": "refs/heads/test", "status": "completed",
            "conclusion": "success", "repository": {"id": 1461523125},
        }
        with patch.object(reconciler, "_api_json", return_value=run) as api, patch.object(
            reconciler, "_paged_items", return_value=[]
        ):
            report = reconciler.reconcile(
                registry_root=self.root, token="test",
                repository="Be90nia/Lottery", repository_id="1461523125",
                workflow_id=423307604,
                workflow_path=".github/workflows/subset-research.yml",
            )
        self.assertTrue(any(
            item["code"] == "workflow_terminal_registry_running"
            for item in report["findings"]
        ))
        self.assertEqual(report["mode"], "read_only")
        self.assertIn("/actions/runs/123456/attempts/1", api.call_args.args[0])

    def test_unbound_workflow_run_is_reported(self):
        with patch.object(reconciler, "_api_json", return_value={
            "id": 123456, "run_attempt": 1, "workflow_id": 423307604,
            "path": ".github/workflows/subset-research.yml", "head_sha": "a" * 40,
            "event": "push", "ref": "refs/heads/test", "status": "in_progress",
            "repository": {"id": 1461523125},
        }), patch.object(reconciler, "_paged_items", return_value=[
            {"id": 999999, "run_attempt": 1, "path": ".github/workflows/subset-research.yml",
             "status": "completed", "conclusion": "cancelled", "head_sha": "b" * 40}
        ]):
            report = reconciler.reconcile(
                registry_root=self.root, token="test",
                repository="Be90nia/Lottery", repository_id="1461523125",
                workflow_id=423307604,
                workflow_path=".github/workflows/subset-research.yml",
            )
        self.assertTrue(any(
            item["code"] == "workflow_run_without_registry_binding"
            and item["run_id"] == 999999
            for item in report["findings"]
        ))


    def test_distinct_rerun_attempts_are_checked_independently(self):
        second_context = dict(self.context)
        second_context["run_attempt"] = 2
        from lottery.execution_context import _execution_digest
        second_context["execution_id"] = _execution_digest(second_context)
        self.registry.start_trial(
            experiment_id=self.registered["experiment_id"],
            attempt_id="attempt-2", config=self.spec["trial_plan"][0],
            actor="test", execution_context=second_context,
            expected_repository="Be90nia/Lottery",
            expected_repository_id="1461523125",
            expected_workflow_id=423307604,
            expected_workflow_path=".github/workflows/subset-research.yml",
        )
        def run(attempt, status):
            return {
                "id": 123456, "run_attempt": attempt, "workflow_id": 423307604,
                "path": ".github/workflows/subset-research.yml@refs/heads/test",
                "head_sha": "a" * 40, "event": "push", "ref": "refs/heads/test",
                "status": status, "conclusion": "success" if status == "completed" else None,
                "repository": {"id": 1461523125},
            }
        with patch.object(
            reconciler, "_api_json",
            side_effect=[run(1, "completed"), run(2, "in_progress")],
        ) as api, patch.object(reconciler, "_paged_items", return_value=[]):
            report = reconciler.reconcile(
                registry_root=self.root, token="test",
                repository="Be90nia/Lottery", repository_id="1461523125",
                workflow_id=423307604,
                workflow_path=".github/workflows/subset-research.yml",
            )
        requested = [call.args[0] for call in api.call_args_list]
        self.assertTrue(any(url.endswith("/runs/123456/attempts/1") for url in requested))
        self.assertTrue(any(url.endswith("/runs/123456/attempts/2") for url in requested))
        self.assertTrue(any(
            item["code"] == "workflow_terminal_registry_running"
            and item["attempt_id"] == "attempt-1"
            for item in report["findings"]
        ))

    def test_execution_identity_mismatch_is_reported(self):
        run = {
            "id": 123456, "run_attempt": 2, "workflow_id": 423307604,
            "path": ".github/workflows/subset-research.yml", "head_sha": "c" * 40,
            "event": "push", "ref": "refs/heads/test", "status": "in_progress",
            "repository": {"id": 1461523125},
        }
        with patch.object(reconciler, "_api_json", return_value=run), patch.object(
            reconciler, "_paged_items", return_value=[]
        ):
            report = reconciler.reconcile(
                registry_root=self.root, token="test",
                repository="Be90nia/Lottery", repository_id="1461523125",
                workflow_id=423307604,
                workflow_path=".github/workflows/subset-research.yml",
            )
        self.assertTrue(any(
            item["code"] == "workflow_metadata_mismatch"
            for item in report["findings"]
        ))


if __name__ == "__main__":
    unittest.main()
