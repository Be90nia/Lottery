"""Exact probability primitives for unordered fixed-size lottery subsets.

This module is intentionally isolated from the legacy marginal forecast and
LOT-042 ledger. It contains no equipment, ball-set, prize, sales, draw-order,
or future features. All probability calculations use the complete legal
subset support.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import itertools
import math
import random
from typing import Iterable, Sequence

FRONT = (35, 5)
BACK = (12, 2)
FEATURE_SCHEMA_VERSION = "lottery-set-features/v1"
_FEATURE_NAMES = ("sum", "odd", "range", "adjacent", "gap_var")


@dataclass(frozen=True)
class FeatureSchema:
    population_size: int
    selection_size: int
    names: tuple[str, ...]
    version: str = FEATURE_SCHEMA_VERSION

    @classmethod
    def for_support(cls, m: int, k: int) -> "FeatureSchema":
        _validate_dimensions(m, k)
        names = _FEATURE_NAMES
        if k == 2:
            names = _FEATURE_NAMES[:4]
        return cls(m, k, names)


@dataclass(frozen=True)
class UniformFeatureStats:
    schema: FeatureSchema
    means: tuple[float, ...]
    population_stds: tuple[float, ...]
    omitted_zero_variance: tuple[str, ...]
    support_count: int


@dataclass(frozen=True)
class FeatureCells:
    schema: FeatureSchema
    stats: UniformFeatureStats
    cells: tuple[tuple[tuple[float, ...], int], ...]
    support_count: int


def _validate_dimensions(m: int, k: int) -> None:
    if type(m) is not int or type(k) is not int:
        raise ValueError("population_size and selection_size must be integers")
    if m < 1 or k < 0 or k > m:
        raise ValueError("require population_size >= 1 and 0 <= selection_size <= population_size")


def enumerate_support(m: int, k: int) -> Iterable[tuple[int, ...]]:
    """Yield every legal subset in deterministic lexicographic order."""
    _validate_dimensions(m, k)
    return itertools.combinations(range(1, m + 1), k)


def validate_subset(subset: Sequence[int], m: int, k: int) -> tuple[int, ...]:
    """Validate canonical ascending input; never silently sort or deduplicate."""
    _validate_dimensions(m, k)
    if isinstance(subset, (str, bytes)) or not isinstance(subset, Sequence):
        raise ValueError("subset must be a finite integer sequence")
    values = tuple(subset)
    if len(values) != k:
        raise ValueError(f"subset must contain exactly {k} values")
    if any(type(value) is not int for value in values):
        raise ValueError("subset members must be integers (booleans are not accepted)")
    if any(value < 1 or value > m for value in values):
        raise ValueError(f"subset members must be in 1..{m}")
    if any(left >= right for left, right in zip(values, values[1:])):
        raise ValueError("subset must be strictly ascending and contain no duplicates")
    return values


def extract_features(subset: Sequence[int], schema: FeatureSchema) -> tuple[float, ...]:
    values = validate_subset(subset, schema.population_size, schema.selection_size)
    gaps = tuple(b - a for a, b in zip(values, values[1:]))
    gap_mean = sum(gaps) / len(gaps) if gaps else 0.0
    gap_var = sum((gap - gap_mean) ** 2 for gap in gaps) / len(gaps) if gaps else 0.0
    raw = {
        "sum": float(sum(values)),
        "odd": float(sum(value % 2 for value in values)),
        "range": float(values[-1] - values[0]) if len(values) > 1 else 0.0,
        "adjacent": float(sum(gap == 1 for gap in gaps)),
        "gap_var": float(gap_var),
    }
    return tuple(raw[name] for name in schema.names)


def uniform_feature_stats(m: int, k: int, schema: FeatureSchema | None = None) -> UniformFeatureStats:
    """Compute exact-support population moments by exhaustive enumeration."""
    schema = schema or FeatureSchema.for_support(m, k)
    if (schema.population_size, schema.selection_size) != (m, k):
        raise ValueError("feature schema dimensions do not match support")
    count = 0
    sums = [0.0] * len(schema.names)
    sums_sq = [0.0] * len(schema.names)
    for subset in enumerate_support(m, k):
        features = extract_features(subset, schema)
        count += 1
        for index, value in enumerate(features):
            sums[index] += value
            sums_sq[index] += value * value
    expected = math.comb(m, k)
    if count != expected:
        raise ArithmeticError("support enumeration count mismatch")
    means = tuple(value / count for value in sums)
    variances = tuple(max(0.0, sums_sq[i] / count - means[i] * means[i]) for i in range(len(means)))
    stds = tuple(math.sqrt(value) for value in variances)
    kept_names, kept_means, kept_stds, omitted = [], [], [], []
    for name, mean, std in zip(schema.names, means, stds):
        if std == 0.0:
            omitted.append(name)
        else:
            kept_names.append(name)
            kept_means.append(mean)
            kept_stds.append(std)
    effective_schema = FeatureSchema(m, k, tuple(kept_names), schema.version)
    return UniformFeatureStats(effective_schema, tuple(kept_means), tuple(kept_stds),
                               tuple(omitted), count)


def standardized_features(subset: Sequence[int], stats: UniformFeatureStats) -> tuple[float, ...]:
    original_names = tuple(name for name in _FEATURE_NAMES if name in stats.schema.names or name in stats.omitted_zero_variance)
    original_schema = FeatureSchema(stats.schema.population_size, stats.schema.selection_size, original_names)
    raw = extract_features(subset, original_schema)
    kept = tuple(value for name, value in zip(original_names, raw) if name not in stats.omitted_zero_variance)
    return tuple((value - mean) / std for value, mean, std in zip(kept, stats.means, stats.population_stds))


def aggregate_feature_cells(m: int, k: int, stats: UniformFeatureStats | None = None) -> FeatureCells:
    stats = stats or uniform_feature_stats(m, k)
    counts: Counter[tuple[float, ...]] = Counter()
    for subset in enumerate_support(m, k):
        counts[standardized_features(subset, stats)] += 1
    cells = tuple(sorted(counts.items(), key=lambda item: item[0]))
    total = sum(multiplicity for _, multiplicity in cells)
    expected = math.comb(m, k)
    if total != expected or stats.support_count != expected:
        raise ArithmeticError("feature-cell multiplicities do not cover the complete support")
    return FeatureCells(stats.schema, stats, cells, total)


def _logsumexp(values: Iterable[float]) -> float:
    items = tuple(values)
    if not items:
        return -math.inf
    if any(math.isnan(value) or value == math.inf for value in items):
        raise ValueError("log-sum-exp inputs must be finite or negative infinity")
    finite = tuple(value for value in items if value != -math.inf)
    if not finite:
        return -math.inf
    maximum = max(finite)
    return maximum + math.log(math.fsum(math.exp(value - maximum) for value in finite))


def _validate_theta(theta: Sequence[float], dimension: int) -> tuple[float, ...]:
    values = tuple(theta)
    if len(values) != dimension:
        raise ValueError("theta dimension does not match feature schema")
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        raise ValueError("theta must contain only finite real numbers")
    return tuple(float(value) for value in values)


def log_partition(theta: Sequence[float], cells: FeatureCells) -> float:
    parameters = _validate_theta(theta, len(cells.schema.names))
    terms = []
    for features, multiplicity in cells.cells:
        dot = math.fsum(a * b for a, b in zip(parameters, features))
        terms.append(math.log(multiplicity) + dot)
    result = _logsumexp(terms)
    if not math.isfinite(result):
        raise ArithmeticError("non-finite log partition")
    return result


def log_probability(subset: Sequence[int], theta: Sequence[float], cells: FeatureCells) -> float:
    values = validate_subset(subset, cells.schema.population_size, cells.schema.selection_size)
    parameters = _validate_theta(theta, len(cells.schema.names))
    features = standardized_features(values, cells.stats)
    logp = math.fsum(a * b for a, b in zip(parameters, features)) - log_partition(parameters, cells)
    if not math.isfinite(logp):
        raise ArithmeticError("non-finite subset log probability")
    return logp


def conditional_poisson_log_dp(log_weights: Sequence[float], k: int) -> list[list[float]]:
    """Return log elementary-symmetric-polynomial prefix DP."""
    weights = tuple(log_weights)
    m = len(weights)
    _validate_dimensions(m, k)
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in weights):
        raise ValueError("log weights must be finite real numbers")
    dp = [[-math.inf] * (k + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = 0.0
    for i in range(1, m + 1):
        for j in range(1, min(i, k) + 1):
            dp[i][j] = _logsumexp((dp[i - 1][j], float(weights[i - 1]) + dp[i - 1][j - 1]))
    return dp


def conditional_poisson_log_normalizer(log_weights: Sequence[float], k: int) -> float:
    dp = conditional_poisson_log_dp(log_weights, k)
    result = dp[len(log_weights)][k]
    if not math.isfinite(result):
        raise ArithmeticError("conditional-Poisson support has non-finite normalizer")
    return result


def conditional_poisson_marginals(log_weights: Sequence[float], k: int) -> tuple[float, ...]:
    """Compute exact inclusion marginals using prefix/suffix log-DP."""
    weights = tuple(float(value) for value in log_weights)
    m = len(weights)
    _validate_dimensions(m, k)
    if any(not math.isfinite(value) for value in weights):
        raise ValueError("log weights must be finite")
    prefix = conditional_poisson_log_dp(weights, k)
    suffix = conditional_poisson_log_dp(tuple(reversed(weights)), k)
    log_z = prefix[m][k]
    marginals = []
    for index, log_weight in enumerate(weights):
        terms = []
        for left_count in range(k):
            right_count = k - 1 - left_count
            left = prefix[index][left_count] if left_count <= index else -math.inf
            right_items = m - index - 1
            right = suffix[right_items][right_count] if right_count <= right_items else -math.inf
            if left == -math.inf or right == -math.inf:
                continue
            terms.append(left + right)
        log_excluded = _logsumexp(terms)
        probability = math.exp(log_weight + log_excluded - log_z)
        if not math.isfinite(probability) or probability < 0.0 or probability > 1.0 + 1e-12:
            raise ArithmeticError("invalid inclusion marginal")
        marginals.append(min(1.0, probability))
    if abs(math.fsum(marginals) - k) > 1e-10:
        raise ArithmeticError("inclusion marginals do not sum to selection size")
    return tuple(marginals)


def conditional_poisson_log_probability(subset: Sequence[int], log_weights: Sequence[float], k: int) -> float:
    values = validate_subset(subset, len(log_weights), k)
    weights = tuple(float(value) for value in log_weights)
    if any(not math.isfinite(value) for value in weights):
        raise ValueError("log weights must be finite")
    return math.fsum(weights[value - 1] for value in values) - conditional_poisson_log_normalizer(weights, k)


def sample_conditional_poisson(log_weights: Sequence[float], k: int, rng: random.Random) -> tuple[int, ...]:
    """Exact backward sampler; RNG is explicitly injected by the caller."""
    if not isinstance(rng, random.Random):
        raise TypeError("rng must be an injected random.Random instance")
    weights = tuple(float(value) for value in log_weights)
    dp = conditional_poisson_log_dp(weights, k)
    m, remaining, chosen = len(weights), k, []
    for i in range(m, 0, -1):
        if remaining == 0:
            break
        if remaining == i:
            chosen.extend(range(1, i + 1))
            remaining = 0
            break
        probability = math.exp(weights[i - 1] + dp[i - 1][remaining - 1] - dp[i][remaining])
        if rng.random() < probability:
            chosen.append(i)
            remaining -= 1
    if remaining != 0:
        raise ArithmeticError("backward sampler terminated with an incomplete subset")
    return tuple(sorted(chosen))


def sample_subsets(log_weights: Sequence[float], k: int, count: int, *, seed: int) -> tuple[tuple[int, ...], ...]:
    if type(count) is not int or count < 0:
        raise ValueError("count must be a non-negative integer")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    rng = random.Random(seed)
    return tuple(sample_conditional_poisson(log_weights, k, rng) for _ in range(count))


@dataclass(frozen=True)
class CalibrationResult:
    status: str
    log_weights: tuple[float, ...]
    target_marginals: tuple[float, ...]
    achieved_marginals: tuple[float, ...]
    max_abs_residual: float
    iterations: int
    objective: float
    termination_reason: str

    @property
    def forecast_ready(self) -> bool:
        return self.status == "converged" and self.max_abs_residual <= 1e-8


def _solve_linear_system(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    """Deterministic Gaussian elimination with partial pivoting."""
    n = len(rhs)
    augmented = [list(matrix[i]) + [rhs[i]] for i in range(n)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(augmented[row][column]))
        pivot_value = augmented[pivot][column]
        if not math.isfinite(pivot_value) or abs(pivot_value) < 1e-14:
            raise ArithmeticError("singular calibration Hessian")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        scale = augmented[column][column]
        for j in range(column, n + 1):
            augmented[column][j] /= scale
        for row in range(n):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor:
                for j in range(column, n + 1):
                    augmented[row][j] -= factor * augmented[column][j]
    solution = [augmented[i][n] for i in range(n)]
    if any(not math.isfinite(value) for value in solution):
        raise ArithmeticError("non-finite calibration Newton step")
    return solution


def _pairwise_inclusion(log_weights: Sequence[float], k: int,
                        marginals: Sequence[float]) -> list[list[float]]:
    weights = tuple(log_weights)
    m = len(weights)
    log_z = conditional_poisson_log_normalizer(weights, k)
    matrix = [[0.0] * m for _ in range(m)]
    for i in range(m):
        matrix[i][i] = marginals[i]
        for j in range(i + 1, m):
            reduced = tuple(value for index, value in enumerate(weights) if index not in (i, j))
            if k < 2:
                pair = 0.0
            else:
                log_pair = weights[i] + weights[j] + conditional_poisson_log_normalizer(reduced, k - 2) - log_z
                pair = math.exp(log_pair)
            matrix[i][j] = matrix[j][i] = pair
    return matrix


def _calibration_objective(log_weights: Sequence[float], target: Sequence[float], k: int) -> float:
    return conditional_poisson_log_normalizer(log_weights, k) - math.fsum(
        eta * marginal for eta, marginal in zip(log_weights, target)
    )


def calibrate_weighted_subset(target_marginals: Sequence[float], k: int, *,
                              tolerance: float = 1e-8, max_iterations: int = 200) -> CalibrationResult:
    """Fit centered log weights to exact fixed-size inclusion marginals.

    The convex dual is solved by damped Newton steps in the zero-sum gauge.
    Failure is returned as a non-ready receipt; targets are never clipped or
    renormalized.
    """
    target = tuple(float(value) for value in target_marginals)
    m = len(target)
    _validate_dimensions(m, k)
    if type(max_iterations) is not int or max_iterations < 1:
        raise ValueError("max_iterations must be a positive integer")
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("tolerance must be finite and positive")
    if any(not math.isfinite(value) or not 0.0 < value < 1.0 for value in target):
        raise ValueError("target marginals must be finite and strictly interior")
    if abs(math.fsum(target) - k) > 1e-10:
        raise ValueError("target marginals must sum to selection size within 1e-10")
    if k == 0 or k == m:
        raise ValueError("interior marginal calibration is undefined for boundary selection sizes")

    eta = [0.0] * m
    last_objective = _calibration_objective(eta, target, k)
    for iteration in range(max_iterations + 1):
        achieved = conditional_poisson_marginals(eta, k)
        residual = [achieved[i] - target[i] for i in range(m)]
        max_residual = max(abs(value) for value in residual)
        if max_residual <= tolerance:
            return CalibrationResult("converged", tuple(eta), target, achieved,
                                     max_residual, iteration, last_objective,
                                     "marginal_residual_tolerance")
        if iteration == max_iterations:
            return CalibrationResult("max_iterations", tuple(eta), target, achieved,
                                     max_residual, iteration, last_objective,
                                     "iteration_limit")
        pair = _pairwise_inclusion(eta, k, achieved)
        covariance = [[pair[i][j] - achieved[i] * achieved[j] for j in range(m)]
                      for i in range(m)]
        # KKT system fixes the redundant additive log-weight degree of freedom.
        kkt = [row + [1.0] for row in covariance]
        kkt.append([1.0] * m + [0.0])
        rhs = [-value for value in residual] + [0.0]
        try:
            direction = _solve_linear_system(kkt, rhs)[:m]
        except ArithmeticError:
            return CalibrationResult("solver_failed", tuple(eta), target, achieved,
                                     max_residual, iteration, last_objective,
                                     "singular_or_nonfinite_hessian")
        directional = math.fsum(residual[i] * direction[i] for i in range(m))
        if not math.isfinite(directional) or directional >= 0.0:
            return CalibrationResult("solver_failed", tuple(eta), target, achieved,
                                     max_residual, iteration, last_objective,
                                     "non_descent_newton_direction")
        step = 1.0
        accepted = False
        while step >= 2.0 ** -30:
            candidate = [eta[i] + step * direction[i] for i in range(m)]
            center = math.fsum(candidate) / m
            candidate = [value - center for value in candidate]
            try:
                objective = _calibration_objective(candidate, target, k)
            except (ValueError, ArithmeticError, OverflowError):
                objective = math.inf
            if math.isfinite(objective) and objective <= last_objective + 1e-4 * step * directional:
                eta = candidate
                last_objective = objective
                accepted = True
                break
            step *= 0.5
        if not accepted:
            return CalibrationResult("solver_failed", tuple(eta), target, achieved,
                                     max_residual, iteration, last_objective,
                                     "line_search_failed")
    raise AssertionError("unreachable calibration state")


@dataclass(frozen=True)
class ExponentialFit:
    status: str
    theta: tuple[float, ...]
    unregularized_mean_nll: float
    penalized_objective: float
    gradient_inf_norm: float
    iterations: int
    termination_reason: str
    cells: FeatureCells

    @property
    def forecast_ready(self) -> bool:
        return (self.status == "converged" and math.isfinite(self.penalized_objective)
                and math.isfinite(self.gradient_inf_norm) and self.gradient_inf_norm <= 1e-8)

    def score_log_probability(self, subset: Sequence[int]) -> float:
        if not self.forecast_ready:
            raise RuntimeError("non-converged exponential fit is not scoreable")
        return log_probability(subset, self.theta, self.cells)


def exponential_objective_gradient(theta: Sequence[float],
                                   training_subsets: Sequence[Sequence[int]],
                                   cells: FeatureCells, *, regularization: float = 1.0
                                   ) -> tuple[float, tuple[float, ...], float]:
    """Mean-NLL objective, analytic gradient, and unregularized mean NLL."""
    if not training_subsets:
        raise ValueError("training subsets must not be empty")
    if not math.isfinite(regularization) or regularization < 0.0:
        raise ValueError("regularization must be finite and non-negative")
    parameters = _validate_theta(theta, len(cells.schema.names))
    observed = [standardized_features(subset, cells.stats) for subset in training_subsets]
    count = len(observed)
    mean_features = tuple(math.fsum(row[j] for row in observed) / count
                          for j in range(len(parameters)))
    log_z = log_partition(parameters, cells)
    mean_dot = math.fsum(parameters[j] * mean_features[j] for j in range(len(parameters)))
    mean_nll = log_z - mean_dot
    weighted_cells = []
    for features, multiplicity in cells.cells:
        log_mass = math.log(multiplicity) + math.fsum(a * b for a, b in zip(parameters, features)) - log_z
        weighted_cells.append((features, math.exp(log_mass)))
    expected = tuple(math.fsum(probability * features[j] for features, probability in weighted_cells)
                     for j in range(len(parameters)))
    gradient = tuple(expected[j] - mean_features[j] + regularization * parameters[j]
                     for j in range(len(parameters)))
    objective = mean_nll + 0.5 * regularization * math.fsum(value * value for value in parameters)
    if not math.isfinite(objective) or any(not math.isfinite(value) for value in gradient):
        raise ArithmeticError("non-finite exponential-family objective or gradient")
    return objective, gradient, mean_nll


def fit_exponential(training_subsets: Sequence[Sequence[int]], cells: FeatureCells, *,
                    regularization: float = 1.0, max_iterations: int = 5000,
                    gradient_tolerance: float = 1e-8) -> ExponentialFit:
    """Fit the frozen L-BFGS-B objective; SciPy must be supplied by a locked runtime."""
    if regularization != 1.0:
        raise ValueError("the preregistered regularization is fixed at lambda=1.0")
    if max_iterations != 5000 or gradient_tolerance != 1e-8:
        raise ValueError("optimizer settings differ from the frozen preregistration")
    try:
        from scipy.optimize import minimize
    except ImportError as exc:
        raise RuntimeError("SciPy L-BFGS-B is unavailable; install only from the LOT-066 hash-locked dependency set") from exc

    initial = [0.0] * len(cells.schema.names)

    def objective(theta: Sequence[float]) -> tuple[float, list[float]]:
        value, gradient, _ = exponential_objective_gradient(
            theta, training_subsets, cells, regularization=regularization
        )
        return value, list(gradient)

    result = minimize(
        objective, initial, method="L-BFGS-B", jac=True,
        options={"maxiter": max_iterations, "gtol": gradient_tolerance, "ftol": 0.0},
    )
    theta = tuple(float(value) for value in result.x)
    try:
        objective_value, gradient, mean_nll = exponential_objective_gradient(
            theta, training_subsets, cells, regularization=regularization
        )
    except (ValueError, ArithmeticError, OverflowError):
        return ExponentialFit("post_fit_validation_failed", theta, math.inf, math.inf,
                              math.inf, int(getattr(result, "nit", 0)),
                              "independent_recomputation_failed", cells)
    gradient_norm = max((abs(value) for value in gradient), default=0.0)
    converged = bool(result.success) and gradient_norm <= gradient_tolerance
    status = "converged" if converged else (
        "max_iterations" if int(getattr(result, "nit", 0)) >= max_iterations else "solver_failed"
    )
    return ExponentialFit(status, theta, mean_nll, objective_value, gradient_norm,
                          int(getattr(result, "nit", 0)), str(result.message), cells)


def marginal_inclusion_targets(training_rows: Sequence[dict[str, object]], zone: str, *,
                               family: str, alpha: float = 100.0,
                               half_life: float = 100.0) -> tuple[float, ...]:
    """Frozen expanding/EWMA marginal formulas, using training rows only."""
    if zone not in ("front", "back"):
        raise ValueError("zone must be front or back")
    if not training_rows:
        raise ValueError("training history must not be empty")
    if alpha != 100.0:
        raise ValueError("the preregistered shrinkage mass is fixed at alpha=100")
    if family not in ("expanding", "ewma"):
        raise ValueError("family must be expanding or ewma")
    if not math.isfinite(half_life) or half_life != 100.0:
        raise ValueError("the preregistered EWMA half-life is fixed at 100 draws")
    field, m, k = ("front_numbers", 35, 5) if zone == "front" else ("back_numbers", 12, 2)
    counts = [0.0] * m
    total_weight = 0.0
    for index, row in enumerate(training_rows):
        lag = len(training_rows) - index - 1
        weight = 1.0 if family == "expanding" else 2.0 ** (-lag / half_life)
        subset = validate_subset(row[field], m, k)
        total_weight += weight
        for number in subset:
            counts[number - 1] += weight
    denominator = total_weight + alpha
    return tuple((count + alpha * k / m) / denominator for count in counts)


def fit_weighted_subset_baseline(training_rows: Sequence[dict[str, object]], zone: str, *,
                                 family: str) -> CalibrationResult:
    targets = marginal_inclusion_targets(training_rows, zone, family=family)
    k = 5 if zone == "front" else 2
    return calibrate_weighted_subset(targets, k)
