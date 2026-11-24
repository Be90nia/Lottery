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
        "LOTTERY_WORKFLOW_ID": "423307604",
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
            return_value=SimpleNamespace(stdout=CHECKED_OUT_SHA + "\n"),
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

    def test_g3_registration_source_is_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registration.json"
            source = Path("docs/G3_DIAGNOSTIC_REGISTRATION_2026-11-22.json").read_bytes()
            path.write_bytes(source + b" ")
            with self.assertRaisesRegex(ValueError, "fixed retrospective-registration allowlist"):
                runner._build_g3_registry_spec(self.rows, self.snapshot_digest, path)

    def test_g3_spec_preserves_retrospective_class_lineage_and_no_approval(self):
        spec, config = runner._build_g3_registry_spec(
            self.rows, self.snapshot_digest, self.registration_path
        )
        self.assertEqual(spec["experiment_class"], "exploratory")
        self.assertTrue(spec["outcomes_observed"])
        self.assertEqual(config["legacy_g3_experiment_label"], "LOT055-OPT-DIAG-20261120")
        self.assertEqual(
            config["legacy_g3_label_digest"],
            "4eceab2eab2cc9cdd2961634815f5ed586ddd9f54df5496d7d2754f60039a12a",
        )
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
        self.assertEqual(
            config["legacy_child_registration_comment_sha256"],
            "161a14dc087702780917ec020685f6c85f696e7f90f607d1ede9959abc8cb8c2",
        )
        self.assertIn("no synthetic content-addressed parent ID", config["parent_lineage_disposition"])

    def test_registration_start_manifest_terminal_and_exact_event_hashes_bind(self):
        registry, binding = self.start_binding()
        self.assertEqual(binding["experiment_class"], "exploratory")
        self.assertIsNone(binding["approval_sha256"])
        self.assertFalse(binding["approval_required"])
        self.assertEqual(binding["approval_disposition"], "not_required_exploratory")

        artifact_id = "sha256:" + "a" * 64
        target_rows = self.rows[runner.MIN_TRAIN:]
        target_list = [
            {"target_draw_id": row["draw_id"], "target_draw_date": row["draw_date"]}
            for row in target_rows
        ]
        model_order = ["uniform", "expanding", "ewma", "exponential_family"]
        model_pairs = [
            {"zone": zone, "model_name": model_name}
            for zone in ("front", "back")
            for model_name in model_order
        ]
        target_records = []
        training_last_draw_id = self.rows[runner.MIN_TRAIN - 1]["draw_id"]
        for model in model_pairs:
            for target in target_rows:
                target_row = {
                    "zone": model["zone"],
                    "model_name": model["model_name"],
                    "target_draw_id": target["draw_id"],
                    "target_draw_date": target["draw_date"],
                    "training_last_draw_id": training_last_draw_id,
                    "training_row_count": runner.MIN_TRAIN,
                    "training_dates_strictly_before_target": True,
                    "terminal_status": "fit_failed",
                    "artifact_id": artifact_id,
                    "diagnostic_ref": artifact_id,
                    "experiment_id": binding["experiment_id"],
                    "trial_id": binding["trial_id"],
                    "registry_attempt_id": binding["attempt_id"],
                    "execution_id": binding["execution_context"]["execution_id"],
                    "approval_sha256": binding["approval_sha256"],
                    "approval_required": binding["approval_required"],
                    "approval_disposition": binding["approval_disposition"],
                }
                target_row["record_sha256"] = "sha256:" + runner.hashlib.sha256(
                    runner.canonicalize(target_row)
                ).hexdigest()
                target_records.append(target_row)
        artifact_record = {"artifact_id": artifact_id}
        provenance_record = {
            "schema": "lottery.model-artifact-provenance/v1",
            "artifact_id": artifact_id,
            "experiment_id": binding["experiment_id"],
            "trial_id": binding["trial_id"],
            "attempt_id": binding["attempt_id"],
            "execution_id": binding["execution_context"]["execution_id"],
            "approval_sha256": binding["approval_sha256"],
            "approval_required": binding["approval_required"],
            "approval_disposition": binding["approval_disposition"],
            "experiment_class": binding["experiment_class"],
            "legacy_parent_issue_url": binding["legacy_parent_issue_url"],
            "legacy_child_registration_comment_url": binding["legacy_child_registration_comment_url"],
            "legacy_child_registration_comment_sha256": binding["legacy_child_registration_comment_sha256"],
            "parent_lineage_disposition": binding["parent_lineage_disposition"],
            "evaluation_run_id": "lot055-test-evaluation-id",
        }
        output_payloads = {
            "target-score-ledger.jsonl": b"".join(
                runner.canonicalize(row) + b"\n" for row in target_records
            ),
            "model-artifacts.jsonl": runner.canonicalize(artifact_record) + b"\n",
            "model-artifact-provenance.jsonl": runner.canonicalize(provenance_record) + b"\n",
        }
        for filename, raw in output_payloads.items():
            (self.output_dir / filename).write_bytes(raw)
        manifest = {
            "run_id": "lot055-test-evaluation-id",
            "status": "complete_with_explicit_failures",
            "confirmatory_eligible": False,
            "experiment_id": binding["experiment_id"],
            "experiment_class": binding["experiment_class"],
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
                "execution_id": binding["execution_context"]["execution_id"],
                "execution_context": binding["execution_context"],
            },
            "target_manifest": {
                "target_count_per_zone": len(target_rows),
                "first_target_draw_id": target_rows[0]["draw_id"],
                "last_target_draw_id": target_rows[-1]["draw_id"],
                "target_list_sha256": runner.hashlib.sha256(
                    runner.canonicalize({"targets": target_list})
                ).hexdigest(),
            },
            "models": model_pairs,
            "expected_target_record_count": len(target_rows) * len(model_pairs),
            "actual_target_record_count": len(target_records),
            "model_artifact_count": 1,
            "model_artifact_provenance_count": 1,
            "terminal_status_counts": {"fit_failed": len(target_records)},
            "output_files": {
                filename: {
                    "schema_version": {
                        "target-score-ledger.jsonl": "lottery.target-score-ledger/v1",
                        "model-artifacts.jsonl": "lottery.subset-probability-model/v1",
                        "model-artifact-provenance.jsonl": "lottery.model-artifact-provenance/v1",
                    }[filename],
                    "sha256": runner.hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw),
                }
                for filename, raw in output_payloads.items()
            },
        }
        manifest["manifest_sha256"] = "sha256:" + runner.hashlib.sha256(runner.canonicalize(manifest)).hexdigest()
        (self.output_dir / "run_manifest.json").write_bytes(runner.canonicalize(manifest) + b"\n")

        receipt = runner._finish_registered_execution(registry, binding, self.output_path)
        snapshot = registry.snapshot()
        attempt = snapshot["experiments"][binding["experiment_id"]]["attempts"][binding["attempt_id"]]
        self.assertEqual(attempt["status"], "succeeded")
        self.assertEqual(attempt["execution_id"], binding["execution_context"]["execution_id"])
        self.assertIsNone(attempt["approval_sha256"])
        self.assertEqual(receipt["execution_status"], "completed")
        self.assertEqual(receipt["scientific_result_status"], "complete_with_explicit_failures")
        self.assertTrue(receipt["storage_receipts"])
        self.assertEqual(
            set(receipt["storage_receipts"]),
            {"run_manifest.json", "target-score-ledger.jsonl", "model-artifacts.jsonl",
             "model-artifact-provenance.jsonl"},
        )
        self.assertTrue(all(
            item["read_back_verified"] for item in receipt["storage_receipts"].values()
        ))
        self.assertTrue(receipt["storage_receipts_sha256"])
        self.assertFalse(receipt["confirmatory_eligible"])
        self.assertEqual(receipt["approval_disposition"], "not_required_exploratory")
        self.assertTrue(receipt["start_event_sha256"])
        self.assertTrue(receipt["artifact_commit_event_id"])
        self.assertTrue(receipt["artifact_commit_event_sha256"])
        self.assertTrue(receipt["terminal_event_sha256"])
        self.assertEqual(receipt["event_chain_head_sha256"], receipt["terminal_event_sha256"])
        self.assertEqual(receipt["event_count_at_terminal"], 4)
        self.assertEqual(
            [event["event_type"] for event in registry._read_events()],
            ["experiment_registered", "trial_started", "artifacts_committed", "trial_finished"],
        )
        self.assertIsNotNone(attempt["artifacts_committed"])
        self.assertEqual(
            attempt["artifacts_committed"]["storage_receipts_sha256"],
            receipt["storage_receipts_sha256"],
        )
        self.assertEqual(
            attempt["artifacts_committed"]["output_files"],
            sorted(receipt["storage_receipts"]),
        )
        self.assertEqual(
            receipt["legacy_child_registration_comment_url"],
            "https://github.com/Be90nia/Lottery/issues/27#issuecomment-7028060751",
        )
        self.assertEqual(
            receipt["legacy_child_registration_comment_sha256"],
            "161a14dc087702780917ec020685f6c85f696e7f90f607d1ede9959abc8cb8c2",
        )
        receipt_bytes = (self.output_dir / "registry-run-receipt.json").read_bytes()
        replayed = runner._finish_registered_execution(registry, binding, self.output_path)
        self.assertEqual(replayed, receipt)
        self.assertEqual((self.output_dir / "registry-run-receipt.json").read_bytes(), receipt_bytes)
        self.assertTrue((self.output_dir / "registry-run-receipt.json").exists())

        # A valid receipt bundle alone is not enough: without its append-only
        # artifact-commit event, a current execution cannot become successful.
        event_prefix = registry._read_events()[:2]
        registry.events_path.write_bytes(
            b"".join(runner.canonicalize(event) + b"\\n" for event in event_prefix)
        )
        with self.assertRaisesRegex(Exception, "artifact commit event"):
            registry.finish_trial(
                experiment_id=binding["experiment_id"],
                attempt_id=binding["attempt_id"],
                terminal_status="succeeded",
                result_sha256=receipt["run_manifest_sha256"],
                artifact_sha256=receipt["model_artifacts_sha256"],
                execution_id=binding["execution_context"]["execution_id"],
                storage_receipts_sha256=receipt["storage_receipts_sha256"],
                actor=binding["execution_context"]["actor"],
            )

    def test_manifest_and_every_score_row_carry_content_addressed_binding(self):
        registry, binding = self.start_binding()
        target_rows = self.rows[runner.MIN_TRAIN:]
        target_hash = runner.hashlib.sha256(
            runner.canonicalize({
                "targets": [
                    {"target_draw_id": row["draw_id"], "target_draw_date": row["draw_date"]}
                    for row in target_rows
                ]
            })
        ).hexdigest()
        self.assertEqual(binding["trial_config"]["target_manifest_sha256"], target_hash)

        def zone_result(zone):
            m, k, number_key = (
                (35, 5, "front_numbers") if zone == "front" else (12, 2, "back_numbers")
            )
            records = []
            for offset, target in enumerate(target_rows):
                training_count = runner.MIN_TRAIN + offset
                fit_statuses = {
                    "candidate": "line_search_failed",
                    "expanding": "converged",
                    "ewma": "converged",
                }
                exact_scores = {
                    "uniform": 1.0,
                    "expanding": 1.1,
                    "ewma": 1.2,
                    "exponential_family": 1.3,
                }
                model_artifacts = {}
                if zone == "front" and offset == 0:
                    from lottery.subset_model.rolling_origin_ledger import _model_identity
                    family, _, feature_schema = _model_identity(
                        "front", "expanding", 35, 5, ["sum"], ["sum"], [], [0.0], [1.0]
                    )
                    feature_schema_hash = "sha256:" + runner.hashlib.sha256(
                        runner.canonicalize(feature_schema)
                    ).hexdigest()
                    model_configuration = {
                        "model_family": "conditional_poisson",
                        "baseline": "expanding",
                        "zone": "front",
                        "population_size": 35,
                        "selection_size": 5,
                        "alpha": 100.0,
                        "half_life": None,
                        "weighting": "expanding",
                        "feature_schema_hash": feature_schema_hash,
                    }
                    model_artifacts["expanding"] = runner._create_fit_failure_artifact(
                        model_family=family,
                        zone="front",
                        population_size=35,
                        selection_size=5,
                        snapshot_digest=self.snapshot_digest,
                        training_rows=self.rows[:training_count],
                        code_revision=CHECKED_OUT_SHA,
                        feature_schema=feature_schema,
                        model_configuration=model_configuration,
                        status="line_search_failed",
                        reason="simulated test failure",
                        objective=None,
                        gradient_inf_norm=None,
                        iterations=0,
                        optimizer="conditional_poisson_calibration_lbfgs_strong_wolfe_v2",
                        regularization_lambda=None,
                        rng_algorithm="conditional_poisson_backward_dp_with_injected_rng_v1",
                    )
                    fit_statuses["expanding"] = "line_search_failed"
                    exact_scores["expanding"] = None
                records.append({
                    "target_draw_id": target["draw_id"],
                    "target_draw_date": target["draw_date"],
                    "training_count": training_count,
                    "training_first_draw_id": self.rows[0]["draw_id"],
                    "training_last_draw_id": self.rows[training_count - 1]["draw_id"],
                    "training_cutoff_draw_id": self.rows[training_count - 1]["draw_id"],
                    "training_dates_strictly_before_target": True,
                    "observed_subset": target[number_key],
                    "fit_statuses": fit_statuses,
                    "exact_set_nll": exact_scores,
                    "model_artifacts": model_artifacts,
                })
            return {
                "population_size": m,
                "selection_size": k,
                "active_feature_names": ["sum"],
                "candidate_feature_names": ["sum"],
                "zero_variance_features": [],
                "uniform_feature_means": [0.0],
                "uniform_feature_standard_deviations": [1.0],
                "target_records": records,
            }

        result = {
            "code_commit": CHECKED_OUT_SHA,
            "snapshot_sha256": self.snapshot_digest,
            "snapshot_trust_status": "manifest_complete_not_officially_authenticated",
            "snapshot_source_commit": "b" * 40,
            "bootstrap": {
                "replicates": 1000,
                "block_length": 50,
                "seed": 20261118,
                "seeds_by_zone_and_comparison": {
                    "front": {"uniform": 20261118, "expanding": 20261119, "ewma": 20261120},
                    "back": {"uniform": 20261119, "expanding": 20261120, "ewma": 20261121},
                },
            },
            "front": zone_result("front"),
            "back": zone_result("back"),
        }
        runner.write_immutable_outputs(
            result, self.rows,
            Path("data/processed/draws-20261118.jsonl"),
            self.output_path,
            experiment_binding=binding,
        )
        manifest = json.loads((self.output_dir / "run_manifest.json").read_text(encoding="utf-8"))
        ledger_first = json.loads((self.output_dir / "target-score-ledger.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(manifest["experiment_id"], binding["experiment_id"])
        self.assertEqual(manifest["legacy_experiment_label"], "LOT055-OPT-DIAG-20261120")
        self.assertEqual(manifest["experiment_binding"]["trial_id"], binding["trial_id"])
        self.assertEqual(manifest["experiment_binding"]["execution_id"], binding["execution_context"]["execution_id"])
        self.assertFalse(manifest["experiment_binding"]["approval_required"])
        self.assertEqual(manifest["experiment_binding"]["approval_disposition"], "not_required_exploratory")
        manifest_body = dict(manifest)
        supplied_manifest_hash = manifest_body.pop("manifest_sha256")
        expected_manifest_hash = "sha256:" + runner.hashlib.sha256(
            runner.canonicalize(manifest_body)
        ).hexdigest()
        self.assertEqual(supplied_manifest_hash, expected_manifest_hash)
        provenance_raw = (self.output_dir / "model-artifact-provenance.jsonl").read_bytes()
        self.assertEqual(
            manifest["output_files"]["model-artifact-provenance.jsonl"]["sha256"],
            runner.hashlib.sha256(provenance_raw).hexdigest(),
        )
        self.assertEqual(
            manifest["output_files"]["target-score-ledger.jsonl"]["schema_version"],
            "lottery.target-score-ledger/v1",
        )
        self.assertEqual(
            manifest["output_files"]["model-artifacts.jsonl"]["schema_version"],
            "lottery.subset-probability-model/v1",
        )
        self.assertEqual(
            manifest["output_files"]["model-artifact-provenance.jsonl"]["schema_version"],
            "lottery.model-artifact-provenance/v1",
        )
        self.assertEqual(ledger_first["experiment_id"], binding["experiment_id"])
        self.assertEqual(ledger_first["trial_id"], binding["trial_id"])
        self.assertEqual(ledger_first["execution_id"], binding["execution_context"]["execution_id"])
        self.assertFalse(ledger_first["approval_required"])
        self.assertEqual(ledger_first["approval_disposition"], "not_required_exploratory")
        provenance_lines = (self.output_dir / "model-artifact-provenance.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertEqual(len(provenance_lines), 1)
        provenance = json.loads(provenance_lines[0])
        self.assertEqual(provenance["experiment_id"], binding["experiment_id"])
        self.assertEqual(provenance["trial_id"], binding["trial_id"])
        self.assertEqual(provenance["execution_id"], binding["execution_context"]["execution_id"])
        self.assertFalse(provenance["approval_required"])
        self.assertEqual(provenance["approval_disposition"], "not_required_exploratory")
        self.assertEqual(
            provenance["legacy_child_registration_comment_url"],
            "https://github.com/Be90nia/Lottery/issues/27#issuecomment-7028060751",
        )
        self.assertEqual(
            provenance["legacy_child_registration_comment_sha256"],
            "161a14dc087702780917ec020685f6c85f696e7f90f607d1ede9959abc8cb8c2",
        )

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
