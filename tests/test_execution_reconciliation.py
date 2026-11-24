import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lottery.experiment_registry import ExperimentRegistry
from scripts import reconcile_experiment_executions as reconciler
from scripts import run_subset_rolling_origin as runner


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


    def test_imported_source_artifact_digest_mismatch_is_reported(self):
        source = {
            "source_run_url": self.context["run_url"],
            "source_started_at_utc": "2026-11-20T06:06:56Z",
            "source_completed_at_utc": "2026-11-20T08:07:28Z",
            "source_artifact_id": 777,
            "source_artifact_zip_sha256": _sha("expected-zip"),
            "source_manifest_sha256": _sha("manifest"),
            "source_model_artifacts_sha256": _sha("model-artifacts"),
            "source_evidence_sha256": _sha("evidence"),
            "scientific_result_status": "complete_with_explicit_failures",
            "confirmatory_eligible": False,
        }
        def verifier(metadata, context):
            import hashlib
            from lottery.subset_model.artifact import canonicalize
            return {
                "schema": "lottery.github-actions-verification/v1",
                "verifier_id": "test-verifier/v1",
                "verified": True,
                "source_metadata_sha256": hashlib.sha256(canonicalize(metadata)).hexdigest(),
                "artifact_zip_sha256": metadata["source_artifact_zip_sha256"],
                "source_evidence_sha256": metadata["source_evidence_sha256"],
                "verified_at_utc": "2026-11-24T00:00:00Z",
            }
        import_registry_root = self.root.parent / "import-registry"
        import_registry = ExperimentRegistry(import_registry_root)
        import_registered = import_registry.register_experiment(self.spec, actor="test")
        import_registry.import_completed_trial(
            experiment_id=import_registered["experiment_id"],
            attempt_id="imported-attempt-1",
            config=self.spec["trial_plan"][0], actor="test",
            execution_context=self.context, source_metadata=source,
            metadata_verifier=verifier,
            expected_repository="Be90nia/Lottery",
            expected_repository_id="1461523125",
            expected_workflow_id=423307604,
            expected_workflow_path=".github/workflows/subset-research.yml",
        )
        run = {
            "id": 123456, "run_attempt": 1, "workflow_id": 423307604,
            "path": ".github/workflows/subset-research.yml@refs/heads/test",
            "head_sha": "a" * 40, "event": "push", "ref": "refs/heads/test",
            "status": "completed", "conclusion": "success",
            "repository": {"id": 1461523125},
        }
        bad_artifact = {
            "id": 777, "digest": "sha256:" + _sha("tampered-zip"),
            "expired": False,
            "workflow_run": {"id": 123456, "repository_id": 1461523125, "head_sha": "a" * 40},
        }
        with patch.object(reconciler, "_api_json", return_value=run), patch.object(
            reconciler, "_paged_items", side_effect=[[bad_artifact], []]
        ):
            report = reconciler.reconcile(
                registry_root=self.root, token="test",
                repository="Be90nia/Lottery", repository_id="1461523125",
                workflow_id=423307604,
                workflow_path=".github/workflows/subset-research.yml",
            )
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("imported_source_artifact_mismatch", codes)
        self.assertIn("historical_execution_not_durably_committed", codes)


    def test_committed_storage_bundle_without_terminal_event_is_reported_read_only(self):
        output_dir = self.root.parent / "outputs"
        output_dir.mkdir()
        output_path = output_dir / "evaluation.json"
        outputs = {
            "target-score-ledger.jsonl": b'{"record_type":"target"}',
            "model-artifacts.jsonl": b'{"artifact_id":"sha256:' + b"a" * 64 + b'"}',
            "model-artifact-provenance.jsonl": b'{"artifact_id":"sha256:' + b"a" * 64 + b'"}',
        }
        declarations = {}
        for filename, raw in outputs.items():
            (output_dir / filename).write_bytes(raw)
            declarations[filename] = {
                "sha256": __import__("hashlib").sha256(raw).hexdigest(),
                "bytes": len(raw),
            }
        manifest = {
            "run_id": "evaluation-domain-id",
            "status": "complete_with_explicit_failures",
            "confirmatory_eligible": False,
            "output_files": declarations,
        }
        (output_dir / "run_manifest.json").write_bytes(
            __import__("json").dumps(manifest, sort_keys=True).encode("utf-8")
        )
        binding = {
            "experiment_id": self.registered["experiment_id"],
            "trial_id": __import__("hashlib").sha256(
                runner.canonicalize(self.spec["trial_plan"][0])
            ).hexdigest(),
            "attempt_id": "attempt-1",
            "execution_context": self.context,
        }
        with patch.object(self.registry, "finish_trial", side_effect=RuntimeError("crash after commit")):
            with self.assertRaisesRegex(RuntimeError, "crash after commit"):
                runner._finish_registered_execution(self.registry, binding, output_path)

        run = {
            "id": 123456, "run_attempt": 1, "workflow_id": 423307604,
            "path": ".github/workflows/subset-research.yml@refs/heads/test",
            "head_sha": "a" * 40, "event": "push", "ref": "refs/heads/test",
            "status": "completed", "conclusion": "success",
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
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("storage_bundle_valid_but_terminal_missing", codes)
        self.assertIn("workflow_terminal_registry_running", codes)
        self.assertEqual(
            self.registry.snapshot()["experiments"][self.registered["experiment_id"]]
            ["attempts"]["attempt-1"]["status"],
            "running",
        )

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
