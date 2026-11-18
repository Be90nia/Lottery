import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.reconcile import ReconciliationError, parse_external_csv, reconcile_draw_sets


class SourceReconciliationTests(unittest.TestCase):
    def test_bom_and_sorted_numbers(self):
        rows = parse_external_csv(
            "\ufeffissue,date,front,back,source\n"
            "07001,2007-05-30,22 24 29 31 35,04 11,official\n"
        )
        self.assertEqual(rows["07001"]["front_numbers"], [22, 24, 29, 31, 35])
        self.assertEqual(rows["07001"]["back_numbers"], [4, 11])

    def test_invalid_draw_rejected(self):
        with self.assertRaises(ReconciliationError):
            parse_external_csv("issue,date,front,back\n1,2026-01-01,1 1 2 3 4,1 2\n")

    def test_reconciliation_reports_mismatch_and_extension(self):
        legacy = [{
            "draw_id": "07001", "draw_date": "2007-05-30",
            "front_numbers": [22, 24, 29, 31, 35], "back_numbers": [4, 11],
        }]
        external = {
            "07001": {
                "draw_date": "2007-05-30",
                "front_numbers": [22, 24, 29, 31, 35],
                "back_numbers": [4, 11],
            },
            "07002": {
                "draw_date": "2007-06-02",
                "front_numbers": [15, 22, 31, 34, 35],
                "back_numbers": [5, 12],
            },
        }
        report = reconcile_draw_sets(legacy, external)
        self.assertEqual(report["overlap_records"], 1)
        self.assertEqual(report["mismatch_count"], 0)
        self.assertEqual(report["external_only_count"], 1)


if __name__ == "__main__":
    unittest.main()
