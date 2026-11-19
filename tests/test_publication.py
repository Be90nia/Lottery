import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.publication import PublicationError, reconcile_append_only
from lottery.ingest import _snapshot


def draw(draw_id, date, source="sha256:" + "a" * 64, front=None):
    return {
        "draw_id": draw_id, "draw_date": date,
        "front_numbers": front or [1, 2, 3, 4, 5], "back_numbers": [1, 2],
        "source_id": source, "front_draw_order": None, "back_draw_order": None,
        "source_unsort_drawresult": None, "source_equipment_count": None,
    }


class AppendOnlyPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.current = self.root / "current.jsonl"
        self.candidate = self.root / "candidate.jsonl"
        self.manifest = self.root / "candidate.manifest.json"
        self.output = self.root / "next.jsonl"
        self.receipt = self.root / "receipt.json"
        self.snapshots_dir = self.root / "snapshots"
        self.old = [draw("26001", "2026-01-01"), draw("26002", "2026-01-02")]
        self.new = [*self.old, draw("26003", "2026-01-03", source="sha256:" + "b" * 64)]
        self.write_rows(self.current, self.old)
        self.write_candidate(self.new)

    def tearDown(self):
        self.temp.cleanup()

    def write_rows(self, path, rows):
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def write_candidate(self, rows):
        self.write_rows(self.candidate, rows)
        raw_rows = []
        for row in rows:
            numbers = row["front_numbers"] + row["back_numbers"]
            raw_rows.append({
                "lotteryDrawNum": row["draw_id"],
                "lotteryDrawTime": row["draw_date"],
                "lotteryDrawResult": " ".join(str(number) for number in numbers),
                "lotteryUnsortDrawresult": None,
                "lotteryEquipmentCount": row.get("source_equipment_count"),
            })
        raw = json.dumps({"success": True, "value": {"list": raw_rows}}).encode("utf-8")
        url = ("https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
               "?gameNo=85&provinceId=0&pageSize=100&isVerify=1&pageNo=1")
        run_id = "c" * 32
        digest = _snapshot(raw, 1, 200, "application/json", self.snapshots_dir, url, run_id)
        raw_name = next(path.name for path in self.snapshots_dir.glob("*.json")
                        if not path.name.endswith(".manifest.json")
                        and path.name.endswith(digest[:12] + ".json"))
        sidecar_name = next(path.name for path in self.snapshots_dir.glob("*.manifest.json")
                            if digest[:12] in path.name)
        from lottery.validate import validate_jsonl
        summary = validate_jsonl(self.candidate)
        manifest = {
            "output_sha256": hashlib.sha256(self.candidate.read_bytes()).hexdigest(),
            "validation": summary,
            "provenance_complete": True,
            "trust_status": "manifest_complete_not_officially_authenticated",
            "snapshot_count": 1,
            "run_id": run_id,
            "snapshots": [{
                "sha256": digest, "raw_file": raw_name, "sidecar_manifest": sidecar_name,
                "page_no": 1, "records": len(rows), "bytes": len(raw),
                "run_id": run_id, "provenance_complete": True,
            }],
            "source_completeness_verified": True,
            "completeness_evidence": {
                "method": "official_pagination_metadata",
                "reported_total_records": len(rows),
                "reported_total_pages": 1,
                "page_size": 100,
            },
        }
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
    def run_gate(self):
        return reconcile_append_only(
            self.current, self.candidate, self.manifest, self.output, self.receipt,
            self.snapshots_dir
        )

    def test_tampered_raw_page_bytes_rejected(self):
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        raw_path = self.snapshots_dir / manifest["snapshots"][0]["raw_file"]
        raw_path.write_bytes(raw_path.read_bytes() + b" ")
        with self.assertRaisesRegex(PublicationError, "hash/size mismatch"):
            self.run_gate()
        self.assertFalse(self.output.exists())

    def test_sidecar_url_mismatch_rejected(self):
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        sidecar_path = self.snapshots_dir / manifest["snapshots"][0]["sidecar_manifest"]
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        sidecar["url"] = "https://evil.example/collect"
        sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
        with self.assertRaisesRegex(PublicationError, "sidecar does not match|approved page request"):
            self.run_gate()

    def test_candidate_must_reconstruct_from_raw_page(self):
        changed = [*self.new[:-1], draw("26003", "2026-01-03", source="sha256:" + "b" * 64, front=[6, 7, 8, 9, 10])]
        self.write_rows(self.candidate, changed)
        from lottery.validate import validate_jsonl
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        manifest["output_sha256"] = hashlib.sha256(self.candidate.read_bytes()).hexdigest()
        manifest["validation"] = validate_jsonl(self.candidate)
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(PublicationError, "does not match archived raw snapshot"):
            self.run_gate()

    def test_append_preserves_existing_rows_and_adds_only_new_draws(self):
        receipt = self.run_gate()
        self.assertEqual(receipt["status"], "append_candidate_created")
        self.assertEqual(receipt["added_draw_ids"], ["26003"])
        output = [json.loads(x) for x in self.output.read_text().splitlines()]
        self.assertEqual(output[:2], self.old)
        self.assertEqual(output[2]["draw_id"], "26003")
        self.assertFalse(receipt["canonical_dataset_modified"])
        self.assertFalse(receipt["promotion_authorized"])

    def test_no_new_draw_is_idempotent_and_does_not_write_output(self):
        self.write_candidate(self.old)
        receipt = self.run_gate()
        self.assertEqual(receipt["status"], "no_new_draws")
        self.assertFalse(receipt["output_written"])
        self.assertFalse(self.output.exists())

    def test_missing_historical_row_rejected(self):
        self.write_candidate([self.old[0]])
        with self.assertRaisesRegex(PublicationError, "not a full snapshot"):
            self.run_gate()

    def test_historical_correction_rejected(self):
        changed = [dict(row) for row in self.new]
        changed[0]["front_numbers"] = [2, 3, 4, 5, 6]
        self.write_candidate(changed)
        with self.assertRaisesRegex(PublicationError, "historical correction"):
            self.run_gate()

    def test_same_day_new_draw_rejected(self):
        changed = [*self.old, draw("26003", "2026-01-02")]
        self.write_candidate(changed)
        with self.assertRaisesRegex(PublicationError, "strictly later"):
            self.run_gate()

    def test_manifest_tampering_rejected(self):
        data = json.loads(self.manifest.read_text())
        data["output_sha256"] = "0" * 64
        self.manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(PublicationError, "output_sha256"):
            self.run_gate()

    def test_incomplete_provenance_rejected(self):
        data = json.loads(self.manifest.read_text())
        data["provenance_complete"] = False
        self.manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(PublicationError, "incomplete"):
            self.run_gate()

    def test_output_collision_rejected(self):
        self.output.write_text("do not overwrite")
        with self.assertRaisesRegex(PublicationError, "already exists"):
            self.run_gate()
        self.assertEqual(self.output.read_text(), "do not overwrite")


    def test_skipped_new_draw_id_rejected(self):
        changed = [*self.old, draw("26004", "2026-01-04")]
        self.write_candidate(changed)
        with self.assertRaisesRegex(PublicationError, "sequence has a gap"):
            self.run_gate()

    def test_draw_id_year_rollover_is_accepted(self):
        old = [draw("26131", "2026-12-28"), draw("26132", "2026-12-30")]
        candidate = [*old, draw("27001", "2027-01-02")]
        self.write_rows(self.current, old)
        self.write_candidate(candidate)
        receipt = self.run_gate()
        self.assertEqual(receipt["added_draw_ids"], ["27001"])

    def test_existing_output_manifest_is_never_overwritten(self):
        sidecar = self.output.with_suffix(self.output.suffix + ".manifest.json")
        sidecar.write_text("prior manifest", encoding="utf-8")
        with self.assertRaisesRegex(PublicationError, "already exists"):
            self.run_gate()
        self.assertFalse(self.output.exists())
        self.assertEqual(sidecar.read_text(encoding="utf-8"), "prior manifest")

    def test_existing_receipt_is_never_overwritten(self):
        self.receipt.write_text("prior receipt", encoding="utf-8")
        with self.assertRaisesRegex(PublicationError, "receipt_path already exists"):
            self.run_gate()
        self.assertEqual(self.receipt.read_text(encoding="utf-8"), "prior receipt")

    def test_unverified_source_completeness_rejected(self):
        data = json.loads(self.manifest.read_text())
        data["source_completeness_verified"] = False
        data["completeness_evidence"] = None
        self.manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(PublicationError, "completeness is unverified"):
            self.run_gate()

    def test_page_inventory_gap_rejected(self):
        data = json.loads(self.manifest.read_text())
        data["snapshots"][0]["page_no"] = 2
        self.manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(PublicationError, "page inventory"):
            self.run_gate()

    def test_reported_total_record_mismatch_rejected(self):
        data = json.loads(self.manifest.read_text())
        data["completeness_evidence"]["reported_total_records"] += 1
        self.manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(PublicationError, "pagination totals"):
            self.run_gate()

if __name__ == "__main__":
    unittest.main()
