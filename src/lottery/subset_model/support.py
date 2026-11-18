"""Exact support enumeration and strict canonical-subset validation."""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from itertools import combinations
from math import comb


class InvalidSubsetError(ValueError):
    """Raised when a subset is not a canonical legal k-subset."""


def _positive_or_nonnegative_int(value: object, name: str, *, allow_zero: bool = False) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer (bool is not accepted)")
    lower = 0 if allow_zero else 1
    if value < lower:
        raise ValueError(f"{name} must be >= {lower}")
    return value


def support_size(m: int, k: int) -> int:
    """Return C(m, k), validating the finite population parameters."""
    _positive_or_nonnegative_int(m, "m")
    _positive_or_nonnegative_int(k, "k", allow_zero=True)
    if k > m:
        raise ValueError("k must not exceed m")
    return comb(m, k)


def validate_subset(subset: Sequence[int], m: int, k: int) -> tuple[int, ...]:
    """Validate and return an already-canonical ascending subset.

    Deliberately does not sort, deduplicate, coerce, or repair malformed input.
    """
    support_size(m, k)
    if isinstance(subset, (str, bytes, bytearray)) or not isinstance(subset, Sequence):
        raise InvalidSubsetError("subset must be a non-string sequence")
    if len(subset) != k:
        raise InvalidSubsetError(f"subset must contain exactly {k} members")
    values = tuple(subset)
    for value in values:
        if type(value) is not int:
            raise InvalidSubsetError("subset members must be integers (bool is not accepted)")
        if not 1 <= value <= m:
            raise InvalidSubsetError(f"subset members must be in 1..{m}")
    if any(left >= right for left, right in zip(values, values[1:])):
        raise InvalidSubsetError("subset must be strictly increasing and contain no duplicates")
    return values


def enumerate_support(m: int, k: int) -> Iterator[tuple[int, ...]]:
    """Yield every legal subset once in canonical lexicographic order."""
    expected = support_size(m, k)
    emitted = 0
    for subset in combinations(range(1, m + 1), k):
        emitted += 1
        yield subset
    if emitted != expected:  # Defensive invariant; itertools should guarantee this.
        raise RuntimeError(f"support enumeration mismatch: expected {expected}, got {emitted}")


FRONT_POPULATION = 35
FRONT_SELECTION = 5
BACK_POPULATION = 12
BACK_SELECTION = 2
FRONT_SUPPORT_SIZE = support_size(FRONT_POPULATION, FRONT_SELECTION)
BACK_SUPPORT_SIZE = support_size(BACK_POPULATION, BACK_SELECTION)
