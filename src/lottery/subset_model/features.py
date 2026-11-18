"""Permutation-invariant symmetric features for unordered lottery subsets."""
from __future__ import annotations

from fractions import Fraction
from typing import TypeAlias

from .support import validate_subset

FeatureValue: TypeAlias = int | Fraction

BASE_FEATURE_NAMES = ("sum", "odd_count", "range", "adjacent_count")
GAP_VARIANCE_FEATURE = "gap_variance"


def feature_names(k: int, *, include_gap_variance: bool) -> tuple[str, ...]:
    if type(k) is not int or k < 1:
        raise ValueError("k must be a positive integer")
    if include_gap_variance and k > 1:
        return BASE_FEATURE_NAMES + (GAP_VARIANCE_FEATURE,)
    return BASE_FEATURE_NAMES


def extract_features(
    subset: tuple[int, ...] | list[int],
    m: int,
    k: int,
    *,
    include_gap_variance: bool,
) -> tuple[FeatureValue, ...]:
    """Extract the frozen symmetric feature vector from a canonical subset.

    gap_var is the population variance of the k-1 internal gaps. Fraction keeps
    this feature exact during uniform-support aggregation.
    """
    values = validate_subset(subset, m, k)
    gaps = tuple(right - left for left, right in zip(values, values[1:]))
    base: tuple[FeatureValue, ...] = (
        sum(values),
        sum(value % 2 for value in values),
        values[-1] - values[0] if k > 1 else 0,
        sum(gap == 1 for gap in gaps),
    )
    if not include_gap_variance or k <= 1:
        return base
    gap_mean = Fraction(sum(gaps), len(gaps))
    gap_variance = sum((Fraction(gap) - gap_mean) ** 2 for gap in gaps) / len(gaps)
    return base + (gap_variance,)
