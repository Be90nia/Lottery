"""Exact complete-subset exponential-family probabilities and fitting."""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from math import exp, isfinite, log
from typing import Sequence

from .features import extract_features
from .support import enumerate_support, validate_subset
from .uniform import UniformFeatureTable


def _finite_vector(values: Sequence[float], name: str) -> tuple[float, ...]:
    try:
        raw = tuple(values)
    except TypeError as exc:
        raise ValueError(f"{name} must be a finite numeric sequence") from exc
    if any(type(value) not in (int, float) for value in raw):
        raise ValueError(f"{name} must contain only int/float values (booleans and strings are invalid)")
    try:
        result = tuple(float(value) for value in raw)
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
    return maximum + log(sum(exp(value - maximum) for value in vals))


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("vector dimensions do not match")
    return sum(a * b for a, b in zip(left, right))


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
            sum(probability * cell.standardized_features[index]
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
        return sum(exp(term - normalizer) for term in terms)

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
        if type(draw) not in (int, float) or not isfinite(float(draw)) or not 0.0 <= draw < 1.0:
            raise ValueError("rng.random() must return a finite int/float in [0, 1) (not bool)")
        index = bisect_right(cumulative, float(draw) * total)
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
        if (type(regularization_lambda) not in (int, float)
                or not isfinite(regularization_lambda) or regularization_lambda < 0):
            raise ValueError("regularization_lambda must be a finite nonnegative int/float (not bool)")
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
        gradient_tolerance: float = 1e-7,
        history_size: int = 10,
    ) -> FitResult:
        """Fit mean-NLL + L2 with the frozen SciPy L-BFGS-B solver.

        Parameters are unconstrained, so no box bounds are supplied. SciPy,
        NumPy, stopping tolerances, history size, and line-search budget are
        pinned by the project environment and recorded in the result.
        """
        if not observations:
            raise ValueError("at least one training observation is required")
        if type(max_iterations) is not int or max_iterations < 1:
            raise ValueError("max_iterations must be a positive integer")
        if type(history_size) is not int or history_size < 1:
            raise ValueError("history_size must be a positive integer")
        if (type(gradient_tolerance) not in (int, float)
                or not isfinite(gradient_tolerance) or gradient_tolerance <= 0):
            raise ValueError("gradient_tolerance must be a finite positive int/float (not bool)")
        if (type(regularization_lambda) not in (int, float)
                or not isfinite(regularization_lambda) or regularization_lambda < 0):
            raise ValueError("regularization_lambda must be a finite nonnegative int/float (not bool)")

        feature_rows = []
        for observation in observations:
            canonical = validate_subset(observation, self.m, self.k)
            raw = extract_features(
                canonical, self.m, self.k,
                include_gap_variance=("gap_variance" in self.table.stats.candidate_feature_names),
            )
            feature_rows.append(self.table.stats.standardize(raw))
        observed_mean = tuple(
            sum(row[index] for row in feature_rows) / len(feature_rows)
            for index in range(self.dimension)
        )

        try:
            import scipy
            from scipy.optimize import minimize
        except ImportError as exc:
            raise RuntimeError(
                "SciPy is required for the preregistered L-BFGS-B subset-model solver"
            ) from exc

        def objective_and_jacobian(parameters):
            theta_values = tuple(float(value) for value in parameters)
            objective, gradient, _ = self.objective_and_gradient(
                theta_values, observed_mean, regularization_lambda
            )
            return objective, list(gradient)

        result = minimize(
            objective_and_jacobian,
            x0=[0.0] * self.dimension,
            method="L-BFGS-B",
            jac=True,
            bounds=None,
            options={
                "maxiter": max_iterations,
                "maxfun": max_iterations * 100,
                "maxcor": history_size,
                "maxls": 60,
                "ftol": 0.0,
                "gtol": float(gradient_tolerance),
            },
        )

        theta = tuple(float(value) for value in result.x)
        final_objective, final_gradient, final_unregularized = self.objective_and_gradient(
            theta, observed_mean, regularization_lambda
        )
        gradient_inf = max(abs(value) for value in final_gradient)
        converged = gradient_inf <= gradient_tolerance
        message = str(result.message)
        if converged:
            status = "converged"
        elif result.status == 1:
            status = "max_iterations"
        elif result.status == 2:
            status = "line_search_failed"
        elif result.success:
            status = "post_fit_validation_failed"
            message = "SciPy reported success but independent gradient validation failed: " + message
        else:
            status = "optimizer_failed"

        return FitResult(
            terminal_status=status,
            converged=converged,
            theta=theta,
            unregularized_mean_nll=final_unregularized,
            penalized_objective=final_objective,
            gradient_infinity_norm=gradient_inf,
            iterations=int(result.nit),
            regularization_lambda=regularization_lambda,
            objective_scale="mean_nll",
            solver=f"scipy.optimize.L-BFGS-B/{scipy.__version__}",
            message=message,
        )
