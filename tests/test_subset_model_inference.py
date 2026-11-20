import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_subset_rolling_origin import (
    BOOTSTRAP_BLOCK,
    BOOTSTRAP_REPLICATES,
    _holm_adjust,
    _moving_block_bootstrap,
)


class MovingBlockInferenceTests(unittest.TestCase):
    def test_uses_fixed_preregistered_replicate_and_block_counts(self):
        values = [((index % 17) - 8) / 10.0 for index in range(125)]
        result = _moving_block_bootstrap(values, seed=20261118)
        self.assertEqual(result["replicates"], BOOTSTRAP_REPLICATES)
        self.assertEqual(result["block_length_draws"], BOOTSTRAP_BLOCK)
        self.assertEqual(result["seed"], 20261118)
        self.assertEqual(result["null_test"]["alternative"], "mean_delta_less_than_zero")
        self.assertEqual(result["null_test"]["null_series"], "d_t_minus_observed_mean_delta")
        self.assertIn("same block indices", result["method"])

    def test_null_centered_one_sided_test_direction(self):
        favorable = _moving_block_bootstrap([-1.0] * 60, seed=7)
        unfavorable = _moving_block_bootstrap([1.0] * 60, seed=7)
        self.assertEqual(favorable["one_sided_null_centered_p_value"],
                         1.0 / (BOOTSTRAP_REPLICATES + 1))
        self.assertEqual(unfavorable["one_sided_null_centered_p_value"], 1.0)

    def test_bootstrap_is_deterministic_for_fixed_seed(self):
        values = [math.sin(index / 7.0) for index in range(111)]
        first = _moving_block_bootstrap(values, seed=12345)
        second = _moving_block_bootstrap(values, seed=12345)
        self.assertEqual(first, second)

    def test_rejects_short_or_non_finite_series(self):
        with self.assertRaisesRegex(ValueError, "block length"):
            _moving_block_bootstrap([0.0] * (BOOTSTRAP_BLOCK - 1), seed=1)
        with self.assertRaisesRegex(ValueError, "finite"):
            _moving_block_bootstrap([0.0] * 49 + [float("nan")], seed=1)


class HolmCorrectionTests(unittest.TestCase):
    def test_two_hypothesis_preregistered_golden_fixture(self):
        adjusted = _holm_adjust({"front": 0.01, "back": 0.04})
        self.assertEqual(adjusted, {"front": 0.02, "back": 0.04})

    def test_step_down_is_monotone_in_sorted_order(self):
        adjusted = _holm_adjust({"h1": 0.001, "h2": 0.02, "h3": 0.03})
        self.assertEqual(adjusted, {"h1": 0.003, "h2": 0.04, "h3": 0.04})

    def test_caps_adjusted_values_and_rejects_invalid_p_values(self):
        self.assertEqual(_holm_adjust({"h1": 0.9, "h2": 1.0}), {"h1": 1.0, "h2": 1.0})
        for invalid in (-0.1, 1.1, float("nan"), float("inf")):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    _holm_adjust({"h": invalid})

    def test_rejects_empty_family(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            _holm_adjust({})


if __name__ == "__main__":
    unittest.main()
