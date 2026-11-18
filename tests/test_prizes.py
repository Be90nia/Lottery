import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.prizes import (
    PrizeDataError, audit_prize_rows, classify_prize_label,
    reconcile_additional_awards,
)


def prize(draw_id="26131", label="五等奖", amount="10", winners=2, total="20"):
    return {
        "draw_id": draw_id,
        "tier_label_original": label,
        "amount_yuan_original": amount,
        "winner_count": winners,
        "total_yuan_original": total,
        "source_id": "legacy:test",
    }


class PrizeAuditTests(unittest.TestCase):
    def test_exact_decimal_accounting(self):
        report = audit_prize_rows([prize(amount="7.5", winners=2, total="15.0")])
        self.assertEqual(report["amount_times_count_mismatch_rows_excluding_promotions"], 0)

    def test_promotion_total_is_separate_from_unit_amount_math(self):
        report = audit_prize_rows([
            prize(label="五等奖派奖", amount="0", winners=10, total="150")
        ])
        self.assertEqual(report["promotion_rows"], 1)
        self.assertEqual(report["promotion_zero_amount_positive_total_rows"], 1)
        self.assertEqual(report["promotion_total_yuan"], "150")
        self.assertEqual(report["amount_times_count_mismatch_rows_excluding_promotions"], 0)

    def test_promotion_coverage_is_grouped_without_treating_zero_as_zero_payout(self):
        rows = [
            prize("23039", "三等奖派奖", "0", 99, "615000"),
            prize("23039", "四等奖派奖", "0", 323, "598500"),
            prize("24030", "三等奖派奖", "1250", 10, "12500"),
        ]
        report = audit_prize_rows(rows)
        self.assertEqual(report["promotion_rows"], 3)
        self.assertEqual(report["promotion_draw_ids"], 2)
        self.assertEqual(report["promotion_zero_amount_positive_total_rows"], 2)
        self.assertEqual(report["promotion_zero_amount_positive_total_by_label"], {
            "三等奖派奖": 1, "四等奖派奖": 1,
        })
        self.assertEqual(report["promotion_summary_by_draw_id_prefix"]["23"], {
            "rows": 2, "draw_ids": 1, "zero_amount_positive_total_rows": 2,
            "total_yuan": "1213500",
        })
        self.assertEqual(report["promotion_summary_by_draw_id_prefix"]["24"], {
            "rows": 1, "draw_ids": 1, "zero_amount_positive_total_rows": 0,
            "total_yuan": "12500",
        })

    def test_ruleset_and_label_distributions_are_reported(self):
        row = prize(draw_id="07001")
        report = audit_prize_rows([row])
        self.assertEqual(report["ruleset_row_counts"], {"dlt_2007_from_07001": 1})
        self.assertEqual(report["tier_label_counts"], {"五等奖": 1})
        self.assertEqual(report["unsupported_ruleset_rows"], 0)

    def test_unknown_historical_rules_are_not_silently_assigned(self):
        row = prize(draw_id="00001")
        report = audit_prize_rows([row])
        self.assertEqual(report["unsupported_ruleset_rows"], 1)
        self.assertEqual(report["ruleset_row_counts"], {})

    def test_all_25_candidate_label_forms_are_classified(self):
        base = ["一等奖", "二等奖", "三等奖", "四等奖", "五等奖",
                "六等奖", "七等奖", "八等奖", "九等奖"]
        additional = [f"{tier}(追加)" for tier in
                      ("一等奖", "二等奖", "三等奖", "四等奖", "五等奖")]
        promotion = [
            "一等奖基本派奖", "一等奖追加派奖", "二等奖基本派奖", "二等奖追加派奖",
            "七等奖派奖", "三等奖派奖", "九等奖派奖", "五等奖派奖",
            "八等奖派奖", "六等奖派奖", "四等奖派奖",
        ]
        self.assertEqual(len(base + additional + promotion), 25)
        for label in base:
            self.assertEqual(classify_prize_label(label)["award_kind"], "base_award")
        for label in additional:
            self.assertEqual(classify_prize_label(label)["award_kind"], "additional_bet")
        for label in promotion:
            self.assertEqual(classify_prize_label(label)["award_kind"], "promotion_overlay")
        self.assertEqual(classify_prize_label("附加玩法一等奖")["award_kind"], "side_game")
        self.assertEqual(classify_prize_label("unknown")["award_kind"], "unknown")

    def test_2007_additional_multiplier_and_forbidden_fixed_additional(self):
        rows = [
            prize("07001", "一等奖", "5000000", 2, "10000000"),
            prize("07001", "一等奖(追加)", "3000000", 1, "3000000"),
            prize("07001", "二等奖", "136558", 8, "1092464"),
            prize("07001", "二等奖(追加)", "81934", 1, "81934"),
            prize("07001", "三等奖", "24466", 9, "220194"),
            prize("07001", "三等奖(追加)", "14679", 1, "14679"),
            prize("07001", "四等奖", "3000", 50, "150000"),
            prize("07001", "四等奖(追加)", "3000", 50, "150000"),
        ]
        report = reconcile_additional_awards(rows)
        self.assertEqual(report["additional_pairs_checked"], 3)
        self.assertEqual(report["additional_pair_mismatches"], 0)
        self.assertEqual(report["unexpected_additional_row_count"], 1)
        self.assertEqual(report["unexpected_additional_rows"][0]["tier"], 4)

    def test_official_2007_regional_result_additional_rows(self):
        rows = [
            prize("07006", "一等奖", "5000000", 1, "5000000"),
            prize("07006", "一等奖(追加)", "3000000", 1, "3000000"),
            prize("07006", "二等奖", "461113", 3, "1383339"),
            prize("07006", "二等奖(追加)", "0", 0, "0"),
            prize("07006", "三等奖", "20343", 13, "264459"),
            prize("07006", "三等奖(追加)", "12205", 1, "12205"),
            prize("07006", "四等奖", "3000", 42, "126000"),
            prize("07006", "五等奖", "500", 814, "407000"),
        ]
        report = reconcile_additional_awards(rows)
        self.assertEqual(report["additional_pairs_checked"], 2)
        self.assertEqual(report["additional_pair_mismatches"], 0)
        self.assertEqual(report["unexpected_additional_row_count"], 0)

    def test_2009_and_2014_fixed_additional_multipliers(self):
        rows = [
            prize("09121", "四等奖", "3000", 10, "30000"),
            prize("09121", "四等奖(追加)", "1500", 2, "3000"),
            prize("14052", "四等奖", "200", 10, "2000"),
            prize("14052", "四等奖(追加)", "100", 2, "200"),
            prize("14052", "五等奖", "10", 20, "200"),
            prize("14052", "五等奖(追加)", "5", 3, "15"),
        ]
        report = reconcile_additional_awards(rows)
        self.assertEqual(report["additional_pairs_checked"], 3)
        self.assertEqual(report["additional_pair_mismatches"], 0)
        self.assertEqual(report["unexpected_additional_row_count"], 0)

    def test_later_fixed_tier_additional_is_flagged(self):
        rows = [
            prize("19019", "三等奖", "10000", 10, "100000"),
            prize("19019", "三等奖(追加)", "8000", 1, "8000"),
        ]
        report = reconcile_additional_awards(rows)
        self.assertEqual(report["unexpected_additional_row_count"], 1)

    def test_duplicate_draw_tier_rejected(self):
        with self.assertRaises(PrizeDataError):
            audit_prize_rows([prize(), prize()])

    def test_negative_amount_rejected(self):
        with self.assertRaises(PrizeDataError):
            audit_prize_rows([prize(amount="-1", winners=1, total="-1")])


if __name__ == "__main__":
    unittest.main()
