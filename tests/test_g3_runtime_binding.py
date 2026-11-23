import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import run_subset_rolling_origin as runner
from lottery.experiment_registry import ExperimentRegistry


REPOSITORY = "Be90nia/Lottery"
REPOSITORY_ID = "1461523125"
WORKFLOW_PATH = ".github/workflows/subset-research.yml"
CHECKED_OUT_SHA = "a" * 40
RUN_ID = "45130000000"


def actions_environment():
    ref = "refs/heads/feat/lot-064-g3-runtime-binding-isolated"
    return {
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_REPOSITORY_ID": REPOSITORY_ID,
        "GITHUB_WORKFLOW_REF": f"{REPOSITORY}/{WORKFLOW_PATH}@{ref}",
        "GITHUB_RUN_ID": RUN_ID,
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_JOB": "full-rolling-origin",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": ref,
        "GITHUB_SHA": CHECKED_OUT_SHA,
        "GITHUB_ACTOR": "research-operator",
    }


class G3RuntimeBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.snapshot_digest = runner._load_and_validate(
            Path("data/processed/draws-20261118.jsonl")
        )
        cls.registration_path = Path("docs/G3_DIAGNOSTIC_REGISTRATION_2026-11-22.json")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.registry_root = Path(self.temp.name) / "experiment-registry"
        self.output_dir = Path(self.temp.name) / "outputs"
        self.output_dir.mkdir()
        self.output_path = self.output_dir / "subset-model-rolling-origin.json"
        self.env_patch = patch.dict(os.environ, actions_environment(), clear=False)
        self.env_patch.start()
        self.git_patch = patch.object(
            runner.subprocess,
            "run",
            return_value=SimpleNamespace(stdout=CHECKED_OUT_SHA + "\\n"),
        )
        self.git_patch.start()

    def tearDown(self):
        self.git_patch.stop()
        self.env_patch.stop()
        self.temp.cleanup()

    def start_binding(self):
        return runner._start_registered_execution(
            self.rows,
            self.snapshot_digest,
            self.registration_path,
            self.registry_root,
        )

    def test_g3_spec_preserves_retrospective_class_lineage_and_no_approval(self):
        spec, config = runner._build_g3_registry_spec(
            self.rows, self.snapshot_digest, self.registration_path
        )
        self.assertEqual(spec["experiment_class"], "exploratory")
        self.assertTrue(spec["outcomes_observed"])
        self.assertIsNone(spec["parent_experiment_id"])
        self.assertFalse(config["approval_required"])
        self.assertEqual(config["approval_disposition"], "not_required_exploratory")
        self.assertEqual(
            config["legacy_parent_issue_url"],
            "https://github.com/Be90nia/Lottery/issues/18",
        )
        self.assertEqual(
            config["legacy_child_registration_comment_url"],
            "https://github.com/Be90nia/Lottery/issues/27#issuecomment-7028060751",
        )
        self.assertIn("no synthetic content-addressed parent ID", config["parent_lineage_disposition"])

    def test_registration_start_manifest_terminal_and_exact_event_hashes_bind(self):
        registry, binding = self.start_binding()
        self.assertEqual(binding["experiment_class"], "exploratory")
        self.assertIsNone(binding["approval_sha256"])
        self.assertFalse(binding["approval_required"])
        self.assertEqual(binding["approval_disposition"], "not_required_exploratory")

        (self.output_dir / "run_manifest.json").write_text(
            json.dumps({
                "run_id": "lot055-test-evaluation-id",
                "status": "complete_with_explicit_failures",
                "confirmatory_eligible": False,
            }),
            encoding="utf-8",
        )
        (self.output_dir / "model-artifacts.jsonl").write_bytes(b'{"artifact_id":"test"}\\n')

        receipt = runner._finish_registered_execution(registry, binding, self.output_path)
        snapshot = registry.snapshot()
        attempt = snapshot["experiments"][binding["experiment_id"]]["attempts"][binding["attempt_id"]]
        self.assertEqual(attempt["status"], "succeeded")
        self.assertEqual(attempt["execution_id"], binding["execution_id"])
        self.assertIsNone(attempt["approval_sha256"])
        self.assertEqual(receipt["execution_status"], "completed")
        self.assertEqual(receipt["scientific_result_status"], "complete_with_explicit_failures")
        self.assertFalse(receipt["confirmatory_eligible"])
        self.assertEqual(receipt["approval_disposition"], "not_required_exploratory")
        self.assertTrue(receipt["start_event_sha256"])
        self.assertTrue(receipt["terminal_event_sha256"])
        self.assertEqual(receipt["event_chain_head_sha256"], receipt["terminal_event_sha256"])
        self.assertEqual(receipt["event_count_at_terminal"], 3)
        self.assertEqual(
            receipt["legacy_child_registration_comment_url"],
            "https://github.com/Be90nia/Lottery/issues/27#issuecomment-7028060751",
        )
        receipt_bytes = (self.output_dir / "registry-run-receipt.json").read_bytes()
        replayed = runner._finish_registered_execution(registry, binding, self.output_path)
        self.assertEqual(replayed, receipt)
        self.assertEqual((self.output_dir / "registry-run-receipt.json").read_bytes(), receipt_bytes)
        self.assertTrue((self.output_dir / "registry-run-receipt.json").exists())

    def test_caught_runner_exception_terminalizes_started_attempt(self):
        registry, binding = self.start_binding()
        with patch.object(runner, "_run_impl", side_effect=RuntimeError("simulated runner failure")):
            with self.assertRaisesRegex(RuntimeError, "simulated runner failure"):
                runner.run(
                    Path("unused-snapshot.jsonl"),
                    self.output_path,
                    registry_root=self.registry_root,
                    registration_path=self.registration_path,
                    require_execution_binding=True,
                )
        attempt = registry.snapshot()["experiments"][binding["experiment_id"]]["attempts"][binding["attempt_id"]]
        self.assertEqual(attempt["status"], "runner_error")
        self.assertEqual(attempt["failure_code"], "RuntimeError")


if __name__ == "__main__":
    unittest.main()
