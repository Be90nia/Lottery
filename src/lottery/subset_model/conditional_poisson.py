"""Exact conditional-Poisson fixed-size subset distribution.

All normalizers, inclusion marginals, calibration objectives and backward
sampling probabilities are computed with log-space elementary-symmetric
polynomial dynamic programming. No independent Bernoulli approximation or
Monte Carlo normalizer is used.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import exp, fsum, isfinite, log
from typing import Sequence

from .exponential import _dot, _strong_wolfe_search


_NEG_INF = float("-inf")


def _logaddexp(left: float, right: float) -> float:
    if left == _NEG_INF:
        return right
    if right == _NEG_INF:
        return left
    maximum = max(left, right)
    return maximum + log(exp(left - maximum) + exp(right - maximum))


def _logsumexp(values: Sequence[float]) -> float:
    if not values:
        return _NEG_INF
    result = _NEG_INF
    for value in values:
        result = _logaddexp(result, value)
    return result


def _validate_log_weights(log_weights: Sequence[float], k: int) -> tuple[tuple[float, ...], float]:
    if isinstance(log_weights, (str, bytes, bytearray)):
        raise ValueError("log_weights must be a numeric sequence")
    raw = tuple(log_weights)
    if not raw or any(type(value) not in (int, float) for value in raw):
        raise ValueError("log_weights must be a non-empty sequence of int/float values")
    values = tuple(float(value) for value in raw)
    if any(not isfinite(value) for value in values):
        raise ValueError("log_weights must contain only finite values")
    if type(k) is not int or not 1 <= k <= len(values):
        raise ValueError("k must be an integer in 1..len(log_weights)")
    # Shift before summing so a large common offset does not overflow.
    # A spread that cannot be represented after centering is rejected rather
    # than allowed to poison the DP with infinities.
    offset = max(values)
    try:
        center = offset + fsum(value - offset for value in values) / len(values)
    except OverflowError as exc:
        raise ValueError("log_weights cannot be centered in float64") from exc
    centered = tuple(value - center for value in values)
    if not isfinite(center) or any(not isfinite(value) for value in centered):
        raise ValueError("centered log_weights must remain finite in float64")
    return centered, center


def _forward_dp(log_weights: tuple[float, ...], k: int) -> list[list[float]]:
    """prefix[i][j] = log e_j(weights[0:i]); columns above k are omitted."""
    m = len(log_weights)
    prefix = [[_NEG_INF] * (k + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        prefix[i][0] = 0.0
    for i, log_weight in enumerate(log_weights, start=1):
        previous = prefix[i - 1]
        current = prefix[i]
        upper = min(i, k)
        for j in range(1, upper + 1):
            current[j] = _logaddexp(previous[j], log_weight + previous[j - 1])
    return prefix


def _backward_dp(log_weights: tuple[float, ...], k: int) -> list[list[float]]:
    """suffix[i][j] = log e_j(weights[i:m])."""
    m = len(log_weights)
    suffix = [[_NEG_INF] * (k + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        suffix[i][0] = 0.0
    for i in range(m - 1, -1, -1):
        following = suffix[i + 1]
        current = suffix[i]
        upper = min(m - i, k)
        for j in range(1, upper + 1):
            current[j] = _logaddexp(following[j], log_weights[i] + following[j - 1])
    return suffix


@dataclass(frozen=True)
class CalibrationResult:
    terminal_status: str
    converged: bool
    centered_log_weights: tuple[float, ...]
    target_marginals: tuple[float, ...]
    achieved_marginals: tuple[float, ...]
    maximum_absolute_residual: float
    objective: float
    gradient_infinity_norm: float
    iterations: int
    message: str
    solver: str


class ConditionalPoisson:
    """Fixed-cardinality rejective/conditional-Poisson subset distribution."""

    def __init__(self, log_weights: Sequence[float], k: int):
        self.log_weights, self._log_weight_offset = _validate_log_weights(log_weights, k)
        self.m = len(self.log_weights)
        self.k = k
        self._prefix = _forward_dp(self.log_weights, k)
        self._centered_log_normalizer = self._prefix[self.m][k]
        self.log_normalizer = self._centered_log_normalizer + k * self._log_weight_offset
        if not isfinite(self.log_normalizer):
            raise ArithmeticError("conditional-Poisson normalizer is not finite")
        self._suffix = _backward_dp(self.log_weights, k)

    def log_probability(self, subset: Sequence[int]) -> float:
        if isinstance(subset, (str, bytes, bytearray)):
            raise ValueError("subset must be a sequence of one-based item indices")
        values = tuple(subset)
        if len(values) != self.k:
            raise ValueError(f"subset must contain exactly {self.k} items")
        if any(type(value) is not int for value in values):
            raise ValueError("subset indices must be integers")
        if any(not 1 <= value <= self.m for value in values):
            raise ValueError(f"subset indices must be in 1..{self.m}")
        if any(a >= b for a, b in zip(values, values[1:])):
            raise ValueError("subset must be strictly increasing and unique")
        score = sum(self.log_weights[index - 1] for index in values)
        result = score - self._centered_log_normalizer
        if not isfinite(result) or result > 1e-12:
            raise ArithmeticError("invalid conditional-Poisson log probability")
        return result

    def inclusion_marginals(self) -> tuple[float, ...]:
        """Compute exact first-order inclusion marginals using prefix/suffix DP."""
        result = []
        for index, log_weight in enumerate(self.log_weights):
            terms = []
            for left_count in range(self.k):
                right_count = self.k - 1 - left_count
                left = self._prefix[index][left_count]
                right = self._suffix[index + 1][right_count]
                if left != _NEG_INF and right != _NEG_INF:
                    terms.append(left + right)
            log_excluded_normalizer = _logsumexp(terms)
            log_marginal = log_weight + log_excluded_normalizer - self._centered_log_normalizer
            marginal = exp(log_marginal)
            if not isfinite(marginal) or not 0.0 <= marginal <= 1.0:
                raise ArithmeticError("computed inclusion marginal is invalid")
            if 0 < self.k < self.m and not 0.0 < marginal < 1.0:
                raise ArithmeticError(
                    "finite non-degenerate inclusion marginal is outside the representable open interval"
                )
            result.append(marginal)
        if abs(fsum(result) - self.k) > 1e-10:
            raise ArithmeticError("inclusion marginals do not sum to the fixed subset size")
        return tuple(result)

    def probability_sum(self) -> float:
        """Exhaustive floating-point normalization diagnostic over complete support."""
        total = 0.0
        for subset in combinations(range(1, self.m + 1), self.k):
            total += exp(self.log_probability(subset))
        return total

    def sample(self, rng) -> tuple[int, ...]:
        """Exact backward sample; rng must expose random() in [0, 1)."""
        if not callable(getattr(rng, "random", None)):
            raise TypeError("rng must expose a random() method")
        remaining = self.k
        selected: list[int] = []
        for i in range(self.m, 0, -1):
            if remaining == 0:
                break
            if i == remaining:
                selected.extend(range(1, i + 1))
                remaining = 0
                break
            denominator = self._prefix[i][remaining]
            numerator = self.log_weights[i - 1] + self._prefix[i - 1][remaining - 1]
            include_probability = exp(numerator - denominator)
            if rng.random() < include_probability:
                selected.append(i)
                remaining -= 1
        if remaining != 0:
            raise ArithmeticError("backward sampler failed to select exactly k items")
        result = tuple(sorted(selected))
        if len(result) != self.k or len(set(result)) != self.k:
            raise ArithmeticError("backward sampler returned an invalid subset")
        return result

    @classmethod
    def calibrate(
        cls,
        target_marginals: Sequence[float],
        k: int,
        *,
        tolerance: float = 1e-8,
        max_iterations: int = 5000,
        history_size: int = 10,
    ) -> CalibrationResult:
        """Fit centered log-weights to interior fixed-size inclusion marginals."""
        target = tuple(float(value) for value in target_marginals)
        m = len(target)
        if type(k) is not int or not 1 <= k <= m:
            raise ValueError("k must be an integer in 1..len(target_marginals)")
        if any(not isfinite(value) for value in target):
            raise ValueError("target marginals must be finite")
        if any(not 0.0 < value < 1.0 for value in target):
            raise ValueError("target marginals must be strictly interior (0, 1)")
        if abs(sum(target) - k) > 1e-10:
            raise ValueError("target marginals must sum to k; no silent renormalization")
        if not isfinite(tolerance) or tolerance <= 0:
            raise ValueError("tolerance must be finite and positive")
        if type(max_iterations) is not int or max_iterations < 1:
            raise ValueError("max_iterations must be a positive integer")

        def evaluate(eta: tuple[float, ...]):
            model = cls(eta, k)
            achieved = model.inclusion_marginals()
            objective = model.log_normalizer - fsum(a * b for a, b in zip(eta, target))
            gradient = tuple(a - b for a, b in zip(achieved, target))
            # Project the gauge direction; the objective is invariant to a
            # common additive constant when both marginal sums equal k.
            mean_gradient = fsum(gradient) / m
            gradient = tuple(value - mean_gradient for value in gradient)
            return objective, gradient, achieved

        eta = tuple(0.0 for _ in range(m))
        objective, gradient, achieved = evaluate(eta)
        s_hist: list[tuple[float, ...]] = []
        y_hist: list[tuple[float, ...]] = []
        rho_hist: list[float] = []
        status = "max_iterations"
        message = "maximum iteration count reached"
        iterations = 0

        for iteration in range(max_iterations + 1):
            grad_inf = max(abs(value) for value in gradient)
            residual = max(abs(a - b) for a, b in zip(achieved, target))
            if grad_inf <= tolerance and residual <= tolerance:
                status, message, iterations = "converged", "marginal residual reached tolerance", iteration
                break
            if iteration == max_iterations:
                iterations = iteration
                break

            q = list(gradient)
            alphas = []
            for s_vec, y_vec, rho in zip(reversed(s_hist), reversed(y_hist), reversed(rho_hist)):
                alpha = rho * _dot(s_vec, q)
                alphas.append(alpha)
                q = [q[i] - alpha * y_vec[i] for i in range(m)]
            scale = (_dot(s_hist[-1], y_hist[-1]) / _dot(y_hist[-1], y_hist[-1])) if s_hist else 1.0
            direction_seed = [scale * value for value in q]
            for (s_vec, y_vec, rho), alpha in zip(zip(s_hist, y_hist, rho_hist), reversed(alphas)):
                beta = rho * _dot(y_vec, direction_seed)
                direction_seed = [
                    direction_seed[i] + s_vec[i] * (alpha - beta) for i in range(m)
                ]
            direction = tuple(-value for value in direction_seed)
            # Project direction into the zero-sum gauge.
            mean_direction = fsum(direction) / m
            direction = tuple(value - mean_direction for value in direction)
            directional_derivative = _dot(gradient, direction)
            if directional_derivative >= 0:
                direction = tuple(-value for value in gradient)
                directional_derivative = -_dot(gradient, gradient)
                s_hist.clear(); y_hist.clear(); rho_hist.clear()

            def line_evaluate(point):
                trial_objective, trial_gradient, _ = evaluate(point)
                return trial_objective, trial_gradient, trial_objective

            accepted = _strong_wolfe_search(
                line_evaluate, eta, direction, objective, gradient,
            )
            if accepted is None:
                status, message, iterations = "line_search_failed", "strong-Wolfe search failed", iteration
                break
            new_eta = accepted[0]
            new_objective, new_gradient, new_achieved = evaluate(new_eta)
            s_vec = tuple(new_eta[i] - eta[i] for i in range(m))
            y_vec = tuple(new_gradient[i] - gradient[i] for i in range(m))
            curvature = _dot(s_vec, y_vec)
            if curvature > 1e-14:
                s_hist.append(s_vec); y_hist.append(y_vec); rho_hist.append(1.0 / curvature)
                if len(s_hist) > history_size:
                    s_hist.pop(0); y_hist.pop(0); rho_hist.pop(0)
            eta, objective, gradient, achieved = new_eta, new_objective, new_gradient, new_achieved
            iterations = iteration + 1

        # Recompute from the final canonical centered weights.
        center = fsum(eta) / m
        eta = tuple(value - center for value in eta)
        final_model = cls(eta, k)
        final_achieved = final_model.inclusion_marginals()
        residual = max(abs(a - b) for a, b in zip(final_achieved, target))
        final_objective = final_model.log_normalizer - fsum(a * b for a, b in zip(eta, target))
        final_gradient = tuple(a - b for a, b in zip(final_achieved, target))
        gradient_inf = max(abs(value) for value in final_gradient)
        converged = status == "converged" and residual <= tolerance and gradient_inf <= tolerance
        if status == "converged" and not converged:
            status, message = "post_fit_validation_failed", "independent marginal residual check failed"
        return CalibrationResult(
            terminal_status=status,
            converged=converged,
            centered_log_weights=eta,
            target_marginals=target,
            achieved_marginals=final_achieved,
            maximum_absolute_residual=residual,
            objective=final_objective,
            gradient_infinity_norm=gradient_inf,
            iterations=iterations,
            message=message,
            solver="conditional_poisson_calibration_lbfgs_strong_wolfe_v2",
        )
