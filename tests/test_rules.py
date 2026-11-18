import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.rules import LEGACY_RULES, RULES_2026, ruleset_for_draw


class VersionedPrizeRulesTests(unittest.TestCase):
    def test_effective_draw_boundary(self):
        self.assertIs(ruleset_for_draw("26013"), LEGACY_RULES)
        self.assertIs(ruleset_for_draw("26014"), RULES_2026)
        self.assertEqual(RULES_2026.effective_from_date, "2026-02-02")
        self.assertEqual(LEGACY_RULES.effective_through_draw_id, "26013")

    def test_legacy_nine_tier_patterns(self):
        expected = {
            (5, 2): 1, (5, 1): 2, (5, 0): 3, (4, 2): 4,
            (4, 1): 5, (3, 2): 6, (4, 0): 7, (3, 1): 8,
            (2, 2): 8, (3, 0): 9, (1, 2): 9, (2, 1): 9, (0, 2): 9,
        }
        for hits, tier in expected.items():
            with self.subTest(hits=hits):
                self.assertEqual(LEGACY_RULES.tier_for_hits(*hits), tier)
        self.assertIsNone(LEGACY_RULES.tier_for_hits(0, 0))

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

    def test_fixed_prize_threshold_is_decimal_safe(self):
        self.assertEqual(RULES_2026.fixed_prize_yuan(3, "799999999"), Decimal("5000"))
        self.assertEqual(RULES_2026.fixed_prize_yuan(3, "800000000"), Decimal("6666"))
        self.assertEqual(RULES_2026.fixed_prize_yuan(4, "800000000"), Decimal("380"))
        self.assertEqual(RULES_2026.fixed_prize_yuan(7, "800000000"), Decimal("7"))
        self.assertEqual(LEGACY_RULES.fixed_prize_yuan(3, "0"), Decimal("10000"))
        self.assertEqual(LEGACY_RULES.fixed_prize_yuan(9, "0"), Decimal("5"))

    def test_floating_awards_are_not_calculated(self):
        self.assertIsNone(RULES_2026.fixed_prize_yuan(1, "800000000"))
        self.assertEqual(RULES_2026.additional_award_multiplier(1), Decimal("0.8"))
        self.assertEqual(RULES_2026.additional_award_multiplier(2), Decimal("0.8"))
        self.assertEqual(RULES_2026.additional_award_multiplier(3), Decimal("0"))

    def test_invalid_draw_ids_hits_and_tiers_rejected(self):
        for value in ("", "26A14", " 26014"):
            with self.subTest(draw_id=value):
                with self.assertRaises(ValueError):
                    ruleset_for_draw(value)
        with self.assertRaises(ValueError):
            RULES_2026.tier_for_hits(6, 0)
        with self.assertRaises(ValueError):
            RULES_2026.fixed_prize_yuan(8, "0")

    def test_ruleset_serialization_is_explicit(self):
        serialized = RULES_2026.as_dict()
        self.assertEqual(serialized["ruleset_id"], "dlt_2026_from_26014")
        self.assertEqual(len(serialized["tiers"]), 7)
        self.assertIn("source_urls", serialized)


if __name__ == "__main__":
    unittest.main()
