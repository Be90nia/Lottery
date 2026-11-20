"""Exact unordered-subset probability model primitives.

The package is intentionally isolated from the legacy LOT-042 marginal forecast
pipeline. It contains no user-facing prediction endpoint.
"""
from .artifact import ArtifactValidationError, canonicalize, create_artifact, verify_artifact
from .conditional_poisson import CalibrationResult, ConditionalPoisson
from .exponential import ExponentialFamily, FitResult, logsumexp
from .features import BASE_FEATURE_NAMES, GAP_VARIANCE_FEATURE, extract_features, feature_names
from .support import (
    BACK_POPULATION,
    BACK_SELECTION,
    BACK_SUPPORT_SIZE,
    FRONT_POPULATION,
    FRONT_SELECTION,
    FRONT_SUPPORT_SIZE,
    InvalidSubsetError,
    enumerate_support,
    support_size,
    validate_subset,
)
from .uniform import FeatureCell, FeatureStats, UniformFeatureTable, build_uniform_feature_stats, build_uniform_feature_table

__all__ = [
    "ArtifactValidationError", "canonicalize", "create_artifact", "verify_artifact", "CalibrationResult", "ConditionalPoisson", "ExponentialFamily", "FitResult", "logsumexp", "BACK_POPULATION", "BACK_SELECTION", "BACK_SUPPORT_SIZE",
    "BASE_FEATURE_NAMES", "FeatureCell", "FeatureStats", "FRONT_POPULATION",
    "FRONT_SELECTION", "FRONT_SUPPORT_SIZE", "GAP_VARIANCE_FEATURE",
    "InvalidSubsetError", "UniformFeatureTable", "build_uniform_feature_stats",
    "build_uniform_feature_table", "enumerate_support", "extract_features",
    "feature_names", "support_size", "validate_subset",
]
