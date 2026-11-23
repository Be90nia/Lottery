import hashlib
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from lottery.execution_context import execution_context_from_env
from lottery.experiment_registry import EXPERIMENT_SCHEMA, ExperimentRegistry
from lottery.subset_model.artifact import canonicalize
from scripts.build_g3_evidence import (
    G3EvidenceBuildError,
    _holm,
    _legacy_label_digest,
    _read_snapshot,
    _strict_json,
    _verify_registry_binding,
)


class G3EvidenceAdapterTests(unittest.TestCase):
    def test_legacy_label_digest_is_not_a_registry_identity(self):
        manifest = {"experiment_id": "LOT055-OPT-DIAG-20261120"}
        digest = _legacy_label_digest(manifest)
        self.assertEqual(
            digest,
            "4eceab2eab2cc9cdd2961634815f5ed586ddd9f54df5496d7d2754f60039a12a",
        )
        self.assertNotEqual(digest, manifest["experiment_id"])

    def test_legacy_run_is_explicitly_unbound(self):
        binding = _verify_registry_binding(
            run_manifest={"experiment_id": "LOT055-OPT-DIAG-20261120"},
            run_manifest_raw=b"{}\\n",
            model_artifacts_raw=b"",
            registration_raw=b"{}",
            registry_root=None,
            registry_run_receipt_path=None,
            artifact_provenance_path=None,
        )
        self.assertEqual(binding["status"], "UNBOUND_LEGACY")
        self.assertIsNone(binding["registry_experiment_id"])

    def test_registry_receipt_binds_trial_execution_and_every_artifact(self):
        repository = "Be90nia/Lottery"
        workflow_path = ".github/workflows/subset-research.yml"
        commit = "a" * 40
        env = {
            "GITHUB_REPOSITORY": repository,
            "GITHUB_REPOSITORY_ID": "1461523125",
            "GITHUB_WORKFLOW_REF": f"{repository}/{workflow_path}@refs/heads/feature",
            "GITHUB_RUN_ID": "45130000000",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_JOB": "run-evaluation",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REF": "refs/heads/feature",
            "GITHUB_SHA": commit,
            "GITHUB_ACTOR": "research-operator",
        }
        execution = execution_context_from_env(
            env, checked_out_sha=commit,
            expected_repository=repository,
            expected_repository_id="1461523125",
            expected_workflow_path=workflow_path,
        )
        registration_raw = b'{"schema":"lottery.g3-preregistration/v1"}'
        trial_config = {"protocol": "LOT-055", "candidate": "diagnostic"}
        trial_id = hashlib.sha256(canonicalize(trial_config)).hexdigest()
        attempt_id = "exec-" + execution["execution_id"]
        spec = {
            "schema": EXPERIMENT_SCHEMA,
            "experiment_name": "retrospective-g3-binding-test",
            "experiment_class": "exploratory",
            "parent_experiment_id": None,
            "hypothesis": "retrospective provenance binding only",
            "model_family": "LOT055_multi_model_evaluation",
            "population_key": "pooled_equipment_blind",
            "zone": "joint",
            "training_snapshot_sha256": "a" * 64,
            "training_cutoff_draw_id": "09053",
            "target_draw_ids": ["09054"],
            "target_manifest_sha256": "b" * 64,
            "source_evidence_sha256": hashlib.sha256(registration_raw).hexdigest(),
            "feature_schema_sha256": "c" * 64,
            "trial_plan": [trial_config],
            "primary_metric": "exact_set_nll",
            "multiplicity_family": ["candidate_vs_uniform:front", "candidate_vs_uniform:back"],
            "bootstrap_replicates": 1000,
            "block_length": 50,
            "seed_commitment_sha256": "d" * 64,
            "holdout_accessed": False,
            "outcomes_observed": True,
            "population_claim": "pooled",
            "population_evidence_sha256": None,
        }
        artifact_id = "e" * 64
        model_artifacts_raw = canonicalize({"artifact_id": artifact_id}) + b"\\n"
        run_manifest = {
            "run_id": "lot055-binding-test",
            "experiment_binding": {
                "schema": "lottery.experiment-run-binding/v1",
                "experiment_id": None,
                "spec_sha256": None,
                "approval_sha256": None,
                "trial_id": trial_id,
                "registry_attempt_id": attempt_id,
                "execution_id": execution["execution_id"],
                "execution_context": execution,
            },
            "model_artifact_provenance_count": 1,
            "output_files": {},
        }
        provenance = {
            "schema": "lottery.model-artifact-provenance/v1",
            "artifact_id": artifact_id,
            "experiment_id": None,
            "trial_id": trial_id,
            "attempt_id": attempt_id,
            "execution_id": execution["execution_id"],
            "evaluation_run_id": run_manifest["run_id"],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = ExperimentRegistry(root / "registry")
            registered = registry.register_experiment(spec, actor=execution["actor"])
            experiment_id = registered["experiment_id"]
            run_manifest["experiment_binding"]["experiment_id"] = experiment_id
            run_manifest["experiment_binding"]["spec_sha256"] = experiment_id
            provenance["experiment_id"] = experiment_id
            provenance_raw = canonicalize(provenance) + b"\\n"
            run_manifest["output_files"]["model-artifact-provenance.jsonl"] = {
                "sha256": hashlib.sha256(provenance_raw).hexdigest(),
                "bytes": len(provenance_raw),
            }
            run_manifest_raw = canonicalize(run_manifest) + b"\\n"
            registry.start_trial(
                experiment_id=experiment_id,
                attempt_id=attempt_id,
                config=trial_config,
                actor=execution["actor"],
                execution_context=execution,
                expected_repository=repository,
                expected_repository_id="1461523125",
                expected_workflow_path=workflow_path,
            )
            registry.finish_trial(
                experiment_id=experiment_id,
                attempt_id=attempt_id,
                terminal_status="succeeded",
                result_sha256=hashlib.sha256(run_manifest_raw).hexdigest(),
                artifact_sha256=hashlib.sha256(model_artifacts_raw).hexdigest(),
                execution_id=execution["execution_id"],
                actor=execution["actor"],
            )
            snapshot = registry.snapshot()
            events = registry._read_events()
            receipt = {
                "schema": "lottery.experiment-run-receipt/v1",
                "experiment_id": experiment_id,
                "spec_sha256": experiment_id,
                "approval_sha256": None,
                "trial_id": trial_id,
                "attempt_id": attempt_id,
                "execution_id": execution["execution_id"],
                "evaluation_run_id": run_manifest["run_id"],
                "run_manifest_sha256": hashlib.sha256(run_manifest_raw).hexdigest(),
                "model_artifacts_sha256": hashlib.sha256(model_artifacts_raw).hexdigest(),
                "event_count": snapshot["event_count"],
                "event_chain_head_sha256": events[-1]["event_hash"],
                "terminal_status": "succeeded",
            }
            receipt_path = root / "registry-run-receipt.json"
            receipt_path.write_bytes(canonicalize(receipt) + b"\\n")
            provenance_path = root / "model-artifact-provenance.jsonl"
            provenance_path.write_bytes(provenance_raw)
            report = _verify_registry_binding(
                run_manifest=run_manifest,
                run_manifest_raw=run_manifest_raw,
                model_artifacts_raw=model_artifacts_raw,
                registration_raw=registration_raw,
                registry_root=registry.root,
                registry_run_receipt_path=receipt_path,
                artifact_provenance_path=provenance_path,
            )
            self.assertEqual(report["status"], "VERIFIED")
            self.assertEqual(report["registry_experiment_id"], experiment_id)
            self.assertEqual(report["execution_id"], execution["execution_id"])

    def test_holm_step_down_is_deterministic(self):
        adjusted = _holm({"front": 0.01, "back": 0.04})
        self.assertEqual(adjusted, {"front": 0.02, "back": 0.04})

    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaisesRegex(G3EvidenceBuildError, "duplicate JSON key"):
            _strict_json(b'{"run_id":"a","run_id":"b"}', "fixture")

    def test_snapshot_preflight_derives_strict_target_boundary(self):
        rows = []
        first = date(2007, 1, 1)
        for index in range(2949):
            if index < 300:
                draw_id = f"{7001 + index:05d}"
            else:
                draw_id = f"{9054 + ((26131 - 9054) * (index - 300) // 2648):05d}"
            rows.append({
                "draw_id": draw_id,
                "draw_date": (first + timedelta(days=index)).isoformat(),
                "front_numbers": [1, 2, 3, 4, 5],
                "back_numbers": [1, 2],
            })
        raw = b"".join(
            json.dumps(row, separators=(",", ":")).encode("utf-8") + b"\n"
            for row in rows
        )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "snapshot.jsonl"
            path.write_bytes(raw)
            actual = hashlib.sha256(raw).hexdigest()
            _, parsed = _read_snapshot(path, actual)
            self.assertEqual(len(parsed), 2949)
            self.assertEqual(parsed[300]["draw_id"], "09054")
            self.assertEqual(parsed[-1]["draw_id"], "26131")
            with self.assertRaisesRegex(G3EvidenceBuildError, "SHA-256 mismatch"):
                _read_snapshot(path, "0" * 64)


if __name__ == "__main__":
    unittest.main()
