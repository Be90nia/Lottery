import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.prizes import PrizeDataError, audit_prize_rows


def prize(amount="10", winners=2, total="20"):
    return {
        "draw_id": "26131",
        "tier_label_original": "五等奖",
        "amount_yuan_original": amount,
        "winner_count": winners,
        "total_yuan_original": total,
        "source_id": "legacy:test",
    }


class PrizeAuditTests(unittest.TestCase):
    def test_exact_decimal_accounting(self):
        report = audit_prize_rows([prize("7.5", 2, "15.0")])
        self.assertEqual(report["amount_times_count_mismatch_rows"], 0)

    def test_promotion_total_mismatch_is_reported_not_rewritten(self):
        report = audit_prize_rows([prize("0", 10, "150")])
        self.assertEqual(report["zero_amount_positive_total_rows"], 1)

    def test_duplicate_draw_tier_rejected(self):
        with self.assertRaises(PrizeDataError):
            audit_prize_rows([prize(), prize()])

    def test_negative_amount_rejected(self):
        with self.assertRaises(PrizeDataError):
            audit_prize_rows([prize("-1", 1, "-1")])


if __name__ == "__main__":
    unittest.main()
