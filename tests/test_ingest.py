import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.ingest import IngestionError, _parse_page


class ParsePageTests(unittest.TestCase):
    def payload(self, result="01 02 03 04 05 01 02"):
        return json.dumps({"value": {"list": [{
            "lotteryDrawNum": "26131",
            "lotteryDrawTime": "2026-11-16",
            "lotteryDrawResult": result,
        }]}}).encode()

    def test_valid_record_is_normalized(self):
        rows = _parse_page(self.payload(), 1, "sha256:test")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].draw_id, "26131")
        self.assertEqual(rows[0].front_numbers, [1, 2, 3, 4, 5])
        self.assertEqual(rows[0].back_numbers, [1, 2])

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


if __name__ == "__main__":
    unittest.main()
