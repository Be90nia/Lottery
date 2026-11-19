import itertools
import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.subset_model.conditional_poisson import ConditionalPoisson


def brute_force(log_weights, k):
    rows = []
    for subset in itertools.combinations(range(len(log_weights)), k):
        score = sum(log_weights[index] for index in subset)
        rows.append((subset, score))
    maximum = max(score for _, score in rows)
    weights = [math.exp(score - maximum) for _, score in rows]
    total = sum(weights)
    probabilities = [weight / total for weight in weights]
    marginals = [0.0] * len(log_weights)
    for (subset, _), probability in zip(rows, probabilities):
        for index in subset:
            marginals[index] += probability
    log_z = maximum + math.log(total)
    return log_z, tuple(marginals), tuple(probabilities)


class ConditionalPoissonDPTests(unittest.TestCase):
    def test_dp_matches_brute_force_for_every_small_m_and_k(self):
        for m in range(2, 9):
            log_weights = tuple(0.17 * (index + 1) - 0.31 for index in range(m))
            for k in range(1, m + 1):
                with self.subTest(m=m, k=k):
                    model = ConditionalPoisson(log_weights, k)
                    expected_log_z, expected_marginals, _ = brute_force(log_weights, k)
                    self.assertAlmostEqual(model.log_normalizer, expected_log_z, places=12)
                    for actual, expected in zip(model.inclusion_marginals(), expected_marginals):
                        self.assertAlmostEqual(actual, expected, places=12)
                    self.assertAlmostEqual(sum(model.inclusion_marginals()), k, places=12)

    def test_complete_subset_probabilities_sum_to_one(self):
        log_weights = (0.3, -0.2, 0.7, -0.4, 0.1, 0.6)
        model = ConditionalPoisson(log_weights, 2)
        total = sum(
            math.exp(model.log_probability(tuple(index + 1 for index in subset)))
            for subset in itertools.combinations(range(len(log_weights)), 2)
        )
        self.assertAlmostEqual(total, 1.0, places=13)
        self.assertAlmostEqual(model.probability_sum(), 1.0, places=15)

    def test_permutation_equivariance(self):
        weights = (0.4, -0.8, 0.2, 1.1, -0.1, 0.7)
        permutation = (3, 0, 5, 1, 4, 2)
        original = ConditionalPoisson(weights, 3)
        permuted_weights = tuple(weights[index] for index in permutation)
        permuted = ConditionalPoisson(permuted_weights, 3)
        self.assertAlmostEqual(original.log_normalizer, permuted.log_normalizer, places=12)
        original_marginals = original.inclusion_marginals()
        permuted_marginals = permuted.inclusion_marginals()
        for new_index, old_index in enumerate(permutation):
            self.assertAlmostEqual(permuted_marginals[new_index], original_marginals[old_index], places=12)

    def test_log_normalizer_gradient_equals_inclusion_marginals(self):
        weights = (0.13, -0.21, 0.44, 0.08, -0.33, 0.17)
        model = ConditionalPoisson(weights, 2)
        marginals = model.inclusion_marginals()
        epsilon = 1e-6
        for index in range(len(weights)):
            plus = list(weights)
            minus = list(weights)
            plus[index] += epsilon
            minus[index] -= epsilon
            finite_difference = (
                ConditionalPoisson(plus, 2).log_normalizer
                - ConditionalPoisson(minus, 2).log_normalizer
            ) / (2 * epsilon)
            self.assertAlmostEqual(marginals[index], finite_difference, places=7)

    def test_extreme_finite_weights_remain_stable(self):
        model = ConditionalPoisson((1000.0, -1000.0, 500.0, -500.0, 0.0), 2)
        self.assertTrue(math.isfinite(model.log_normalizer))
        marginals = model.inclusion_marginals()
        self.assertTrue(all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in marginals))
        self.assertAlmostEqual(sum(marginals), 2.0, places=10)


class ConditionalPoissonCalibrationTests(unittest.TestCase):
    def test_calibration_recovers_exact_target_marginals(self):
        source = ConditionalPoisson((0.3, -0.2, 0.7, -0.4, 0.1), 2)
        target = source.inclusion_marginals()
        result = ConditionalPoisson.calibrate(target, 2)
        self.assertTrue(result.converged, msg=result)
        self.assertEqual(result.terminal_status, "converged")
        self.assertLessEqual(result.maximum_absolute_residual, 1e-8)
        self.assertLessEqual(result.gradient_infinity_norm, 1e-8)
        self.assertAlmostEqual(sum(result.centered_log_weights), 0.0, places=12)

    def test_calibration_rejects_boundary_and_wrong_sum_without_repair(self):
        with self.assertRaises(ValueError):
            ConditionalPoisson.calibrate((1.0, 0.5, 0.5), 2)
        with self.assertRaises(ValueError):
            ConditionalPoisson.calibrate((0.2, 0.2, 0.2), 2)

    def test_calibration_rejects_boolean_and_string_numeric_inputs(self):
        for target in ((True, 0.4, 0.6, 1.0), ("0.3", 0.4, 0.5, 0.8)):
            with self.subTest(target=target):
                with self.assertRaisesRegex(ValueError, "int/float"):
                    ConditionalPoisson.calibrate(target, 2)
        with self.assertRaisesRegex(ValueError, "tolerance"):
            ConditionalPoisson.calibrate((0.3, 0.4, 0.5, 0.8), 2, tolerance=True)

    def test_calibration_rejects_invalid_history_size(self):
        for history_size in (0, -1, 1.5, True):
            with self.subTest(history_size=history_size):
                with self.assertRaisesRegex(ValueError, "history_size must be a positive integer"):
                    ConditionalPoisson.calibrate(
                        (0.3, 0.4, 0.5, 0.8), 2, history_size=history_size
                    )

    def test_backward_sampler_rejects_invalid_rng_values(self):
        class InvalidRng:
            def __init__(self, value):
                self.value = value

            def random(self):
                return self.value

        model = ConditionalPoisson((0.3, -0.2, 0.7, -0.4, 0.1), 2)
        for value in (False, True, -0.1, 1.0, float("nan"), "0.5"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "rng.random"):
                    model.sample(InvalidRng(value))

    def test_backward_sampler_returns_distinct_legal_items_and_replays(self):
        model = ConditionalPoisson((0.3, -0.2, 0.7, -0.4, 0.1, 0.8), 3)
        left_rng = random.Random(20261118)
        right_rng = random.Random(20261118)
        left = [model.sample(left_rng) for _ in range(100)]
        right = [model.sample(right_rng) for _ in range(100)]
        self.assertEqual(left, right)
        for subset in left:
            self.assertEqual(len(subset), 3)
            self.assertEqual(len(set(subset)), 3)
            self.assertEqual(tuple(sorted(subset)), subset)
            self.assertTrue(all(1 <= value <= 6 for value in subset))

    def test_backward_sampler_empirical_marginals_match_exact_dp(self):
        model = ConditionalPoisson((0.3, -0.2, 0.7, -0.4, 0.1), 2)
        expected = model.inclusion_marginals()
        rng = random.Random(20261118)
        draws = 12000
        counts = [0] * 5
        for _ in range(draws):
            for value in model.sample(rng):
                counts[value - 1] += 1
        empirical = [value / draws for value in counts]
        for actual, target in zip(empirical, expected):
            self.assertAlmostEqual(actual, target, delta=0.02)


if __name__ == "__main__":
    unittest.main()
