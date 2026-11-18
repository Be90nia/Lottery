import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.baseline import analyze_frequency_baseline


def draw(front, back):
    return {
        "front_numbers": front,
        "back_numbers": back,
    }


class FrequencyBaselineTests(unittest.TestCase):
    def test_reproducible_for_same_seed(self):
        rows = [
            draw([1, 2, 3, 4, 5], [1, 2]),
            draw([6, 7, 8, 9, 10], [3, 4]),
        ]
        first = analyze_frequency_baseline(rows, simulations=9, seed=17)
        second = analyze_frequency_baseline(rows, simulations=9, seed=17)
        self.assertEqual(first, second)

    def test_frequency_counts_preserve_draw_structure(self):
        rows = [
            draw([1, 2, 3, 4, 5], [1, 2]),
            draw([1, 6, 7, 8, 9], [1, 3]),
        ]
        report = analyze_frequency_baseline(rows, simulations=5, seed=1)
        self.assertEqual(sum(x["count"] for x in report["front_frequency"]), 10)
        self.assertEqual(sum(x["count"] for x in report["back_frequency"]), 4)
        self.assertEqual(report["draw_count"], 2)

    def test_invalid_simulation_count_rejected(self):
        with self.assertRaises(ValueError):
            analyze_frequency_baseline([draw([1, 2, 3, 4, 5], [1, 2])], simulations=0)


if __name__ == "__main__":
    unittest.main()
