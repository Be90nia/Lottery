import hashlib
import json
import sys
import tempfile
from dataclasses import asdict
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.ingest import Draw, IngestionError, _add_draw, _parse_page, _snapshot, fetch_history, ingest_snapshot_directory
from lottery.validate import validate_records


class ParsePageTests(unittest.TestCase):
    def payload(self, result="01 02 03 04 05 01 02", order=None):
        row = {
            "lotteryDrawNum": "26131",
            "lotteryDrawTime": "2026-11-16",
            "lotteryDrawResult": result,
            "lotteryEquipmentCount": 2,
        }
        if order is not None:
            row["lotteryUnsortDrawresult"] = order
        return json.dumps({"value": {"list": [row]}}).encode()

    def test_valid_record_is_normalized(self):
        rows = _parse_page(self.payload(), 1, "sha256:test")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].draw_id, "26131")
        self.assertEqual(rows[0].front_numbers, [1, 2, 3, 4, 5])
        self.assertEqual(rows[0].back_numbers, [1, 2])
        self.assertEqual(rows[0].source_equipment_count, 2)
        self.assertIsNone(rows[0].source_unsort_drawresult)

    def test_draw_order_is_preserved_by_zone(self):
        rows = _parse_page(self.payload(order="03 01 05 02 04 02 01"), 1, "x")
        self.assertEqual(rows[0].front_draw_order, [3, 1, 5, 2, 4])
        self.assertEqual(rows[0].back_draw_order, [2, 1])
        self.assertEqual(rows[0].source_unsort_drawresult, "03 01 05 02 04 02 01")
        self.assertEqual(rows[0].source_equipment_count, 2)

    def test_source_metadata_survives_json_roundtrip_and_dataset_validation(self):
        rows = _parse_page(self.payload(order="03 01 05 02 04 02 01"), 1, "sha256:fixture")
        encoded = json.dumps(asdict(rows[0]), ensure_ascii=False)
        restored = json.loads(encoded)
        report = validate_records([restored])
        self.assertEqual(report["records"], 1)
        self.assertEqual(restored["source_unsort_drawresult"], "03 01 05 02 04 02 01")
        self.assertEqual(restored["source_equipment_count"], 2)

    def test_non_string_draw_order_rejected(self):
        row = json.loads(self.payload().decode())
        row["value"]["list"][0]["lotteryUnsortDrawresult"] = [1, 2, 3, 4, 5, 1, 2]
        with self.assertRaises(IngestionError):
            _parse_page(json.dumps(row).encode(), 1, "x")

    def test_invalid_draw_order_rejected(self):
        with self.assertRaises(IngestionError):
            _parse_page(self.payload(order="03 01 05 02 06 02 01"), 1, "x")

    def test_duplicate_number_rejected(self):
        with self.assertRaises(IngestionError):
            _parse_page(self.payload("01 01 03 04 05 01 02"), 1, "x")

    def test_out_of_range_number_rejected(self):
        with self.assertRaises(IngestionError):
            _parse_page(self.payload("01 02 03 04 36 01 02"), 1, "x")

    def test_wrong_number_count_rejected(self):
        with self.assertRaises(IngestionError):
            _parse_page(self.payload("01 02 03 04 05 01"), 1, "x")

    def test_invalid_json_rejected(self):
        with self.assertRaises(IngestionError):
            _parse_page(b"not json", 1, "x")

    def test_source_failure_envelope_rejected(self):
        payload = json.dumps({"success": False, "errorMessage": "blocked", "value": {"list": []}}).encode()
        with self.assertRaises(IngestionError):
            _parse_page(payload, 1, "x")

    def test_nonzero_error_code_rejected(self):
        payload = json.dumps({"errorCode": "E001", "value": {"list": []}}).encode()
        with self.assertRaises(IngestionError):
            _parse_page(payload, 1, "x")



    def test_offline_snapshot_import_writes_verified_output_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_dir = root / "raw"
            raw_dir.mkdir()
            raw = self.payload(order="03 01 05 02 04 02 01")
            digest = hashlib.sha256(raw).hexdigest()
            name = f"page-00001-{digest[:12]}.json"
            (raw_dir / name).write_bytes(raw)
            (raw_dir / f"page-00001-{digest[:12]}.manifest.json").write_text(
                json.dumps({
                    "source": "Sporttery public historical draw API",
                    "url": "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry?gameNo=85",
                    "retrieved_at": "2026-11-18T00:00:00+00:00",
                    "http_status": 200,
                    "sha256": digest,
                    "raw_file": name,
                    "page_no": 1,
                    "run_id": "a" * 32,
                }),
                encoding="utf-8",
            )
            output = root / "processed" / "draws.jsonl"
            report = ingest_snapshot_directory(raw_dir, output, require_manifests=True)
            self.assertTrue(report["provenance_complete"])
            self.assertIs(report["source_completeness_verified"], False)
            self.assertIsNone(report["completeness_evidence"])
            self.assertEqual(report["validation"]["records"], 1)
            self.assertEqual(report["trust_status"], "manifest_complete_not_officially_authenticated")
            row = json.loads(output.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["source_unsort_drawresult"], "03 01 05 02 04 02 01")
            self.assertTrue(output.with_suffix(".jsonl.manifest.json").exists())

    def test_offline_snapshot_import_rejects_tampered_manifest_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_dir = root / "raw"
            raw_dir.mkdir()
            raw = self.payload()
            name = "page-00001.json"
            (raw_dir / name).write_bytes(raw)
            (raw_dir / "page-00001.manifest.json").write_text(
                json.dumps({"sha256": "0" * 64, "raw_file": name}),
                encoding="utf-8",
            )
            with self.assertRaises(IngestionError):
                ingest_snapshot_directory(raw_dir, root / "draws.jsonl")


    def test_strict_offline_import_rejects_non_official_manifest_url(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_dir = root / "raw"
            raw_dir.mkdir()
            raw = self.payload()
            digest = hashlib.sha256(raw).hexdigest()
            name = "page-00001.json"
            (raw_dir / name).write_bytes(raw)
            (raw_dir / "page-00001.manifest.json").write_text(
                json.dumps({
                    "source": "Sporttery public historical draw API",
                    "url": "https://example.com/gateway/lottery/getHistoryPageListV1.qry?gameNo=85",
                    "retrieved_at": "2026-11-18T00:00:00+00:00",
                    "http_status": 200,
                    "sha256": digest,
                    "raw_file": name,
                }),
                encoding="utf-8",
            )
            with self.assertRaises(IngestionError):
                ingest_snapshot_directory(raw_dir, root / "strict.jsonl", require_manifests=True)

    def test_offline_snapshot_import_without_sidecar_remains_unverified(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_dir = root / "raw"
            raw_dir.mkdir()
            (raw_dir / "page-00001.json").write_bytes(self.payload())
            report = ingest_snapshot_directory(raw_dir, root / "draws.jsonl")
            self.assertFalse(report["provenance_complete"])
            self.assertEqual(report["trust_status"], "candidate_unverified")
            with self.assertRaises(IngestionError):
                ingest_snapshot_directory(raw_dir, root / "strict.jsonl", require_manifests=True)

    def test_identical_duplicate_across_pages_is_accepted(self):
        rows = {}
        first = Draw("26131", "2026-11-16", [1, 2, 3, 4, 5], [1, 2], "page-a")
        repeated = Draw("26131", "2026-11-16", [1, 2, 3, 4, 5], [1, 2], "page-b")
        _add_draw(rows, first)
        _add_draw(rows, repeated)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows["26131"].source_id, "page-a")

    def test_conflicting_equipment_metadata_across_pages_is_rejected(self):
        rows = {}
        first = Draw("26131", "2026-11-16", [1, 2, 3, 4, 5], [1, 2], "page-a",
                     source_equipment_count=1)
        conflict = Draw("26131", "2026-11-16", [1, 2, 3, 4, 5], [1, 2], "page-b",
                        source_equipment_count=3)
        _add_draw(rows, first)
        with self.assertRaises(IngestionError):
            _add_draw(rows, conflict)

    def test_conflicting_duplicate_across_pages_is_rejected(self):
        rows = {}
        first = Draw("26131", "2026-11-16", [1, 2, 3, 4, 5], [1, 2], "page-a")
        conflict = Draw("26131", "2026-11-16", [1, 2, 3, 4, 6], [1, 2], "page-b")
        _add_draw(rows, first)
        with self.assertRaises(IngestionError):
            _add_draw(rows, conflict)



class FetchPaginationSafetyTests(unittest.TestCase):
    def payload(self, rows):
        return json.dumps({"success": True, "value": {"list": rows}}).encode("utf-8")

    def row(self, draw_id="26131"):
        return {
            "lotteryDrawNum": draw_id,
            "lotteryDrawTime": "2026-11-16",
            "lotteryDrawResult": "01 02 03 04 05 01 02",
        }

    def test_full_page_at_max_pages_fails_closed_without_publishing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "processed" / "draws.jsonl"
            raw_dir = root / "raw"
            with patch("lottery.ingest._fetch_page", return_value=(self.payload([self.row()]), 200, "application/json")):
                with self.assertRaisesRegex(IngestionError, "potentially truncated"):
                    fetch_history(output, raw_dir, page_size=1, max_pages=1, delay_seconds=0)
            self.assertFalse(output.exists())
            self.assertEqual(len([path for path in raw_dir.rglob("*.json") if not path.name.endswith(".manifest.json")]), 1)

    def test_empty_first_page_fails_closed_without_publishing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "processed" / "draws.jsonl"
            with patch("lottery.ingest._fetch_page", return_value=(self.payload([]), 200, "application/json")):
                with self.assertRaisesRegex(IngestionError, "no draws"):
                    fetch_history(output, root / "raw", page_size=100, delay_seconds=0)
            self.assertFalse(output.exists())

    def test_short_terminal_page_is_explicitly_unverified_for_completeness(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "processed" / "draws.jsonl"
            with patch("lottery.ingest._fetch_page", return_value=(self.payload([self.row()]), 200, "application/json")):
                result = fetch_history(output, root / "raw", page_size=2, delay_seconds=0)
            self.assertEqual(result["records"], 1)
            self.assertEqual(result["pagination_end_reason"], "short_page")
            self.assertFalse(result["source_completeness_verified"])
            self.assertEqual(result["trust_status"], "manifest_complete_not_officially_authenticated")
            self.assertEqual(Path(result["raw_dir"]).parent, root / "raw")
            self.assertTrue(Path(result["raw_dir"]).is_dir())


    def test_repeated_fetch_runs_get_separate_snapshot_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_parent = root / "raw"
            payload = self.payload([self.row()])
            with patch("lottery.ingest._fetch_page", return_value=(payload, 200, "application/json")):
                first = fetch_history(root / "one.jsonl", raw_parent, page_size=2, delay_seconds=0)
                second = fetch_history(root / "two.jsonl", raw_parent, page_size=2, delay_seconds=0)
            self.assertNotEqual(first["raw_dir"], second["raw_dir"])
            self.assertEqual(len(list(Path(first["raw_dir"]).glob("*.manifest.json"))), 1)
            self.assertEqual(len(list(Path(second["raw_dir"]).glob("*.manifest.json"))), 1)

    def test_import_rejects_snapshots_from_mixed_fetch_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_dir = root / "raw"
            raw_dir.mkdir()
            url = "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry?gameNo=85&pageNo=1"
            _snapshot(self.payload([self.row("26131")]), 1, 200, "application/json", raw_dir, url, "a" * 32)
            _snapshot(self.payload([self.row("26132")]), 2, 200, "application/json", raw_dir, url.replace("pageNo=1", "pageNo=2"), "b" * 32)
            with self.assertRaisesRegex(IngestionError, "one contiguous page sequence from one fetch run"):
                ingest_snapshot_directory(raw_dir, root / "out.jsonl", require_manifests=True)

class ImmutableSnapshotTests(unittest.TestCase):
    def test_identical_snapshot_does_not_rewrite_original_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            raw_dir = Path(temp)
            raw = json.dumps({"success": True, "value": {"list": []}}).encode()
            url = "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry?gameNo=85&pageNo=1"
            _snapshot(raw, 1, 200, "application/json", raw_dir, url, "run-one")
            manifest = next(raw_dir.glob("*.manifest.json"))
            original = manifest.read_bytes()
            _snapshot(raw, 1, 200, "application/json", raw_dir, url, "run-two")
            self.assertEqual(manifest.read_bytes(), original)
            self.assertEqual(len([path for path in raw_dir.glob("*.json") if not path.name.endswith(".manifest.json")]), 1)

    def test_corrupted_content_addressed_snapshot_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            raw_dir = Path(temp)
            raw = b'{"success":true,"value":{"list":[]}}'
            url = "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry?gameNo=85&pageNo=1"
            _snapshot(raw, 1, 200, "application/json", raw_dir, url, "run-one")
            body = next(path for path in raw_dir.glob("*.json") if not path.name.endswith(".manifest.json"))
            body.write_bytes(b"tampered")
            with self.assertRaisesRegex(IngestionError, "corruption"):
                _snapshot(raw, 1, 200, "application/json", raw_dir, url, "run-two")

if __name__ == "__main__":
    unittest.main()
