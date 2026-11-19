import itertools
import math
import random
import unittest

from lottery.subset_probability import (
    BACK, FRONT, FeatureSchema, aggregate_feature_cells,
    conditional_poisson_log_normalizer, conditional_poisson_log_probability,
    conditional_poisson_marginals, enumerate_support, extract_features,
    log_partition, log_probability, sample_conditional_poisson, sample_subsets,
    uniform_feature_stats, validate_subset,
)


class SupportTests(unittest.TestCase):
    def test_support_matches_binomial_for_every_small_dimension(self):
        for m in range(2, 9):
            for k in range(m + 1):
                support = list(enumerate_support(m, k))
                self.assertEqual(len(support), math.comb(m, k))
                self.assertEqual(len(set(support)), len(support))
                self.assertEqual(support, sorted(support))

    def test_production_support_sizes(self):
        self.assertEqual(sum(1 for _ in enumerate_support(*FRONT)), 324632)
        self.assertEqual(sum(1 for _ in enumerate_support(*BACK)), 66)

    def test_invalid_or_noncanonical_subsets_fail_closed(self):
        for subset in ([2, 1], [1, 1], [0, 2], [1, 36], [True, 2], [1.0, 2.0]):
            with self.subTest(subset=subset), self.assertRaises(ValueError):
                validate_subset(subset, 35, 2)
        with self.assertRaises(ValueError):
            validate_subset([1], 35, 2)

    def test_dimensions_reject_booleans(self):
        with self.assertRaises(ValueError):
            list(enumerate_support(True, 1))


class FeatureAndExponentialTests(unittest.TestCase):
    def test_feature_formulas(self):
        schema = FeatureSchema.for_support(8, 3)
        self.assertEqual(extract_features((1, 3, 6), schema), (10.0, 2.0, 5.0, 0.0, 0.25))
        self.assertEqual(extract_features((1, 2, 3), schema), (6.0, 2.0, 2.0, 2.0, 0.0))

    def test_uniform_moments_and_zero_variance_omission(self):
        stats = uniform_feature_stats(12, 2)
        self.assertEqual(stats.support_count, 66)
        self.assertNotIn("gap_var", stats.schema.names)
        self.assertEqual(len(stats.means), len(stats.population_stds))
        self.assertTrue(all(value > 0 for value in stats.population_stds))

    def test_full_front_and_back_cells_cover_support(self):
        front = aggregate_feature_cells(*FRONT)
        back = aggregate_feature_cells(*BACK)
        self.assertEqual(front.support_count, 324632)
        self.assertEqual(sum(count for _, count in front.cells), 324632)
        self.assertEqual(back.support_count, 66)
        self.assertEqual(sum(count for _, count in back.cells), 66)

    def test_zero_theta_recovers_uniform(self):
        for m, k in (FRONT, BACK):
            cells = aggregate_feature_cells(m, k)
            theta = [0.0] * len(cells.schema.names)
            self.assertAlmostEqual(log_partition(theta, cells), math.log(math.comb(m, k)), places=12)
            for subset in itertools.islice(enumerate_support(m, k), 10):
                self.assertAlmostEqual(log_probability(subset, theta, cells),
                                       -math.log(math.comb(m, k)), places=12)

    def test_nonfinite_theta_rejected(self):
        cells = aggregate_feature_cells(*BACK)
        with self.assertRaises(ValueError):
            log_partition([float("nan")] * len(cells.schema.names), cells)


class ConditionalPoissonTests(unittest.TestCase):
    def test_dp_matches_brute_force_for_all_small_supports(self):
        for m in range(2, 9):
            weights = [math.log(i + 1) / 3 for i in range(m)]
            for k in range(m + 1):
                brute = [sum(weights[i] for i in subset)
                         for subset in itertools.combinations(range(m), k)]
                maximum = max(brute)
                expected = maximum + math.log(sum(math.exp(x - maximum) for x in brute))
                self.assertAlmostEqual(conditional_poisson_log_normalizer(weights, k), expected, places=11)
                pi = conditional_poisson_marginals(weights, k)
                for i in range(m):
                    selected = [sum(weights[j] for j in subset)
                                for subset in itertools.combinations(range(m), k) if i in subset]
                    expected_pi = sum(math.exp(x - expected) for x in selected)
                    self.assertAlmostEqual(pi[i], expected_pi, places=10)
                self.assertAlmostEqual(sum(pi), k, places=10)

    def test_extreme_finite_weights_stay_finite(self):
        weights = [-30.0, -15.0, 0.0, 15.0, 30.0]
        self.assertTrue(math.isfinite(conditional_poisson_log_normalizer(weights, 2)))
        pi = conditional_poisson_marginals(weights, 2)
        self.assertTrue(all(math.isfinite(x) for x in pi))
        self.assertAlmostEqual(sum(pi), 2.0, places=10)

    def test_probability_and_backward_sampler(self):
        weights = [math.log(x) for x in (1, 2, 3, 4, 5, 6)]
        sample = sample_conditional_poisson(weights, 3, random.Random(42))
        self.assertEqual(len(sample), 3)
        self.assertEqual(len(set(sample)), 3)
        self.assertTrue(all(1 <= x <= 6 for x in sample))
        self.assertTrue(math.isfinite(conditional_poisson_log_probability(sample, weights, 3)))

    def test_deterministic_replay(self):
        first = sample_subsets([0.0] * 8, 3, 20, seed=71)
        second = sample_subsets([0.0] * 8, 3, 20, seed=71)
        self.assertEqual(first, second)

    def test_weighted_marginal_calibration_recovers_generated_marginals(self):
        from lottery.subset_probability import calibrate_weighted_subset
        source_weights = [-0.8, -0.2, 0.1, 0.4, 0.5]
        target = conditional_poisson_marginals(source_weights, 2)
        result = calibrate_weighted_subset(target, 2)
        self.assertTrue(result.forecast_ready, result)
        self.assertLessEqual(result.max_abs_residual, 1e-8)
        self.assertAlmostEqual(sum(result.log_weights), 0.0, places=10)

    def test_weighted_marginal_calibration_fails_closed_on_boundary(self):
        from lottery.subset_probability import calibrate_weighted_subset
        with self.assertRaises(ValueError):
            calibrate_weighted_subset([1.0, 0.5, 0.5], 2)

    def test_mean_nll_objective_and_gradient_replication_invariance(self):
        from lottery.subset_probability import exponential_objective_gradient
        stats = uniform_feature_stats(8, 3)
        cells = aggregate_feature_cells(8, 3, stats)
        training = [(1, 2, 4), (2, 5, 7), (1, 6, 8)]
        theta = [0.1] * len(cells.schema.names)
        first = exponential_objective_gradient(theta, training, cells)
        second = exponential_objective_gradient(theta, training * 3, cells)
        self.assertAlmostEqual(first[0], second[0], places=12)
        self.assertEqual(first[1], second[1])
        self.assertAlmostEqual(first[2], second[2], places=12)

    def test_exponential_objective_gradient_matches_finite_difference(self):
        from lottery.subset_probability import exponential_objective_gradient
        stats = uniform_feature_stats(8, 3)
        cells = aggregate_feature_cells(8, 3, stats)
        training = [(1, 2, 4), (2, 5, 7), (1, 6, 8)]
        theta = [0.07] * len(cells.schema.names)
        _, gradient, _ = exponential_objective_gradient(theta, training, cells)
        for index in range(len(theta)):
            plus, minus = list(theta), list(theta)
            plus[index] += 1e-6
            minus[index] -= 1e-6
            high = exponential_objective_gradient(plus, training, cells)[0]
            low = exponential_objective_gradient(minus, training, cells)[0]
            numeric = (high - low) / 2e-6
            self.assertAlmostEqual(gradient[index], numeric, places=6)

    def test_invalid_weights_rejected(self):
        with self.assertRaises(ValueError):
            conditional_poisson_log_normalizer([0.0, float("inf")], 1)


if __name__ == "__main__":
    unittest.main()
