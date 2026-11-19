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
    if any(not math.isfinite(value) for value in items):
        if all(value == -math.inf for value in items):
            return -math.inf
        raise ValueError("log-sum-exp inputs must be finite or all negative infinity")
    maximum = max(items)
    return maximum + math.log(math.fsum(math.exp(value - maximum) for value in items))


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
