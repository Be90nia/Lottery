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
        ledger_row = {"record_type": "target", "target_draw_id": "26131"}
        ledger_row["record_sha256"] = sha(canonicalize(ledger_row))
        ledger_raw = canonicalize(ledger_row) + b"\n"
        artifact_raw = b'{"artifact_id":"sha256:' + b"a" * 64 + b'"}\n'
        manifest = {
            "status": "complete_with_explicit_failures",
            "confirmatory_eligible": False,
            "snapshot_sha256": "9f4cc51b76fd258dd056e0b86f675192d3d9a41c2901f771cab778c65ec2b6aa",
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
                "target_score_ledger": {
                    "sha256": sha(ledger_raw), "byte_length": len(ledger_raw), "record_count": 1,
                },
                "model_artifacts": {
                    "sha256": sha(artifact_raw), "byte_length": len(artifact_raw), "record_count": 1,
                },
            },
            "scientific_result": {
                "status": "complete_with_explicit_failures",
                "snapshot_sha256": manifest["snapshot_sha256"],
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

    def test_archive_tampering_fails_before_historical_import(self):
        evidence, archive_raw = self.build_archive()
        tampered = archive_raw + b"tampered"
        with self.assertRaisesRegex(ValueError, "byte length"):
            importer._verify_archive(evidence, tampered)


if __name__ == "__main__":
    unittest.main()
