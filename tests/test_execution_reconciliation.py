import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lottery.experiment_registry import ExperimentRegistry
from lottery.storage import FileSystemObjectStore
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
            "workflow_ref": "Be90nia/Lottery/.github/workflows/subset-research.yml@refs/heads/feat/lot-064-g3-runtime-binding-isolated",
            "run_id": 123456,
            "run_attempt": 1,
            "job": "full-rolling-origin",
            "event_name": "push",
            "ref": "refs/heads/feat/lot-064-g3-runtime-binding-isolated",
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
            "path": ".github/workflows/subset-research.yml@refs/heads/feat/lot-064-g3-runtime-binding-isolated", "head_sha": "a" * 40,
            # GitHub Actions API omits ref on this endpoint; head_branch is
            # the authoritative equivalent for a branch-triggered run.
            "event": "push", "head_branch": "test", "status": "completed",
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

    def test_current_run_uses_completed_evaluator_job_before_workflow_wrap_up(self):
        self.registry.finish_trial(
            experiment_id=self.registered["experiment_id"],
            attempt_id="attempt-1",
            terminal_status="runner_error",
            failure_code="simulated_runner_error",
            execution_id=self.context["execution_id"],
            actor="test",
        )
        run = {
            "id": 123456, "run_attempt": 1, "workflow_id": 423307604,
            "path": ".github/workflows/subset-research.yml",
            "head_sha": "a" * 40,
            "event": "push",
            "ref": "refs/heads/feat/lot-064-g3-runtime-binding-isolated",
            "status": "in_progress", "conclusion": None,
            "repository": {"id": 1461523125},
        }
        def pages(url, key, token):
            if url.endswith("/attempts/1/jobs"):
                return [{
                    "name": "full-rolling-origin",
                    "status": "completed",
                    "conclusion": "failure",
                }]
            return []
        with patch.object(reconciler, "_api_json", return_value=run), patch.object(
            reconciler, "_paged_items", side_effect=pages
        ) as paged:
            report = reconciler.reconcile(
                registry_root=self.root, token="test",
                repository="Be90nia/Lottery", repository_id="1461523125",
                workflow_id=423307604,
                workflow_path=".github/workflows/subset-research.yml",
                current_run_id=123456, current_run_job="full-rolling-origin",
            )
        codes = {item["code"] for item in report["findings"]}
        self.assertNotIn("registry_terminal_before_workflow_terminal", codes)
        self.assertNotIn("registry_success_without_successful_workflow", codes)
        self.assertNotIn("workflow_terminal_registry_running", codes)
        self.assertTrue(any(
            call.args[0].endswith("/runs/123456/attempts/1/jobs")
            for call in paged.call_args_list
        ))

    def test_missing_api_ref_is_checked_against_head_branch(self):
        self.assertTrue(reconciler._run_ref_matches(
            {"head_branch": "feature-x"}, "refs/heads/feature-x"
        ))
        self.assertFalse(reconciler._run_ref_matches(
            {"head_branch": "other"}, "refs/heads/feature-x"
        ))
        self.assertTrue(reconciler._run_ref_matches(
            {"pull_requests": [{"number": 114}]}, "refs/pull/114/merge"
        ))
        self.assertFalse(reconciler._run_ref_matches(
            {"pull_requests": [{"number": 115}]}, "refs/pull/114/merge"
        ))

    def test_latest_github_rerun_without_registry_attempt_is_an_error(self):
        run = {
            "id": 123456, "run_attempt": 1, "workflow_id": 423307604,
            "path": ".github/workflows/subset-research.yml", "head_sha": "a" * 40,
            "event": "push", "head_branch": "test", "status": "completed",
            "conclusion": "success", "repository": {"id": 1461523125},
        }
        latest = {
            "id": 123456, "run_attempt": 2,
            "path": ".github/workflows/subset-research.yml",
            "status": "completed", "conclusion": "success",
        }
        with patch.object(reconciler, "_api_json", return_value=run), patch.object(
            reconciler, "_paged_items", return_value=[latest]
        ):
            report = reconciler.reconcile(
                registry_root=self.root, token="test",
                repository="Be90nia/Lottery", repository_id="1461523125",
                workflow_id=423307604,
                workflow_path=".github/workflows/subset-research.yml",
            )
        finding = next(
            item for item in report["findings"]
            if item["code"] == "workflow_rerun_attempt_without_registry_binding"
        )
        self.assertEqual(finding["run_id"], 123456)
        self.assertEqual(finding["run_attempt"], 2)
        self.assertEqual(finding["registered_run_attempts"], [1])

    def test_unbound_workflow_run_is_reported(self):
        with patch.object(reconciler, "_api_json", return_value={
            "id": 123456, "run_attempt": 1, "workflow_id": 423307604,
            "path": ".github/workflows/subset-research.yml", "head_sha": "a" * 40,
            "event": "push", "ref": "refs/heads/feat/lot-064-g3-runtime-binding-isolated", "status": "in_progress",
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
                "path": ".github/workflows/subset-research.yml@refs/heads/feat/lot-064-g3-runtime-binding-isolated",
                "head_sha": "a" * 40, "event": "push", "ref": "refs/heads/feat/lot-064-g3-runtime-binding-isolated",
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
            "path": ".github/workflows/subset-research.yml@refs/heads/feat/lot-064-g3-runtime-binding-isolated",
            "head_sha": "a" * 40, "event": "push", "ref": "refs/heads/feat/lot-064-g3-runtime-binding-isolated",
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
                registry_root=import_registry_root, token="test",
                repository="Be90nia/Lottery", repository_id="1461523125",
                workflow_id=423307604,
                workflow_path=".github/workflows/subset-research.yml",
            )
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("imported_source_artifact_mismatch", codes)
        self.assertIn("historical_execution_not_durably_committed", codes)


    def test_committed_storage_operation_without_receipt_bundle_is_reported(self):
        store = FileSystemObjectStore(self.root.parent / "experiment-storage")
        staged = store.stage(
            idempotency_key=f"lot064-g3:{self.context['execution_id']}:run_manifest.json",
            content=b'{"schema":"test"}',
            media_type="application/json",
            schema_version="lottery.g3-run-output/v1",
            producer_commit=self.context["sha"],
            producer_runtime="python/3.12",
            execution_id=self.context["execution_id"],
        )
        store.validate(
            operation_id=staged["operation_id"],
            validator=lambda raw: True,
            validator_id="lottery.g3-json-object-or-jsonl/v1",
        )
        store.commit(operation_id=staged["operation_id"])
        store.publish_pointer(
            name="g3-crash-window-test",
            operation_id=staged["operation_id"],
            expected_generation=0,
        )
        run = {
            "id": 123456, "run_attempt": 1, "workflow_id": 423307604,
            "path": ".github/workflows/subset-research.yml",
            "head_sha": "a" * 40, "event": "push",
            "ref": "refs/heads/feat/lot-064-g3-runtime-binding-isolated",
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
        finding = next(
            item for item in report["findings"]
            if item["code"] == "committed_storage_operation_without_registry_bundle"
        )
        self.assertEqual(finding["operation_id"], staged["operation_id"])
        self.assertEqual(finding["execution_id"], self.context["execution_id"])

    def test_committed_storage_bundle_without_terminal_event_is_reported_read_only(self):
        output_dir = self.root.parent / "outputs"
        output_dir.mkdir()
        output_path = output_dir / "evaluation.json"
        trial_id = __import__("hashlib").sha256(
            runner.canonicalize(self.spec["trial_plan"][0])
        ).hexdigest()
        binding = {
            "experiment_id": self.registered["experiment_id"],
            "spec_sha256": self.registered["spec_sha256"],
            "experiment_class": "exploratory",
            "approval_sha256": None,
            "approval_required": False,
            "approval_disposition": "not_required_exploratory",
            "approval_disposition_reason": "test-only exploratory binding",
            "legacy_parent_issue_url": "https://github.com/Be90nia/Lottery/issues/18",
            "legacy_child_registration_comment_url": "https://github.com/Be90nia/Lottery/issues/27#issuecomment-7028060751",
            "legacy_child_registration_comment_sha256": "a" * 64,
            "parent_lineage_disposition": "test-only lineage",
            "trial_id": trial_id,
            "attempt_id": "attempt-1",
            "execution_context": self.context,
        }
        artifact_id = "sha256:" + "a" * 64
        target_records = []
        for target_id, target_date in (("09054", "2026-11-18"),):
            target_row = {
                "zone": "front", "model_name": "candidate",
                "target_draw_id": target_id, "target_draw_date": target_date,
                "training_last_draw_id": "09053", "training_row_count": 1,
                "training_dates_strictly_before_target": True, "terminal_status": "fit_failed",
                "artifact_id": artifact_id, "diagnostic_ref": artifact_id,
                "experiment_id": self.registered["experiment_id"], "trial_id": trial_id,
                "registry_attempt_id": "attempt-1", "execution_id": self.context["execution_id"],
                "approval_sha256": None, "approval_required": False,
                "approval_disposition": "not_required_exploratory",
            }
            target_row["record_sha256"] = "sha256:" + __import__("hashlib").sha256(
                runner.canonicalize(target_row)
            ).hexdigest()
            target_records.append(target_row)
        artifact_record = {"artifact_id": artifact_id}
        provenance_record = {
            "schema": "lottery.model-artifact-provenance/v1",
            "artifact_id": artifact_id,
            "experiment_id": self.registered["experiment_id"],
            "trial_id": trial_id,
            "attempt_id": "attempt-1",
            "execution_id": self.context["execution_id"],
            "approval_sha256": None,
            "approval_required": False,
            "approval_disposition": "not_required_exploratory",
            "experiment_class": "exploratory",
            "legacy_parent_issue_url": binding["legacy_parent_issue_url"],
            "legacy_child_registration_comment_url": binding["legacy_child_registration_comment_url"],
            "legacy_child_registration_comment_sha256": binding["legacy_child_registration_comment_sha256"],
            "parent_lineage_disposition": binding["parent_lineage_disposition"],
            "evaluation_run_id": "evaluation-domain-id",
        }
        outputs = {
            "target-score-ledger.jsonl": b"".join(
                runner.canonicalize(row) + b"\n" for row in target_records
            ),
            "model-artifacts.jsonl": runner.canonicalize(artifact_record) + b"\n",
            "model-artifact-provenance.jsonl": runner.canonicalize(provenance_record) + b"\n",
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
            "experiment_id": self.registered["experiment_id"],
            "experiment_class": "exploratory",
            "target_manifest": {
                "target_count_per_zone": 1,
                "first_target_draw_id": "09054",
                "last_target_draw_id": "09054",
            },
            "models": [{"zone": "front", "model_name": "candidate"}],
            "expected_target_record_count": 1,
            "actual_target_record_count": 1,
            "model_artifact_count": 1,
            "model_artifact_provenance_count": 1,
            "terminal_status_counts": {"fit_failed": 1},
            "experiment_binding": {
                "schema": "lottery.experiment-run-binding/v1",
                "experiment_id": binding["experiment_id"],
                "spec_sha256": binding["spec_sha256"],
                "approval_sha256": binding["approval_sha256"],
                "approval_required": binding["approval_required"],
                "approval_disposition": binding["approval_disposition"],
                "approval_disposition_reason": binding["approval_disposition_reason"],
                "legacy_parent_issue_url": binding["legacy_parent_issue_url"],
                "legacy_child_registration_comment_url": binding["legacy_child_registration_comment_url"],
                "legacy_child_registration_comment_sha256": binding["legacy_child_registration_comment_sha256"],
                "parent_lineage_disposition": binding["parent_lineage_disposition"],
                "experiment_class": binding["experiment_class"],
                "trial_id": binding["trial_id"],
                "registry_attempt_id": binding["attempt_id"],
                "execution_id": self.context["execution_id"],
                "execution_context": self.context,
            },
            "output_files": declarations,
        }
        manifest["manifest_sha256"] = "sha256:" + __import__("hashlib").sha256(
            runner.canonicalize(manifest)
        ).hexdigest()
        (output_dir / "run_manifest.json").write_bytes(
            runner.canonicalize(manifest) + b"\n"
        )
        with patch.object(self.registry, "finish_trial", side_effect=RuntimeError("crash after commit")):
            with self.assertRaisesRegex(RuntimeError, "crash after commit"):
                runner._finish_registered_execution(self.registry, binding, output_path)

        run = {
            "id": 123456, "run_attempt": 1, "workflow_id": 423307604,
            "path": ".github/workflows/subset-research.yml@refs/heads/feat/lot-064-g3-runtime-binding-isolated",
            "head_sha": "a" * 40, "event": "push", "ref": "refs/heads/feat/lot-064-g3-runtime-binding-isolated",
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
        self.assertIn("storage_bundle_valid_but_terminal_missing", codes, report["findings"])
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
            "event": "push", "ref": "refs/heads/feat/lot-064-g3-runtime-binding-isolated", "status": "in_progress",
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
