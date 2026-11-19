import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.publication import PublicationError, reconcile_append_only


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
        raw = self.candidate.read_bytes()
        from lottery.validate import validate_jsonl
        summary = validate_jsonl(self.candidate)
        manifest = {
            "output_sha256": hashlib.sha256(raw).hexdigest(),
            "validation": summary,
            "provenance_complete": True,
            "trust_status": "manifest_complete_not_officially_authenticated",
            "snapshot_count": 1,
            "snapshots": [{"sha256": "c" * 64, "provenance_complete": True}],
        }
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")

    def run_gate(self):
        return reconcile_append_only(
            self.current, self.candidate, self.manifest, self.output, self.receipt
        )

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


if __name__ == "__main__":
    unittest.main()
