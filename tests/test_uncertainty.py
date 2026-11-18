import unittest

from lottery.backtest import _moving_block_bootstrap_ci


class BootstrapTests(unittest.TestCase):
    def test_bootstrap_is_reproducible(self):
        values = [-0.01, 0.02, -0.03, 0.01] * 30
        first = _moving_block_bootstrap_ci(values, replicates=200, block_length=5, seed=7)
        second = _moving_block_bootstrap_ci(values, replicates=200, block_length=5, seed=7)
        self.assertEqual(first, second)

    def test_constant_delta_has_degenerate_interval(self):
        result = _moving_block_bootstrap_ci([0.25] * 20, replicates=100, block_length=4)
        self.assertAlmostEqual(result["mean_delta"], 0.25)
        self.assertAlmostEqual(result["ci_95_lower"], 0.25)
        self.assertAlmostEqual(result["ci_95_upper"], 0.25)

    def test_empty_input_rejected(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            _moving_block_bootstrap_ci([])


if __name__ == "__main__":
    unittest.main()
