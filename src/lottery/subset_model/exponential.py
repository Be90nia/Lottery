"""Exact complete-subset exponential-family probabilities and fitting."""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from math import exp, fsum, isfinite, log, ulp
from typing import Sequence

from .features import extract_features
from .support import enumerate_support, validate_subset
from .uniform import UniformFeatureTable


def _finite_vector(values: Sequence[float], name: str) -> tuple[float, ...]:
    try:
        result = tuple(float(value) for value in values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite numeric sequence") from exc
    if any(not isfinite(value) for value in result):
        raise ValueError(f"{name} must contain only finite values")
    return result


def logsumexp(values: Sequence[float]) -> float:
    """Stable float64 log(sum(exp(values)))."""
    if not values:
        raise ValueError("logsumexp requires at least one value")
    vals = _finite_vector(values, "values")
    maximum = max(vals)
    return maximum + log(fsum(exp(value - maximum) for value in vals))


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
) -> tuple[tuple[float, ...], float, tuple[float, ...], float] | None:
    """Deterministic strong-Wolfe line search for the unbounded L-BFGS-B case."""
    derivative_zero = _dot(initial_gradient, direction)
    if not isfinite(derivative_zero) or derivative_zero >= 0.0:
        return None
    # Near stationarity, the theoretical Armijo decrease can be smaller than
    # one float64 ULP of the objective. Permit only a bounded rounding envelope;
    # the strong-Wolfe curvature condition must still hold.
    objective_roundoff = 8.0 * ulp(max(1.0, abs(initial_objective)))

    def at(step: float):
        trial = tuple(point[index] + step * direction[index] for index in range(len(point)))
        try:
            objective, gradient, unregularized = evaluate(trial)
        except (ArithmeticError, ValueError, OverflowError):
            return None
        if (not isfinite(objective) or not isfinite(unregularized)
                or any(not isfinite(value) for value in gradient)):
            return None
        return trial, objective, tuple(gradient), unregularized

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

    previous_step = 0.0
    previous_value = (point, initial_objective, initial_gradient, 0.0)
    step = 1.0
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
        step *= 2.0
        if not isfinite(step) or step > 1e12:
            return None
    return None


@dataclass(frozen=True)
class FitResult:
    terminal_status: str
    converged: bool
    theta: tuple[float, ...]
    unregularized_mean_nll: float
    penalized_objective: float
    gradient_infinity_norm: float
    iterations: int
    regularization_lambda: float
    objective_scale: str
    solver: str
    message: str


class ExponentialFamily:
    """A normalized distribution over the complete unordered-subset support."""

    def __init__(self, table: UniformFeatureTable):
        self.table = table
        self.m = table.stats.population_size
        self.k = table.stats.selection_size
        self.dimension = len(table.stats.feature_names)
        if self.dimension == 0:
            raise ValueError("feature schema has no non-degenerate features")
        if table.multiplicity_sum != table.stats.support_count:
            raise ValueError("feature table does not cover the complete support")
        self._sampling_cache = {}

    def _theta(self, theta: Sequence[float]) -> tuple[float, ...]:
        values = _finite_vector(theta, "theta")
        if len(values) != self.dimension:
            raise ValueError(f"theta must have exactly {self.dimension} parameters")
        return values

    def _cell_terms(self, theta: tuple[float, ...]) -> tuple[float, ...]:
        terms = []
        for cell in self.table.cells:
            if cell.multiplicity <= 0:
                raise ValueError("feature-cell multiplicity must be positive")
            score = _dot(theta, cell.standardized_features)
            terms.append(log(cell.multiplicity) + score)
        return tuple(terms)

    def log_partition(self, theta: Sequence[float]) -> float:
        values = self._theta(theta)
        return logsumexp(self._cell_terms(values))

    def expected_features(self, theta: Sequence[float]) -> tuple[float, ...]:
        values = self._theta(theta)
        terms = self._cell_terms(values)
        normalizer = logsumexp(terms)
        probabilities = tuple(exp(term - normalizer) for term in terms)
        return tuple(
            fsum(probability * cell.standardized_features[index]
                 for probability, cell in zip(probabilities, self.table.cells))
            for index in range(self.dimension)
        )

    def log_probability(self, subset: Sequence[int], theta: Sequence[float]) -> float:
        values = self._theta(theta)
        canonical = validate_subset(subset, self.m, self.k)
        raw = extract_features(
            canonical, self.m, self.k,
            include_gap_variance=("gap_variance" in self.table.stats.candidate_feature_names),
        )
        standardized = self.table.stats.standardize(raw)
        result = _dot(values, standardized) - self.log_partition(values)
        if not isfinite(result) or result > 1e-12:
            raise ArithmeticError("computed log probability is non-finite or positive")
        return result

    def probability_sum(self, theta: Sequence[float]) -> float:
        """Sum probabilities over all support cells (including multiplicity)."""
        values = self._theta(theta)
        terms = self._cell_terms(values)
        normalizer = logsumexp(terms)
        return fsum(exp(term - normalizer) for term in terms)

    def sample(self, theta: Sequence[float], rng) -> tuple[int, ...]:
        """Draw one exact full-support categorical subset using an injected RNG."""
        values = self._theta(theta)
        if not callable(getattr(rng, "random", None)):
            raise TypeError("rng must expose a random() method")
        cached = self._sampling_cache.get(values)
        if cached is None:
            support = tuple(enumerate_support(self.m, self.k))
            log_scores = []
            include_gap = "gap_variance" in self.table.stats.candidate_feature_names
            for subset in support:
                raw = extract_features(subset, self.m, self.k, include_gap_variance=include_gap)
                log_scores.append(_dot(values, self.table.stats.standardize(raw)))
            maximum = max(log_scores)
            cumulative = []
            running = 0.0
            for score in log_scores:
                running += exp(score - maximum)
                cumulative.append(running)
            if not isfinite(running) or running <= 0.0:
                raise ArithmeticError("categorical sampler has invalid total weight")
            cached = (support, tuple(cumulative), running)
            self._sampling_cache[values] = cached
        support, cumulative, total = cached
        draw = rng.random()
        if not isinstance(draw, (int, float)) or not isfinite(float(draw)) or not 0.0 <= draw < 1.0:
            raise ValueError("rng.random() must return a finite value in [0, 1)")
        index = bisect_left(cumulative, float(draw) * total)
        return support[min(index, len(support) - 1)]

    def sample_many(self, count: int, theta: Sequence[float], rng) -> tuple[tuple[int, ...], ...]:
        """Draw count independent tickets with replacement; preserve duplicates."""
        if type(count) is not int or count < 1:
            raise ValueError("count must be a positive integer")
        return tuple(self.sample(theta, rng) for _ in range(count))

    def objective_and_gradient(
        self,
        theta: Sequence[float],
        observed_mean_features: Sequence[float],
        regularization_lambda: float = 1.0,
    ) -> tuple[float, tuple[float, ...], float]:
        values = self._theta(theta)
        observed = _finite_vector(observed_mean_features, "observed_mean_features")
        if len(observed) != self.dimension:
            raise ValueError("observed mean feature vector has the wrong dimension")
        if not isfinite(regularization_lambda) or regularization_lambda < 0:
            raise ValueError("regularization_lambda must be finite and nonnegative")
        log_z = self.log_partition(values)
        expected = self.expected_features(values)
        unregularized = log_z - _dot(values, observed)
        penalty = 0.5 * regularization_lambda * _dot(values, values)
        objective = unregularized + penalty
        gradient = tuple(
            expected[index] - observed[index] + regularization_lambda * values[index]
            for index in range(self.dimension)
        )
        if not isfinite(objective) or any(not isfinite(value) for value in gradient):
            raise ArithmeticError("non-finite objective or gradient")
        return objective, gradient, unregularized

    def fit(
        self,
        observations: Sequence[Sequence[int]],
        *,
        regularization_lambda: float = 1.0,
        max_iterations: int = 5000,
        gradient_tolerance: float = 1e-8,
        history_size: int = 10,
    ) -> FitResult:
        """Fit mean-NLL + L2 using the unbounded L-BFGS-B specialization.

        Parameters have no box constraints, so the L-BFGS-B active-set step
        reduces to the ordinary limited-memory BFGS two-loop recursion. A
        deterministic strong-Wolfe line search supplies the standard smooth,
        unbounded search step. Terminal failures are retained, never hidden.
        """
        if not observations:
            raise ValueError("at least one training observation is required")
        if type(max_iterations) is not int or max_iterations < 1:
            raise ValueError("max_iterations must be a positive integer")
        if type(history_size) is not int or history_size < 1:
            raise ValueError("history_size must be a positive integer")
        if not isfinite(gradient_tolerance) or gradient_tolerance <= 0:
            raise ValueError("gradient_tolerance must be finite and positive")
        if not isfinite(regularization_lambda) or regularization_lambda < 0:
            raise ValueError("regularization_lambda must be finite and nonnegative")

        feature_rows = []
        for observation in observations:
            canonical = validate_subset(observation, self.m, self.k)
            raw = extract_features(
                canonical, self.m, self.k,
                include_gap_variance=("gap_variance" in self.table.stats.candidate_feature_names),
            )
            feature_rows.append(self.table.stats.standardize(raw))
        observed_mean = tuple(
            fsum(row[index] for row in feature_rows) / len(feature_rows)
            for index in range(self.dimension)
        )

        theta = tuple(0.0 for _ in range(self.dimension))
        objective, gradient, unregularized = self.objective_and_gradient(
            theta, observed_mean, regularization_lambda
        )
        s_history: list[tuple[float, ...]] = []
        y_history: list[tuple[float, ...]] = []
        rho_history: list[float] = []
        status = "max_iterations"
        message = "maximum iteration count reached"
        iterations = 0

        for iteration in range(max_iterations + 1):
            grad_inf = max(abs(value) for value in gradient)
            if grad_inf <= gradient_tolerance:
                status = "converged"
                message = "gradient infinity norm reached tolerance"
                iterations = iteration
                break
            if iteration == max_iterations:
                iterations = iteration
                break

            q = list(gradient)
            alphas: list[float] = []
            for s_vec, y_vec, rho in zip(
                reversed(s_history), reversed(y_history), reversed(rho_history)
            ):
                alpha = rho * _dot(s_vec, q)
                alphas.append(alpha)
                q = [q[i] - alpha * y_vec[i] for i in range(self.dimension)]

            if s_history:
                sy = _dot(s_history[-1], y_history[-1])
                yy = _dot(y_history[-1], y_history[-1])
                scale = sy / yy if yy > 0 else 1.0
            else:
                scale = 1.0
            direction_seed = [scale * value for value in q]
            for (s_vec, y_vec, rho), alpha in zip(
                zip(s_history, y_history, rho_history), reversed(alphas)
            ):
                beta = rho * _dot(y_vec, direction_seed)
                direction_seed = [
                    direction_seed[i] + s_vec[i] * (alpha - beta)
                    for i in range(self.dimension)
                ]
            direction = tuple(-value for value in direction_seed)
            directional_derivative = _dot(gradient, direction)
            if not isfinite(directional_derivative) or directional_derivative >= 0:
                direction = tuple(-value for value in gradient)
                directional_derivative = -_dot(gradient, gradient)
                s_history.clear()
                y_history.clear()
                rho_history.clear()

            accepted = _strong_wolfe_search(
                lambda candidate: self.objective_and_gradient(
                    candidate, observed_mean, regularization_lambda
                ),
                theta,
                direction,
                objective,
                gradient,
            )
            if accepted is None:
                status = "line_search_failed"
                message = "strong-Wolfe line search could not find an acceptable step"
                iterations = iteration
                break

            new_theta, new_objective, new_gradient, new_unregularized = accepted
            s_vec = tuple(new_theta[i] - theta[i] for i in range(self.dimension))
            y_vec = tuple(new_gradient[i] - gradient[i] for i in range(self.dimension))
            curvature = _dot(s_vec, y_vec)
            if curvature > 1e-12 * (sum(value * value for value in s_vec) ** 0.5
                                        * sum(value * value for value in y_vec) ** 0.5):
                s_history.append(s_vec)
                y_history.append(y_vec)
                rho_history.append(1.0 / curvature)
                if len(s_history) > history_size:
                    s_history.pop(0)
                    y_history.pop(0)
                    rho_history.pop(0)
            theta, objective, gradient, unregularized = (
                new_theta, new_objective, new_gradient, new_unregularized
            )
            iterations = iteration + 1

        # Independent terminal recomputation is mandatory for readiness.
        final_objective, final_gradient, final_unregularized = self.objective_and_gradient(
            theta, observed_mean, regularization_lambda
        )
        gradient_inf = max(abs(value) for value in final_gradient)
        converged = status == "converged" and gradient_inf <= gradient_tolerance
        if not converged and status == "converged":
            status = "post_fit_validation_failed"
            message = "independent post-fit gradient check failed"
        return FitResult(
            terminal_status=status,
            converged=converged,
            theta=theta,
            unregularized_mean_nll=final_unregularized,
            penalized_objective=final_objective,
            gradient_infinity_norm=gradient_inf,
            iterations=iterations,
            regularization_lambda=regularization_lambda,
            objective_scale="mean_nll",
            solver="deterministic_unbounded_lbfgsb_strong_wolfe_v1",
            message=message,
        )
