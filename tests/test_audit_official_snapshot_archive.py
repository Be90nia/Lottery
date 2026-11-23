import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.ingest import PARSER_VERSION, _parse_page
from scripts.audit_official_snapshot_archive import AuditError, audit_archive


class OfficialSnapshotArchiveAuditTests(unittest.TestCase):
    def build_fixture(self, root: Path):
        payload = {
            "success": True,
            "errorCode": "0",
            "value": {
                "list": [{
                    "lotteryDrawNum": "26131",
                    "lotteryDrawTime": "2026-11-16",
                    "lotteryDrawResult": "02 11 18 19 29 04 07",
                    "lotteryUnsortDrawresult": "18 11 29 02 19 04 07",
                    "lotteryEquipmentCount": 2,
                }]
            },
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        page_name = f"page-00001-{digest[:12]}.json"
        sidecar_name = f"page-00001-{digest[:12]}.manifest.json"
        sidecar = {
            "source": "Sporttery public historical draw API",
            "url": "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry?gameNo=85&pageNo=1",
            "retrieved_at": "2026-11-18T03:58:58+00:00",
            "http_status": 200,
            "content_type": "application/json;charset=UTF-8",
            "sha256": digest,
            "parser_version": PARSER_VERSION,
            "run_id": "fixture-run",
            "page_no": 1,
            "raw_file": page_name,
        }
        collection = {"total_pages": 1, "total_records": 1}
        archive_path = root / "incoming.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("dlt_official_raw/", b"")
            archive.writestr("dlt_official_raw/collection-fixture.manifest.json", json.dumps(collection))
            archive.writestr("dlt_official_raw/" + page_name, raw)
            archive.writestr("dlt_official_raw/" + sidecar_name, json.dumps(sidecar))

        parsed = _parse_page(raw, 1, "sha256:" + digest)
        processed_bytes = (
            json.dumps(asdict(parsed[0]), ensure_ascii=False) + "\n"
        ).encode("utf-8")
        processed_path = root / "draws.jsonl"
        processed_path.write_bytes(processed_bytes)
        manifest = {
            "snapshot_count": 1,
            "snapshot_sha256": [digest],
            "snapshots": [{
                "sha256": digest,
                "provenance_complete": True,
                "records": 1,
            }],
            "trust_status": "manifest_complete_not_officially_authenticated",
            "output_sha256": hashlib.sha256(processed_bytes).hexdigest(),
            "validation": {"records": 1},
        }
        manifest_path = root / "draws.jsonl.manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return archive_path, processed_path, manifest_path, sidecar

    def test_archive_and_processed_bytes_reproduce_exactly(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive, processed, manifest, _ = self.build_fixture(root)
            report = audit_archive(
                archive, processed, manifest, expected_pages=1, expected_records=1
            )
            self.assertTrue(report["processed_rebuild_byte_identical"])
            self.assertTrue(report["raw_snapshot_hashes_match_processed_manifest"])
            self.assertEqual(report["raw_records"], 1)
            self.assertEqual(report["trust_status"], "manifest_complete_not_officially_authenticated")

    def test_archive_rejects_sidecar_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive, processed, manifest, sidecar = self.build_fixture(root)
            sidecar["sha256"] = "0" * 64
            # Rebuild the ZIP with the tampered sidecar while leaving raw bytes unchanged.
            with zipfile.ZipFile(archive, "r") as source:
                members = {name: source.read(name) for name in source.namelist()}
            sidecar_name = next(name for name in members if name.endswith(".manifest.json") and "page-" in name)
            members[sidecar_name] = json.dumps(sidecar).encode("utf-8")
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as target:
                for name, value in members.items():
                    target.writestr(name, value)
            with self.assertRaisesRegex(AuditError, "sidecar identity/hash/status mismatch"):
                audit_archive(archive, processed, manifest, expected_pages=1, expected_records=1)

    def test_archive_rejects_non_official_endpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive, processed, manifest, sidecar = self.build_fixture(root)
            sidecar["url"] = sidecar["url"].replace("webapi.sporttery.cn", "example.com")
            with zipfile.ZipFile(archive, "r") as source:
                members = {name: source.read(name) for name in source.namelist()}
            sidecar_name = next(name for name in members if name.endswith(".manifest.json") and "page-" in name)
            members[sidecar_name] = json.dumps(sidecar).encode("utf-8")
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as target:
                for name, value in members.items():
                    target.writestr(name, value)
            with self.assertRaisesRegex(AuditError, "non-canonical official endpoint metadata"):
                audit_archive(archive, processed, manifest, expected_pages=1, expected_records=1)


if __name__ == "__main__":
    unittest.main()
