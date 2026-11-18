import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.ingest import Draw, IngestionError, _add_draw, _parse_page


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


    def test_identical_duplicate_across_pages_is_accepted(self):
        rows = {}
        first = Draw("26131", "2026-11-16", [1, 2, 3, 4, 5], [1, 2], "page-a")
        repeated = Draw("26131", "2026-11-16", [1, 2, 3, 4, 5], [1, 2], "page-b")
        _add_draw(rows, first)
        _add_draw(rows, repeated)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows["26131"].source_id, "page-a")

    def test_conflicting_duplicate_across_pages_is_rejected(self):
        rows = {}
        first = Draw("26131", "2026-11-16", [1, 2, 3, 4, 5], [1, 2], "page-a")
        conflict = Draw("26131", "2026-11-16", [1, 2, 3, 4, 6], [1, 2], "page-b")
        _add_draw(rows, first)
        with self.assertRaises(IngestionError):
            _add_draw(rows, conflict)

if __name__ == "__main__":
    unittest.main()
