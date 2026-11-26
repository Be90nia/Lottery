import itertools
import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.subset_model.conditional_poisson import (
    ConditionalPoisson,
    _strong_wolfe_search,
    calibration_configuration,
)


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

    def test_extreme_finite_weights_remain_stable_when_representable(self):
        model = ConditionalPoisson((30.0, -30.0, 20.0, -20.0, 0.0), 2)
        self.assertTrue(math.isfinite(model.log_normalizer))
        marginals = model.inclusion_marginals()
        self.assertTrue(all(math.isfinite(value) and 0.0 < value < 1.0 for value in marginals))
        self.assertAlmostEqual(sum(marginals), 2.0, places=10)

    def test_unrepresentable_open_interval_marginal_fails_closed(self):
        model = ConditionalPoisson((1000.0, -1000.0, 500.0, -500.0, 0.0), 2)
        with self.assertRaisesRegex(ArithmeticError, "representable open interval"):
            model.inclusion_marginals()

    def test_common_large_log_weight_offset_is_centered_safely(self):
        model = ConditionalPoisson((1e308, 1e308, 1e308, 1e308), 1)
        self.assertTrue(math.isfinite(model._centered_log_normalizer))
        self.assertEqual(model.inclusion_marginals(), (0.25, 0.25, 0.25, 0.25))


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



    def test_calibration_uses_strong_wolfe_and_not_armijo(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "src/lottery/subset_model/conditional_poisson.py"
        ).read_text(encoding="utf-8")
        self.assertIn("def _strong_wolfe_search(", source)
        self.assertIn("accepted = _strong_wolfe_search(", source)
        self.assertNotIn("Armijo search failed", source)

    def test_strong_wolfe_calibration_handles_high_dynamic_range_marginals(self):
        source = ConditionalPoisson(
            tuple((index - 17) * 0.07 for index in range(35)), 5
        )
        target = source.inclusion_marginals()
        first = ConditionalPoisson.calibrate(target, 5)
        second = ConditionalPoisson.calibrate(target, 5)
        self.assertTrue(first.converged, msg=first)
        self.assertLessEqual(first.maximum_absolute_residual, 1e-8)
        self.assertLessEqual(first.gradient_infinity_norm, 1e-8)
        self.assertEqual(first, second)

    def test_calibration_configuration_is_complete_and_source_bound(self):
        import hashlib

        configuration = calibration_configuration()
        source = Path(__file__).resolve().parents[1] / "src/lottery/subset_model/conditional_poisson.py"
        self.assertEqual(configuration["solver_id"], "conditional_poisson_calibration_lbfgs_strong_wolfe_v2")
        self.assertEqual(configuration["line_search"], {
            "method": "strong_wolfe",
            "c1": 1e-4,
            "c2": 0.9,
            "max_iterations": 60,
            "initial_step": 1.0,
            "bracketing": "step_doubling",
            "bracketing_factor": 2.0,
            "zoom": "deterministic_midpoint_bisection",
            "roundoff_policy": "bounded_float64_ulp_envelope",
        })
        self.assertEqual(configuration["stopping"], {
            "gradient_infinity_norm_tolerance": 1e-8,
            "independent_marginal_residual_tolerance": 1e-8,
            "max_iterations": 5000,
            "history_size": 10,
        })
        self.assertEqual(
            configuration["source_sha256"],
            hashlib.sha256(source.read_bytes()).hexdigest(),
        )
        self.assertEqual(configuration["initialization"], "zero_log_weights")
        self.assertEqual(configuration["gauge"], "centered_zero_sum")
        self.assertEqual(configuration["accumulation"], "compensated_float64_math.fsum")

    def test_strong_wolfe_zoom_accepts_after_initial_objective_increase(self):
        def evaluate(point):
            x = point[0]
            objective = x**4 - 2.0*x**3 + 2.0*x**2 - 0.5*x
            gradient = (4.0*x**3 - 6.0*x**2 + 4.0*x - 0.5,)
            return objective, gradient, (0.5,)

        # The first trial at step=1 must increase the objective, forcing zoom.
        self.assertGreater(evaluate((1.0,))[0], evaluate((0.0,))[0])
        accepted = _strong_wolfe_search(
            evaluate, (0.0,), (1.0,), 0.0, (-0.5,),
        )
        self.assertIsNotNone(accepted)
        point, objective, gradient, _ = accepted
        step = point[0]
        self.assertLessEqual(objective, 0.0 + 1e-4 * step * -0.5 + 1e-14)
        derivative = gradient[0]
        self.assertLessEqual(abs(derivative), 0.9 * 0.5)

    def test_strong_wolfe_zoom_handles_derivative_sign_transition(self):
        def evaluate(point):
            x = point[0]
            objective = (x - 0.75) ** 2
            gradient = (2.0 * (x - 0.75),)
            return objective, gradient, (0.5,)

        first = _strong_wolfe_search(
            evaluate, (0.0,), (1.0,), 0.75**2, (-1.5,),
        )
        second = _strong_wolfe_search(
            evaluate, (0.0,), (1.0,), 0.75**2, (-1.5,),
        )
        self.assertIsNotNone(first)
        self.assertEqual(first, second)
        point, objective, gradient, _ = first
        step = point[0]
        derivative_zero = -1.5
        derivative = gradient[0]
        self.assertLessEqual(objective, 0.75**2 + 1e-4 * step * derivative_zero + 1e-14)
        self.assertLessEqual(abs(derivative), -0.9 * derivative_zero)

    def test_calibration_rejects_boundary_and_wrong_sum_without_repair(self):
        with self.assertRaises(ValueError):
            ConditionalPoisson.calibrate((1.0, 0.5, 0.5), 2)
        with self.assertRaises(ValueError):
            ConditionalPoisson.calibrate((0.2, 0.2, 0.2), 2)

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
