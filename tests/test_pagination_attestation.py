import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.append_only import reconcile_append_only
from lottery.ingest import IngestionError, fetch_history, ingest_snapshot_directory


def source_item(draw_id, draw_date):
    return {
        "lotteryDrawNum": draw_id,
        "lotteryDrawTime": draw_date,
        "lotteryDrawResult": "01 02 03 04 05 01 02",
        "lotteryUnsortDrawresult": None,
        "lotteryEquipmentCount": None,
    }


def source_page(items, total=3, total_pages=2):
    return json.dumps({
        "success": True,
        "value": {"list": items, "total": total, "totalPage": total_pages},
    }, sort_keys=True).encode("utf-8")


def source_url(page_no, page_size=2):
    return (
        "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
        f"?gameNo=85&provinceId=0&pageSize={page_size}&isVerify=1&pageNo={page_no}"
    )


def canonical_row(draw_id, draw_date, source_id="sha256:prior"):
    return {
        "draw_id": draw_id,
        "draw_date": draw_date,
        "front_numbers": [1, 2, 3, 4, 5],
        "back_numbers": [1, 2],
        "source_id": source_id,
        "front_draw_order": None,
        "back_draw_order": None,
        "source_unsort_drawresult": None,
        "source_equipment_count": None,
    }


class SourcePaginationAttestationTests(unittest.TestCase):
    def fetch_two_pages(self, root, *, page2_total=3, page2_count=1):
        raw_parent = root / "raw"
        output = root / "fetch.jsonl"
        first = source_page([
            source_item("26001", "2026-01-01"),
            source_item("26002", "2026-01-02"),
        ])
        second_items = (
            [source_item("26003", "2026-01-03")]
            if page2_count == 1
            else []
        )
        second = source_page(second_items, total=page2_total, total_pages=2)
        responses = [
            (first, 200, "application/json", source_url(1)),
            (second, 200, "application/json", source_url(2)),
        ]
        with patch("lottery.ingest._fetch_page", side_effect=responses) as fetch:
            result = fetch_history(output, raw_parent, page_size=2, delay_seconds=0)
        return result, fetch

    def test_fetch_stops_at_source_total_pages_and_reports_reconciled_totals(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result, fetch = self.fetch_two_pages(root)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(result["pagination_end_reason"], "source_total_pages")
            self.assertTrue(result["source_completeness_verified"])
            self.assertEqual(result["source_total_records"], 3)
            self.assertEqual(result["source_total_pages"], 2)
            self.assertEqual(result["records"], 3)

    def test_strict_import_emits_raw_page_backed_pagination_attestation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result, _ = self.fetch_two_pages(root)
            candidate = root / "candidate.jsonl"
            manifest = ingest_snapshot_directory(
                Path(result["raw_dir"]), candidate, require_manifests=True
            )
            self.assertTrue(manifest["source_completeness_verified"])
            attestation = manifest["source_completeness_attestation"]
            self.assertEqual(attestation["schema"], "sporttery-pagination-attestation-v1")
            self.assertEqual(attestation["source_total_records"], 3)
            self.assertEqual(attestation["source_total_pages"], 2)
            self.assertEqual(attestation["page_size"], 2)
            self.assertEqual(attestation["total_records_pointer"], "/value/total")
            self.assertEqual(attestation["total_pages_pointer"], "/value/totalPage")
            self.assertEqual([page["page_no"] for page in attestation["pages"]], [1, 2])
            self.assertEqual(
                manifest["output_sha256"],
                hashlib.sha256(candidate.read_bytes()).hexdigest(),
            )

    def test_import_attestation_is_accepted_by_append_only_publication_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result, _ = self.fetch_two_pages(root)
            candidate = root / "candidate.jsonl"
            manifest_path = candidate.with_suffix(candidate.suffix + ".manifest.json")
            snapshots_dir = Path(result["raw_dir"])
            manifest = ingest_snapshot_directory(
                snapshots_dir, candidate, require_manifests=True
            )
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            current = root / "current.jsonl"
            current.write_text(
                "".join(
                    json.dumps(canonical_row(draw_id, date)) + "\n"
                    for draw_id, date in (
                        ("26001", "2026-01-01"),
                        ("26002", "2026-01-02"),
                    )
                ),
                encoding="utf-8",
            )
            published = root / "published.jsonl"
            receipt_path = root / "publication-receipt.json"
            receipt = reconcile_append_only(
                current, candidate, manifest_path, published, receipt_path, snapshots_dir
            )
            self.assertEqual(receipt["status"], "appended")
            self.assertEqual(receipt["appended_draw_ids"], ["26003"])
            self.assertTrue(published.exists())

    def test_page_record_count_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_parent = root / "raw"
            output = root / "fetch.jsonl"
            first = source_page([source_item("26001", "2026-01-01")])
            with patch("lottery.ingest._fetch_page", return_value=(
                first, 200, "application/json", source_url(1)
            )):
                with self.assertRaisesRegex(IngestionError, "record count does not match"):
                    fetch_history(output, raw_parent, page_size=2, delay_seconds=0)
            self.assertFalse(output.exists())

    def test_changed_source_totals_between_pages_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_parent = root / "raw"
            output = root / "fetch.jsonl"
            first = source_page([
                source_item("26001", "2026-01-01"),
                source_item("26002", "2026-01-02"),
            ])
            second = source_page(
                [source_item("26003", "2026-01-03")],
                total=4,
                total_pages=2,
            )
            with patch("lottery.ingest._fetch_page", side_effect=[
                (first, 200, "application/json", source_url(1)),
                (second, 200, "application/json", source_url(2)),
            ]):
                with self.assertRaisesRegex(IngestionError, "totals changed between pages"):
                    fetch_history(output, raw_parent, page_size=2, delay_seconds=0)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
