import hashlib
import io
import json
import unittest
import zipfile
from unittest.mock import patch

from lottery.subset_model.artifact import canonicalize
from scripts import import_g3_historical_execution as importer


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class HistoricalG3ArchiveVerificationTests(unittest.TestCase):
    def build_archive(self):
        ledger_row = {"record_type": "target", "zone": "front", "target_draw_id": "26131", "model_name": "uniform", "terminal_status": "scored", "training_dates_strictly_before_target": True, "training_last_draw_id": "26130", "training_row_count": 300, "artifact_id": None, "diagnostic_ref": None}
        ledger_row["record_sha256"] = sha(canonicalize(ledger_row))
        ledger_raw = canonicalize(ledger_row) + b"\n"
        artifact_raw = b'{"artifact_id":"sha256:' + b"a" * 64 + b'"}\n'
        manifest = {
            "status": "complete_with_explicit_failures",
            "confirmatory_eligible": False,
            "snapshot": {"sha256": "9f4cc51b76fd258dd056e0b86f675192d3d9a41c2901f771cab778c65ec2b6aa"},
            "expected_target_record_count": 1,
            "actual_target_record_count": 1,
            "model_artifact_count": 1,
            "terminal_status_counts": {
                "scored": 1, "fit_failed": 0, "artifact_invalid": 0,
                "probability_invalid": 0, "runner_error": 0,
            },
            "target_manifest": {
                "first_target_draw_id": "26131",
                "last_target_draw_id": "26131",
                "target_count_per_zone": 1,
            },
            "models": [{"model_name": "uniform", "zone": "front"}],
            "output_files": {
                "target-score-ledger.jsonl": {"sha256": sha(ledger_raw), "bytes": len(ledger_raw)},
                "model-artifacts.jsonl": {"sha256": sha(artifact_raw), "bytes": len(artifact_raw)},
            },
        }
        manifest["manifest_sha256"] = "sha256:" + sha(canonicalize(manifest))
        manifest_raw = canonicalize(manifest) + b"\n"
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("run_manifest.json", manifest_raw)
            archive.writestr("target-score-ledger.jsonl", ledger_raw)
            archive.writestr("model-artifacts.jsonl", artifact_raw)
        zip_raw = buffer.getvalue()
        evidence = {
            "artifact": {"size_in_bytes": len(zip_raw), "digest": "sha256:" + sha(zip_raw)},
            "artifact_contents": {
                "run_manifest_sha256": manifest["manifest_sha256"].removeprefix("sha256:"),
                "run_manifest_file": {"sha256": sha(manifest_raw), "byte_length": len(manifest_raw)},
                "target_score_ledger": {
                    "sha256": sha(ledger_raw), "byte_length": len(ledger_raw), "record_count": 1,
                },
                "model_artifacts": {
                    "sha256": sha(artifact_raw), "byte_length": len(artifact_raw), "record_count": 1,
                },
            },
            "scientific_result": {
                "status": "complete_with_explicit_failures",
                "snapshot_sha256": manifest["snapshot"]["sha256"],
                "target_count_per_zone": 1,
                "first_target_draw_id": "26131",
                "last_target_draw_id": "26131",
                "zones": ["front"],
                "terminal_counts": manifest["terminal_status_counts"],
            },
        }
        return evidence, zip_raw

    def test_archive_checks_zip_digest_manifest_ledger_and_artifacts(self):
        evidence, archive_raw = self.build_archive()
        with patch.object(importer, "verify_artifact", return_value={"artifact_id": "sha256:" + "a" * 64}):
            manifest, ledger, artifacts = importer._verify_archive(evidence, archive_raw)
        self.assertEqual(manifest["status"], "complete_with_explicit_failures")
        self.assertTrue(ledger)
        self.assertTrue(artifacts)

    def test_live_github_run_job_step_and_artifact_metadata_are_pinned(self):
        from pathlib import Path
        evidence = json.loads(
            Path("docs/G3_HISTORICAL_EXECUTION_EVIDENCE_2026-11-20.json").read_text(encoding="utf-8")
        )
        expected = evidence["run"]
        run = {
            "id": expected["id"],
            "run_attempt": expected["run_attempt"],
            "run_number": expected["run_number"],
            "workflow_id": expected["workflow_id"],
            "name": expected["workflow_name"],
            "path": expected["workflow_path"] + "@" + expected["ref"],
            "head_branch": expected["head_branch"],
            "head_sha": expected["head_sha"],
            "event": expected["event"],
            "status": expected["status"],
            "conclusion": expected["conclusion"],
            "run_started_at": expected["run_started_at_utc"],
            "html_url": expected["run_url"],
            "repository": {"id": 1461523125},
            "actor": {"login": expected["actor"]},
        }
        expected_job = evidence["job"]
        job = {
            "id": expected_job["id"],
            "name": expected_job["name"],
            "status": expected_job["status"],
            "conclusion": expected_job["conclusion"],
            "started_at": expected_job["started_at_utc"],
            "completed_at": expected_job["completed_at_utc"],
            "run_attempt": expected["run_attempt"],
            "head_sha": expected["head_sha"],
            "steps": [{
                "name": "Run full frozen 2,649-target exact-subset evaluation",
                "started_at": expected_job["evaluator_step_started_at_utc"],
                "completed_at": expected_job["evaluator_step_completed_at_utc"],
                "conclusion": "success",
            }],
        }
        expected_artifact = evidence["artifact"]
        artifact = {
            "id": expected_artifact["id"],
            "name": expected_artifact["name"],
            "size_in_bytes": expected_artifact["size_in_bytes"],
            "digest": expected_artifact["digest"],
            "created_at": expected_artifact["created_at_utc"],
            "expires_at": expected_artifact["expires_at_utc"],
            "expired": False,
            "workflow_run": {
                "id": expected["id"],
                "repository_id": 1461523125,
                "head_sha": expected["head_sha"],
            },
        }
        with patch.object(
            importer, "_api_json",
            side_effect=[run, {"jobs": [job]}, {"artifacts": [artifact]}],
        ):
            verified_run, verified_artifact = importer._verify_github_sources(evidence, "test-token")
        self.assertEqual(verified_run["id"], expected["id"])
        self.assertEqual(verified_artifact["id"], expected_artifact["id"])


    def test_evidence_cannot_choose_a_different_workflow_or_repository(self):
        from pathlib import Path
        evidence = json.loads(
            Path("docs/G3_HISTORICAL_EXECUTION_EVIDENCE_2026-11-20.json").read_text(encoding="utf-8")
        )
        evidence["run"]["workflow_id"] += 1
        with patch.object(importer, "_api_json") as api:
            with self.assertRaisesRegex(ValueError, "workflow identity"):
                importer._verify_github_sources(evidence, "test-token")
            api.assert_not_called()

    def test_archive_tampering_fails_before_historical_import(self):
        evidence, archive_raw = self.build_archive()
        tampered = archive_raw + b"tampered"
        with self.assertRaisesRegex(ValueError, "byte length"):
            importer._verify_archive(evidence, tampered)


if __name__ == "__main__":
    unittest.main()
