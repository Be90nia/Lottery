import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.rules import (
    RULES_2007, RULES_2009, RULES_2013, RULES_2014, RULES_2019, RULES_2026, UnsupportedRulesetError,
    ruleset_for_draw,
)


class VersionedPrizeRulesTests(unittest.TestCase):
    def test_all_evidenced_effective_draw_boundaries(self):
        self.assertIs(ruleset_for_draw("07001"), RULES_2007)
        self.assertIs(ruleset_for_draw("09120"), RULES_2007)
        self.assertIs(ruleset_for_draw("09121"), RULES_2009)
        self.assertIs(ruleset_for_draw("13144"), RULES_2009)
        self.assertIs(ruleset_for_draw("13145"), RULES_2013)
        self.assertIs(ruleset_for_draw("14051"), RULES_2013)
        self.assertIs(ruleset_for_draw("14052"), RULES_2014)
        self.assertIs(ruleset_for_draw("19018"), RULES_2014)
        self.assertIs(ruleset_for_draw("19019"), RULES_2019)
        self.assertIs(ruleset_for_draw("26013"), RULES_2019)
        self.assertIs(ruleset_for_draw("26014"), RULES_2026)
        self.assertEqual(RULES_2007.effective_from_date, "2007-05-30")
        self.assertEqual(RULES_2009.effective_from_date, "2009-10-14")
        self.assertEqual(RULES_2013.effective_from_date, "2013-12-09")
        self.assertEqual(RULES_2014.effective_from_date, "2014-05-05")
        self.assertEqual(RULES_2019.effective_from_date, "2019-02-20")
        self.assertEqual(RULES_2026.effective_from_date, "2026-02-02")

    def test_pre_launch_history_fails_closed(self):
        with self.assertRaises(UnsupportedRulesetError):
            ruleset_for_draw("07000")

    def test_2007_launch_rules_and_additional_scope(self):
        expected = {
            (5, 2): 1, (5, 1): 2, (5, 0): 3, (4, 2): 4,
            (4, 1): 5, (4, 0): 6, (3, 2): 6, (3, 1): 7,
            (2, 2): 7, (3, 0): 8, (1, 2): 8, (2, 1): 8, (0, 2): 8,
        }
        for hits, tier in expected.items():
            with self.subTest(hits=hits):
                self.assertEqual(RULES_2007.tier_for_hits(*hits), tier)
        self.assertEqual(RULES_2007.fixed_prize_yuan(4, "0"), Decimal("3000"))
        self.assertEqual(RULES_2007.fixed_prize_yuan(5, "0"), Decimal("500"))
        self.assertEqual(RULES_2007.fixed_prize_yuan(6, "0"), Decimal("200"))
        self.assertEqual(RULES_2007.fixed_prize_yuan(7, "0"), Decimal("10"))
        self.assertEqual(RULES_2007.fixed_prize_yuan(8, "0"), Decimal("5"))
        self.assertEqual(RULES_2007.additional_award_multiplier(1), Decimal("0.6"))
        self.assertEqual(RULES_2007.additional_award_multiplier(3), Decimal("0.6"))
        self.assertEqual(RULES_2007.additional_award_multiplier(4), Decimal("0"))

    def test_2009_and_2013_eight_tier_patterns_and_additional_rules(self):
        expected = {
            (5, 2): 1, (5, 1): 2, (5, 0): 3, (4, 2): 4,
            (4, 1): 5, (4, 0): 6, (3, 2): 6, (3, 1): 7,
            (2, 2): 7, (3, 0): 8, (1, 2): 8, (2, 1): 8, (0, 2): 8,
        }
        for rules in (RULES_2009, RULES_2013):
            for hits, tier in expected.items():
                with self.subTest(rules=rules.ruleset_id, hits=hits):
                    self.assertEqual(rules.tier_for_hits(*hits), tier)
            self.assertEqual(rules.fixed_prize_yuan(4, "0"), Decimal("3000"))
            self.assertEqual(rules.fixed_prize_yuan(5, "0"), Decimal("600"))
            self.assertEqual(rules.fixed_prize_yuan(6, "0"), Decimal("100"))
            self.assertEqual(rules.fixed_prize_yuan(7, "0"), Decimal("10"))
            self.assertEqual(rules.fixed_prize_yuan(8, "0"), Decimal("5"))
            self.assertEqual(rules.additional_award_multiplier(1), Decimal("0.6"))
            self.assertEqual(rules.additional_award_multiplier(4), Decimal("0.5"))
            self.assertEqual(rules.additional_award_multiplier(8), Decimal("0"))

    def test_2014_six_tier_patterns(self):
        expected = {
            (5, 2): 1, (5, 1): 2, (5, 0): 3, (4, 2): 3,
            (4, 1): 4, (3, 2): 4, (4, 0): 5, (3, 1): 5,
            (2, 2): 5, (3, 0): 6, (1, 2): 6, (2, 1): 6, (0, 2): 6,
        }
        for hits, tier in expected.items():
            with self.subTest(hits=hits):
                self.assertEqual(RULES_2014.tier_for_hits(*hits), tier)
        self.assertEqual(RULES_2014.fixed_prize_yuan(4, "0"), Decimal("200"))
        self.assertEqual(RULES_2014.fixed_prize_yuan(5, "0"), Decimal("10"))
        self.assertEqual(RULES_2014.fixed_prize_yuan(6, "0"), Decimal("5"))
        self.assertEqual(RULES_2014.additional_award_multiplier(1), Decimal("0.6"))
        self.assertEqual(RULES_2014.additional_award_multiplier(4), Decimal("0.5"))

    def test_2019_nine_tier_patterns_and_additional_rule(self):
        expected = {
            (5, 2): 1, (5, 1): 2, (5, 0): 3, (4, 2): 4,
            (4, 1): 5, (3, 2): 6, (4, 0): 7, (3, 1): 8,
            (2, 2): 8, (3, 0): 9, (1, 2): 9, (2, 1): 9, (0, 2): 9,
        }
        for hits, tier in expected.items():
            with self.subTest(hits=hits):
                self.assertEqual(RULES_2019.tier_for_hits(*hits), tier)
        self.assertEqual(RULES_2019.fixed_prize_yuan(3, "0"), Decimal("10000"))
        self.assertEqual(RULES_2019.fixed_prize_yuan(9, "0"), Decimal("5"))
        self.assertEqual(RULES_2019.additional_award_multiplier(1), Decimal("0.8"))
        self.assertEqual(RULES_2019.additional_award_multiplier(3), Decimal("0"))

    def test_2026_seven_tier_patterns(self):
        expected = {
            (5, 2): 1, (5, 1): 2, (5, 0): 3, (4, 2): 3,
            (4, 1): 4, (4, 0): 5, (3, 2): 5, (3, 1): 6,
            (2, 2): 6, (3, 0): 7, (2, 1): 7, (1, 2): 7, (0, 2): 7,
        }
        for hits, tier in expected.items():
            with self.subTest(hits=hits):
                self.assertEqual(RULES_2026.tier_for_hits(*hits), tier)
        self.assertIsNone(RULES_2026.tier_for_hits(0, 0))

    def test_2026_fixed_prize_threshold_is_decimal_safe(self):
        self.assertEqual(RULES_2026.fixed_prize_yuan(3, "799999999"), Decimal("5000"))
        self.assertEqual(RULES_2026.fixed_prize_yuan(3, "800000000"), Decimal("6666"))
        self.assertEqual(RULES_2026.fixed_prize_yuan(4, "800000000"), Decimal("380"))
        self.assertEqual(RULES_2026.fixed_prize_yuan(7, "800000000"), Decimal("7"))

    def test_floating_awards_are_not_calculated(self):
        self.assertIsNone(RULES_2026.fixed_prize_yuan(1, "800000000"))
        self.assertEqual(RULES_2026.additional_award_multiplier(1), Decimal("0.8"))
        self.assertEqual(RULES_2026.additional_award_multiplier(2), Decimal("0.8"))
        self.assertEqual(RULES_2026.additional_award_multiplier(3), Decimal("0"))
        self.assertEqual(RULES_2026.floating_total_cap_per_tier_yuan, Decimal("100000000"))

    def test_invalid_draw_ids_hits_and_tiers_rejected(self):
        for value in ("", "26A14", " 26014", "2601"):
            with self.subTest(draw_id=value):
                with self.assertRaises(ValueError):
                    ruleset_for_draw(value)
        with self.assertRaises(ValueError):
            RULES_2026.tier_for_hits(6, 0)
        with self.assertRaises(ValueError):
            RULES_2026.fixed_prize_yuan(8, "0")
        with self.assertRaises(ValueError):
            RULES_2026.fixed_prize_yuan(3, "not-a-number")
        with self.assertRaises(ValueError):
            RULES_2026.fixed_prize_yuan(3, "-1")

    def test_ruleset_serialization_is_explicit(self):
        serialized = RULES_2026.as_dict()
        self.assertEqual(serialized["ruleset_id"], "dlt_2026_from_26014")
        self.assertEqual(len(serialized["tiers"]), 7)
        self.assertIn("source_urls", serialized)
        self.assertIn("floating_award_notes", serialized)


if __name__ == "__main__":
    unittest.main()
