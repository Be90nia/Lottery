"""Exhaustive uniform-support moments and exact feature-cell multiplicities."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from math import sqrt
from typing import TypeAlias

from .features import FeatureValue, extract_features, feature_names
from .support import enumerate_support, support_size

RawFeatureKey: TypeAlias = tuple[FeatureValue, ...]


@dataclass(frozen=True)
class FeatureStats:
    """Immutable uniform-support standardization metadata.

    Means and variances are retained as exact rational strings; standard
    deviations are float64 because square roots need not be rational.
    """
    population_size: int
    selection_size: int
    feature_schema_version: str
    candidate_feature_names: tuple[str, ...]
    feature_names: tuple[str, ...]
    support_count: int
    all_mean_fractions: tuple[str, ...]
    all_variance_fractions: tuple[str, ...]
    means: tuple[float, ...]
    standard_deviations: tuple[float, ...]
    zero_variance_features: tuple[str, ...]

    def standardize(self, raw: RawFeatureKey) -> tuple[float, ...]:
        if len(raw) != len(self.candidate_feature_names):
            raise ValueError("raw feature vector has the wrong dimension")
        result: list[float] = []
        for value, mean, scale in zip(raw, self._all_means, self._all_standard_deviations):
            if scale == 0.0:
                continue
            result.append((float(value) - mean) / scale)
        return tuple(result)

    @property
    def _all_means(self) -> tuple[float, ...]:
        return tuple(float(Fraction(value)) for value in self.all_mean_fractions)

    @property
    def _all_standard_deviations(self) -> tuple[float, ...]:
        return tuple(sqrt(float(Fraction(value))) for value in self.all_variance_fractions)


@dataclass(frozen=True)
class FeatureCell:
    """One distinct standardized feature vector and its exact support count."""
    standardized_features: tuple[float, ...]
    multiplicity: int


@dataclass(frozen=True)
class UniformFeatureTable:
    stats: FeatureStats
    cells: tuple[FeatureCell, ...]

    @property
    def multiplicity_sum(self) -> int:
        return sum(cell.multiplicity for cell in self.cells)


def _fraction_text(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def build_uniform_feature_table(
    m: int,
    k: int,
    *,
    include_gap_variance: bool,
    feature_schema_version: str = "lot-051-symmetric-v1",
) -> UniformFeatureTable:
    """Exhaustively enumerate support, moments and exact feature-cell counts."""
    expected = support_size(m, k)
    names = feature_names(k, include_gap_variance=include_gap_variance)
    counts: Counter[RawFeatureKey] = Counter()
    sums = [Fraction(0) for _ in names]
    sums_sq = [Fraction(0) for _ in names]
    seen = 0

    for subset in enumerate_support(m, k):
        raw = extract_features(subset, m, k, include_gap_variance=include_gap_variance)
        counts[raw] += 1
        seen += 1
        for index, value in enumerate(raw):
            exact = Fraction(value)
            sums[index] += exact
            sums_sq[index] += exact * exact

    if seen != expected or sum(counts.values()) != expected:
        raise RuntimeError("feature table does not cover the complete legal support")

    means_exact = tuple(total / expected for total in sums)
    variances_exact = tuple(
        max(Fraction(0), sums_sq[index] / expected - means_exact[index] ** 2)
        for index in range(len(names))
    )
    stds = tuple(sqrt(float(variance)) for variance in variances_exact)
    zero = tuple(name for name, scale in zip(names, stds) if scale == 0.0)
    stats = FeatureStats(
        population_size=m,
        selection_size=k,
        feature_schema_version=feature_schema_version,
        candidate_feature_names=names,
        feature_names=tuple(name for name, scale in zip(names, stds) if scale > 0.0),
        support_count=expected,
        all_mean_fractions=tuple(_fraction_text(value) for value in means_exact),
        all_variance_fractions=tuple(_fraction_text(value) for value in variances_exact),
        means=tuple(float(value) for value, scale in zip(means_exact, stds) if scale > 0.0),
        standard_deviations=tuple(scale for scale in stds if scale > 0.0),
        zero_variance_features=zero,
    )

    cells = tuple(
        FeatureCell(stats.standardize(raw), multiplicity)
        for raw, multiplicity in sorted(counts.items(), key=lambda item: item[0])
    )
    if sum(cell.multiplicity for cell in cells) != expected:
        raise RuntimeError("aggregated feature-cell multiplicities do not equal support size")
    return UniformFeatureTable(stats=stats, cells=cells)


def build_uniform_feature_stats(
    m: int,
    k: int,
    *,
    include_gap_variance: bool,
    feature_schema_version: str = "lot-051-symmetric-v1",
) -> FeatureStats:
    """Convenience API when callers need moments but not feature-cell vectors."""
    return build_uniform_feature_table(
        m, k,
        include_gap_variance=include_gap_variance,
        feature_schema_version=feature_schema_version,
    ).stats
