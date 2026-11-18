import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.subset_model import build_uniform_feature_table, enumerate_support
from lottery.subset_model.exponential import ExponentialFamily


class ExponentialFamilyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = build_uniform_feature_table(8, 3, include_gap_variance=True)
        cls.model = ExponentialFamily(cls.table)

    def test_theta_zero_is_exact_uniform_on_every_subset(self):
        theta = (0.0,) * self.model.dimension
        expected = -math.log(math.comb(8, 3))
        for subset in enumerate_support(8, 3):
            self.assertAlmostEqual(self.model.log_probability(subset, theta), expected, places=12)
        self.assertAlmostEqual(self.model.probability_sum(theta), 1.0, places=14)

    def test_aggregated_log_partition_matches_direct_enumeration(self):
        theta = tuple(0.07 * (index + 1) for index in range(self.model.dimension))
        direct_terms = []
        for subset in enumerate_support(8, 3):
            from lottery.subset_model import extract_features
            raw = extract_features(subset, 8, 3, include_gap_variance=True)
            z = self.table.stats.standardize(raw)
            direct_terms.append(sum(a * b for a, b in zip(theta, z)))
        maximum = max(direct_terms)
        direct_log_z = maximum + math.log(sum(math.exp(x - maximum) for x in direct_terms))
        self.assertAlmostEqual(self.model.log_partition(theta), direct_log_z, places=12)

    def test_probability_sum_for_nonzero_parameters(self):
        theta = (0.12, -0.08, 0.04, 0.11, -0.03)
        self.assertAlmostEqual(self.model.probability_sum(theta), 1.0, places=14)

    def test_log_partition_gradient_equals_expected_features(self):
        theta = (0.03, -0.07, 0.02, 0.05, -0.01)
        expected = self.model.expected_features(theta)
        epsilon = 1e-6
        for index in range(self.model.dimension):
            plus = list(theta)
            minus = list(theta)
            plus[index] += epsilon
            minus[index] -= epsilon
            finite_difference = (
                self.model.log_partition(plus) - self.model.log_partition(minus)
            ) / (2 * epsilon)
            self.assertAlmostEqual(expected[index], finite_difference, places=7)

    def test_invalid_subset_and_nonfinite_theta_fail_closed(self):
        with self.assertRaises(ValueError):
            self.model.log_probability((3, 1, 2), (0.0,) * self.model.dimension)
        with self.assertRaises(ValueError):
            self.model.log_partition((float("nan"),) * self.model.dimension)

    def test_fit_returns_recomputed_converged_diagnostics(self):
        observations = [
            (1, 2, 3), (1, 2, 4), (1, 3, 5), (2, 4, 6),
            (2, 5, 8), (3, 6, 8), (1, 4, 7), (2, 3, 7),
        ]
        result = self.model.fit(observations)
        self.assertEqual(result.objective_scale, "mean_nll")
        self.assertEqual(result.regularization_lambda, 1.0)
        self.assertTrue(result.converged, msg=result)
        self.assertEqual(result.terminal_status, "converged")
        self.assertLessEqual(result.gradient_infinity_norm, 1e-8)
        self.assertTrue(math.isfinite(result.unregularized_mean_nll))
        self.assertTrue(math.isfinite(result.penalized_objective))

    def test_repeating_full_training_multiset_preserves_objective(self):
        observations = [(1, 2, 3), (1, 2, 4), (2, 4, 6), (3, 6, 8)]
        once = self.model.fit(observations)
        repeated = self.model.fit(observations * 3)
        self.assertTrue(once.converged, msg=once)
        self.assertTrue(repeated.converged, msg=repeated)
        self.assertAlmostEqual(once.penalized_objective, repeated.penalized_objective, places=10)
        for left, right in zip(once.theta, repeated.theta):
            self.assertAlmostEqual(left, right, places=7)


if __name__ == "__main__":
    unittest.main()
