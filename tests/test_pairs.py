import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.pairs import analyze_pair_cooccurrence, exact_binomial_two_sided_pvalue


def draw(front, back):
    return {"front_numbers": front, "back_numbers": back}


class PairCooccurrenceTests(unittest.TestCase):
    def test_exact_binomial_two_sided_values(self):
        self.assertAlmostEqual(exact_binomial_two_sided_pvalue(1, 1, 0.2), 0.4)
        self.assertEqual(exact_binomial_two_sided_pvalue(1, 0, 0.2), 1.0)

    def test_pair_counts_and_family_size(self):
        rows = [
            draw([1, 2, 3, 4, 5], [1, 2]),
            draw([1, 2, 6, 7, 8], [1, 3]),
        ]
        report = analyze_pair_cooccurrence(rows)
        self.assertEqual(report["draw_count"], 2)
        self.assertEqual(report["hypotheses_tested"], 661)
        self.assertEqual(len(report["front_pairs"]), 595)
        self.assertEqual(len(report["back_pairs"]), 66)
        front = {tuple(item["pair"]): item["count"] for item in report["front_pairs"]}
        back = {tuple(item["pair"]): item["count"] for item in report["back_pairs"]}
        self.assertEqual(front[(1, 2)], 2)
        self.assertEqual(front[(1, 3)], 1)
        self.assertEqual(back[(1, 2)], 1)
        self.assertEqual(back[(1, 3)], 1)
        self.assertEqual(sum(item["count"] for item in report["front_pairs"]), 20)
        self.assertEqual(sum(item["count"] for item in report["back_pairs"]), 2)

    def test_holm_adjustment_detects_planted_extreme_fixture(self):
        rows = [draw([1, 2, 3, 4, 5], [1, 2]) for _ in range(20)]
        report = analyze_pair_cooccurrence(rows)
        front = {tuple(item["pair"]): item for item in report["front_pairs"]}
        back = {tuple(item["pair"]): item for item in report["back_pairs"]}
        self.assertTrue(front[(1, 2)]["significant_at_0_05_after_holm"])
        self.assertTrue(back[(1, 2)]["significant_at_0_05_after_holm"])
        self.assertGreater(report["significant_pair_count_after_holm"], 0)

    def test_reproducible_and_reports_all_pairs(self):
        rows = [draw([1, 6, 11, 16, 21], [2, 8]) for _ in range(8)]
        self.assertEqual(analyze_pair_cooccurrence(rows), analyze_pair_cooccurrence(rows))

    def test_rejects_empty_or_malformed_rows(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            analyze_pair_cooccurrence([])
        with self.assertRaisesRegex(ValueError, "front_numbers"):
            analyze_pair_cooccurrence([draw([1, 1, 2, 3, 4], [1, 2])])
        with self.assertRaisesRegex(ValueError, "back_numbers"):
            analyze_pair_cooccurrence([draw([1, 2, 3, 4, 5], [1, 1])])

    def test_rejects_invalid_binomial_parameters(self):
        with self.assertRaises(ValueError):
            exact_binomial_two_sided_pvalue(0, 0, 0.2)
        with self.assertRaises(ValueError):
            exact_binomial_two_sided_pvalue(10, 2, 1.0)


if __name__ == "__main__":
    unittest.main()
