"""Exact conditional-Poisson fixed-size subset distribution.

All normalizers, inclusion marginals, calibration objectives and backward
sampling probabilities are computed with log-space elementary-symmetric
polynomial dynamic programming. No independent Bernoulli approximation or
Monte Carlo normalizer is used.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from itertools import combinations
from math import exp, fsum, isfinite, log, sqrt, ulp
from pathlib import Path
from typing import Sequence


_NEG_INF = float("-inf")

CALIBRATION_SOLVER_ID = "conditional_poisson_calibration_lbfgs_strong_wolfe_v2"
CALIBRATION_LINE_SEARCH_C1 = 1e-4
CALIBRATION_LINE_SEARCH_C2 = 0.9
CALIBRATION_LINE_SEARCH_MAX_ITERATIONS = 60
CALIBRATION_INITIAL_STEP = 1.0
CALIBRATION_BRACKETING_FACTOR = 2.0


def calibration_configuration(
    *, tolerance: float = 1e-8, max_iterations: int = 5000, history_size: int = 10,
) -> dict:
    """Return the effective, content-bound configuration used by calibrate()."""
    if not isfinite(tolerance) or tolerance <= 0:
        raise ValueError("tolerance must be finite and positive")
    if type(max_iterations) is not int or max_iterations < 1:
        raise ValueError("max_iterations must be a positive integer")
    if type(history_size) is not int or history_size < 1:
        raise ValueError("history_size must be a positive integer")
    source_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return {
        "solver_id": CALIBRATION_SOLVER_ID,
        "algorithm": "L-BFGS",
        "implementation_version": "v2",
        "line_search": {
            "method": "strong_wolfe",
            "c1": CALIBRATION_LINE_SEARCH_C1,
            "c2": CALIBRATION_LINE_SEARCH_C2,
            "max_iterations": CALIBRATION_LINE_SEARCH_MAX_ITERATIONS,
            "initial_step": CALIBRATION_INITIAL_STEP,
            "bracketing": "step_doubling",
            "bracketing_factor": CALIBRATION_BRACKETING_FACTOR,
            "zoom": "deterministic_midpoint_bisection",
            "roundoff_policy": "bounded_float64_ulp_envelope",
        },
        "stopping": {
            "gradient_infinity_norm_tolerance": tolerance,
            "independent_marginal_residual_tolerance": tolerance,
            "max_iterations": max_iterations,
            "history_size": history_size,
        },
        "initialization": "zero_log_weights",
        "gauge": "centered_zero_sum",
        "accumulation": "compensated_float64_math.fsum",
        "source_sha256": source_sha256,
    }


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


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("vector dimensions do not match")
    return fsum(a * b for a, b in zip(left, right))


def _strong_wolfe_search(
    evaluate,
    point: tuple[float, ...],
    direction: tuple[float, ...],
    initial_objective: float,
    initial_gradient: tuple[float, ...],
    *,
    c1: float = 1e-4,
    c2: float = 0.9,
    max_iterations: int = 60,
    initial_step: float = CALIBRATION_INITIAL_STEP,
):
    """Deterministic strong-Wolfe search with a bounded float64 roundoff envelope."""
    derivative_zero = _dot(initial_gradient, direction)
    if not isfinite(derivative_zero) or derivative_zero >= 0.0:
        return None
    objective_roundoff = 8.0 * ulp(max(1.0, abs(initial_objective)))

    def at(step: float):
        trial = tuple(point[index] + step * direction[index] for index in range(len(point)))
        try:
            objective, gradient, achieved = evaluate(trial)
        except (ArithmeticError, ValueError, OverflowError):
            return None
        if (not isfinite(objective)
                or any(not isfinite(value) for value in gradient)
                or any(not isfinite(value) for value in achieved)):
            return None
        return trial, objective, tuple(gradient), tuple(achieved)

    def zoom(low: float, high: float, low_value):
        low_objective = initial_objective if low == 0.0 else low_value[1]
        for _ in range(max_iterations):
            step = 0.5 * (low + high)
            if step == low or step == high:
                break
            candidate = at(step)
            if (candidate is None
                    or candidate[1] > initial_objective + c1 * step * derivative_zero + objective_roundoff
                    or candidate[1] > low_objective + objective_roundoff):
                high = step
                continue
            derivative = _dot(candidate[2], direction)
            if abs(derivative) <= -c2 * derivative_zero:
                return candidate
            if derivative * (high - low) >= 0.0:
                high = low
            low = step
            low_value = candidate
            low_objective = candidate[1]
        return None

    if not isfinite(initial_step) or initial_step <= 0.0:
        return None
    previous_step = 0.0
    previous_value = (point, initial_objective, initial_gradient, ())
    step = initial_step
    for iteration in range(max_iterations):
        candidate = at(step)
        if candidate is None:
            return zoom(previous_step, step, previous_value)
        objective = candidate[1]
        if (objective > initial_objective + c1 * step * derivative_zero + objective_roundoff
                or (iteration > 0 and objective > previous_value[1] + objective_roundoff)):
            return zoom(previous_step, step, previous_value)
        derivative = _dot(candidate[2], direction)
        if abs(derivative) <= -c2 * derivative_zero:
            return candidate
        if derivative >= 0.0:
            return zoom(step, previous_step, candidate)
        previous_step = step
        previous_value = candidate
        step *= CALIBRATION_BRACKETING_FACTOR
    return None


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
        score = fsum(self.log_weights[index - 1] for index in values)
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
        line_search_c1: float = CALIBRATION_LINE_SEARCH_C1,
        line_search_c2: float = CALIBRATION_LINE_SEARCH_C2,
        line_search_max_iterations: int = CALIBRATION_LINE_SEARCH_MAX_ITERATIONS,
        line_search_initial_step: float = CALIBRATION_INITIAL_STEP,
    ) -> CalibrationResult:
        """Fit centered log-weights with deterministic strong-Wolfe L-BFGS."""
        target = tuple(float(value) for value in target_marginals)
        m = len(target)
        if type(k) is not int or not 1 <= k <= m:
            raise ValueError("k must be an integer in 1..len(target_marginals)")
        if any(not isfinite(value) for value in target):
            raise ValueError("target marginals must be finite")
        if any(not 0.0 < value < 1.0 for value in target):
            raise ValueError("target marginals must be strictly interior (0, 1)")
        if abs(fsum(target) - k) > 1e-10:
            raise ValueError("target marginals must sum to k; no silent renormalization")
        if not isfinite(tolerance) or tolerance <= 0:
            raise ValueError("tolerance must be finite and positive")
        if type(max_iterations) is not int or max_iterations < 1:
            raise ValueError("max_iterations must be a positive integer")
        if type(history_size) is not int or history_size < 1:
            raise ValueError("history_size must be a positive integer")
        if not (isfinite(line_search_c1) and isfinite(line_search_c2)
                and 0.0 < line_search_c1 < line_search_c2 < 1.0):
            raise ValueError("Strong-Wolfe constants must satisfy 0 < c1 < c2 < 1")
        if type(line_search_max_iterations) is not int or line_search_max_iterations < 1:
            raise ValueError("line_search_max_iterations must be a positive integer")
        if not isfinite(line_search_initial_step) or line_search_initial_step <= 0.0:
            raise ValueError("line_search_initial_step must be finite and positive")

        def evaluate(eta: tuple[float, ...]):
            model = cls(eta, k)
            achieved = model.inclusion_marginals()
            objective = model.log_normalizer - fsum(a * b for a, b in zip(eta, target))
            gradient = tuple(a - b for a, b in zip(achieved, target))
            mean_gradient = fsum(gradient) / m
            projected_gradient = tuple(value - mean_gradient for value in gradient)
            return objective, projected_gradient, achieved

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
            if s_hist:
                denominator = _dot(y_hist[-1], y_hist[-1])
                scale = _dot(s_hist[-1], y_hist[-1]) / denominator if denominator > 0.0 else 1.0
            else:
                scale = 1.0
            direction_seed = [scale * value for value in q]
            for (s_vec, y_vec, rho), alpha in zip(
                zip(s_hist, y_hist, rho_hist), reversed(alphas)
            ):
                beta = rho * _dot(y_vec, direction_seed)
                direction_seed = [
                    direction_seed[i] + s_vec[i] * (alpha - beta) for i in range(m)
                ]
            direction = tuple(-value for value in direction_seed)
            mean_direction = fsum(direction) / m
            direction = tuple(value - mean_direction for value in direction)
            directional_derivative = _dot(gradient, direction)
            if not isfinite(directional_derivative) or directional_derivative >= 0.0:
                direction = tuple(-value for value in gradient)
                directional_derivative = -_dot(gradient, gradient)
                s_hist.clear()
                y_hist.clear()
                rho_hist.clear()

            accepted = _strong_wolfe_search(
                evaluate, eta, direction, objective, gradient,
                c1=line_search_c1, c2=line_search_c2,
                max_iterations=line_search_max_iterations,
                initial_step=line_search_initial_step,
            )
            if accepted is None:
                status = "line_search_failed"
                message = "strong-Wolfe line search could not find an acceptable step"
                iterations = iteration
                break

            new_eta, new_objective, new_gradient, new_achieved = accepted
            s_vec = tuple(new_eta[i] - eta[i] for i in range(m))
            y_vec = tuple(new_gradient[i] - gradient[i] for i in range(m))
            curvature = _dot(s_vec, y_vec)
            s_norm = sqrt(_dot(s_vec, s_vec))
            y_norm = sqrt(_dot(y_vec, y_vec))
            if curvature > 1e-12 * s_norm * y_norm:
                s_hist.append(s_vec)
                y_hist.append(y_vec)
                rho_hist.append(1.0 / curvature)
                if len(s_hist) > history_size:
                    s_hist.pop(0)
                    y_hist.pop(0)
                    rho_hist.pop(0)
            eta, objective, gradient, achieved = (
                new_eta, new_objective, new_gradient, new_achieved
            )
            iterations = iteration + 1

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
        )
