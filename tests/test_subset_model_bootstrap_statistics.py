import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_subset_rolling_origin import _holm_adjust, _moving_block_bootstrap


class ExactSubsetBootstrapTests(unittest.TestCase):
    def test_null_centered_block_bootstrap_detects_negative_mean(self):
        result = _moving_block_bootstrap([-1.0] * 100, seed=7)
        self.assertEqual(result["observed_mean_delta_candidate_minus_reference"], -1.0)
        self.assertLess(result["ci_95_upper"], 0.0)
        self.assertEqual(result["one_sided_null_centered_p_value"], 1 / 1001)
        self.assertIn("null-centered", result["method"])

    def test_null_centered_block_bootstrap_does_not_call_positive_mean_a_win(self):
        result = _moving_block_bootstrap([1.0] * 100, seed=7)
        self.assertGreaterEqual(result["ci_95_lower"], 0.0)
        self.assertEqual(result["one_sided_null_centered_p_value"], 1.0)

    def test_holm_step_down_adjusts_all_six_preregistered_comparisons(self):
        raw = {
            "front:uniform": 0.001,
            "front:expanding": 0.01,
            "front:ewma": 0.02,
            "back:uniform": 0.03,
            "back:expanding": 0.04,
            "back:ewma": 0.05,
        }
        adjusted = _holm_adjust(raw, family_size=6)
        self.assertEqual(adjusted["front:uniform"], 0.006)
        self.assertEqual(adjusted["front:expanding"], 0.05)
        self.assertEqual(adjusted["front:ewma"], 0.08)
        self.assertEqual(adjusted["back:uniform"], 0.09)
        self.assertEqual(adjusted["back:expanding"], 0.09)
        self.assertEqual(adjusted["back:ewma"], 0.09)

    def test_missing_or_invalid_comparison_fails_closed(self):
        self.assertEqual(_holm_adjust({"front:uniform": 0.01}, family_size=6),
                         {"front:uniform": None})
        raw = {f"comparison:{i}": 0.01 for i in range(6)}
        raw["comparison:5"] = float("nan")
        self.assertTrue(all(value is None for value in _holm_adjust(raw, family_size=6).values()))


if __name__ == "__main__":
    unittest.main()
