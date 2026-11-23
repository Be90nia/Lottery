"""Verified exact-set probability evaluation from immutable fitted artifacts."""
from __future__ import annotations

import hashlib
import math
from typing import Any

from .subset_model.artifact import canonicalize
from .subset_model import ConditionalPoisson, ExponentialFamily, build_uniform_feature_table
from .subset_model.lifecycle import ChampionLifecycle


class FrozenArtifactEvaluationError(ValueError):
    """The frozen artifact cannot produce a verified full-support distribution."""


def distribution_identity(artifact_id: str, artifact: dict[str, Any]) -> str:
    body = {
        "artifact_id": artifact_id,
        "artifact_schema": artifact.get("artifact_schema"),
        "model_family": artifact.get("model_family"),
        "zone": artifact.get("zone"),
        "support": artifact.get("support"),
        "feature_schema_hash": artifact.get("feature_schema_hash"),
        "model_configuration_hash": artifact.get("model_configuration_hash"),
        "parameters": artifact.get("parameters"),
        "normalization": artifact.get("normalization"),
    }
    return hashlib.sha256(canonicalize(body)).hexdigest()


class FrozenArtifactEvaluator:
    """Load only content-addressed lifecycle artifacts and evaluate exact subsets."""

    def __init__(self, lifecycle: ChampionLifecycle):
        self.lifecycle = lifecycle
        self._cache: dict[str, tuple[dict[str, Any], Any, float]] = {}

    def _load(self, artifact_id: str) -> tuple[dict[str, Any], Any, float]:
        if not isinstance(artifact_id, str) or not artifact_id.startswith("sha256:"):
            raise FrozenArtifactEvaluationError("forecast artifact ID must be content-addressed")
        # Re-read and verify immutable storage on every evaluation; an in-memory
        # cache must never conceal later on-disk tampering or object replacement.
        artifact = self.lifecycle._load_artifact(artifact_id)
        cached = self._cache.get(artifact_id)
        if cached is not None:
            if canonicalize(cached[0]) != canonicalize(artifact):
                raise FrozenArtifactEvaluationError("immutable artifact bytes changed after initial verification")
            return cached
        zone = artifact.get("zone")
        m, k = (35, 5) if zone == "front" else (12, 2) if zone == "back" else (0, 0)
        if not m or artifact.get("support", {}).get("support_count") != math.comb(m, k):
            raise FrozenArtifactEvaluationError("artifact support does not match the legal exact-subset space")
        family = artifact.get("model_family")
        parameters = artifact.get("parameters")
        normalization = artifact.get("normalization")
        if not isinstance(parameters, dict) or not isinstance(normalization, dict):
            raise FrozenArtifactEvaluationError("artifact parameters or normalization envelope is missing")
        if family == "conditional_poisson":
            if normalization.get("method") != "exact_conditional_poisson_log_space_dp":
                raise FrozenArtifactEvaluationError("conditional-Poisson artifact has an unsupported normalizer")
            weights = parameters.get("centered_log_weights")
            if not isinstance(weights, list) or len(weights) != m:
                raise FrozenArtifactEvaluationError("conditional-Poisson artifact weights are malformed")
            model = ConditionalPoisson(weights, k)
            log_partition = model.log_normalizer
            probability_sum = model.probability_sum()
        elif family == "complete_subset_exponential":
            if normalization.get("method") != "full_support_logsumexp":
                raise FrozenArtifactEvaluationError("exponential artifact has an unsupported normalizer")
            schema = artifact.get("feature_schema")
            if not isinstance(schema, dict):
                raise FrozenArtifactEvaluationError("exponential artifact feature schema is missing")
            candidates = schema.get("candidate_names")
            names = schema.get("names")
            if not isinstance(candidates, list) or not isinstance(names, list):
                raise FrozenArtifactEvaluationError("exponential artifact feature names are malformed")
            table = build_uniform_feature_table(
                m, k,
                include_gap_variance=("gap_variance" in candidates),
                feature_schema_version=schema.get("version", "lot-051-symmetric-v1"),
            )
            if (
                list(table.stats.feature_names) != names
                or list(table.stats.candidate_feature_names) != candidates
                or list(table.stats.zero_variance_features) != schema.get("zero_variance_features")
                or list(table.stats.all_means) != schema.get("uniform_means")
                or list(table.stats.all_standard_deviations) != schema.get("uniform_population_stds")
            ):
                raise FrozenArtifactEvaluationError("artifact feature statistics do not reproduce from complete support")
            theta = parameters.get("theta")
            if not isinstance(theta, list):
                raise FrozenArtifactEvaluationError("exponential artifact theta is malformed")
            model = ExponentialFamily(table)
            log_partition = model.log_partition(theta)
            probability_sum = model.probability_sum(theta)
            model = (model, tuple(theta))
        else:
            raise FrozenArtifactEvaluationError("unsupported immutable artifact model family")
        declared = normalization.get("log_partition")
        if (
            isinstance(declared, bool) or not isinstance(declared, (int, float))
            or not math.isfinite(float(declared))
            or abs(float(declared) - log_partition) > 1e-8
            or not math.isfinite(probability_sum)
            or abs(probability_sum - 1.0) > 1e-10
        ):
            raise FrozenArtifactEvaluationError("full-support normalization verification failed")
        result = (artifact, model, log_partition)
        self._cache[artifact_id] = result
        return result

    def evaluate(self, forecast: dict[str, Any], subset: list[int]) -> dict[str, Any]:
        artifact_id = "sha256:" + forecast["artifact_sha256"]
        artifact, model, _ = self._load(artifact_id)
        if (
            artifact.get("zone") != forecast.get("zone")
            or artifact.get("model_family") != forecast.get("model_family")
            or artifact.get("training_snapshot_sha256") != forecast.get("training_snapshot_sha256")
            or artifact.get("training_cutoff_draw_id") != forecast.get("training_last_draw_id")
        ):
            raise FrozenArtifactEvaluationError("forecast provenance differs from immutable artifact")
        if artifact["model_family"] == "conditional_poisson":
            log_probability = model.log_probability(subset)
        else:
            family, theta = model
            log_probability = family.log_probability(subset, theta)
        if not math.isfinite(log_probability) or log_probability >= 0.0:
            raise FrozenArtifactEvaluationError("exact-set log probability is invalid")
        return {
            "artifact_sha256": forecast["artifact_sha256"],
            "normalization_verified": True,
            "log_probability": log_probability,
        }

    def distribution_sha256(self, artifact_id: str) -> str:
        artifact, _, _ = self._load(artifact_id)
        return distribution_identity(artifact_id, artifact)
