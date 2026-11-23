from __future__ import annotations

from math import comb, log\nfrom lottery.subset_model import ExponentialFamily, build_uniform_feature_table
import unittest

from lottery.prospective_evaluator import (
    FrozenArtifactEvaluationError,
    FrozenArtifactEvaluator,
    distribution_identity,
)


class FakeLifecycle:
    def __init__(self, artifact):
        self.artifact = artifact

    def _load_artifact(self, artifact_id):
        return self.artifact


def conditional_artifact():
    m, k = 12, 2
    return {
        "artifact_id": "sha256:" + "a" * 64,
        "artifact_schema": "lottery.subset-probability-model/v1",
        "model_family": "conditional_poisson",
        "zone": "back",
        "population_size": m,
        "selection_size": k,
        "support": {
            "population_size": m, "selection_size": k,
            "support_count": comb(m, k), "subset_order": "lexicographic_ascending",
        },
        "parameters": {"centered_log_weights": [0.0] * m},
        "normalization": {
            "method": "exact_conditional_poisson_log_space_dp",
            "log_partition": log(comb(m, k)),
            "numeric_dtype": "float64",
        },
        "training_snapshot_sha256": "b" * 64,
        "training_cutoff_draw_id": "26130",
    }


class FrozenArtifactEvaluatorTests(unittest.TestCase):
    def test_conditional_poisson_uses_full_support_and_exact_set_nll(self):
        artifact = conditional_artifact()
        evaluator = FrozenArtifactEvaluator(FakeLifecycle(artifact))
        forecast = {
            "artifact_sha256": "a" * 64,
            "zone": "back",
            "model_family": "conditional_poisson",
            "training_snapshot_sha256": "b" * 64,
            "training_last_draw_id": "26130",
        }
        result = evaluator.evaluate(forecast, [1, 12])
        self.assertEqual(result["artifact_sha256"], "a" * 64)
        self.assertTrue(result["normalization_verified"])
        self.assertAlmostEqual(result["log_probability"], -log(comb(12, 2)), places=12)
        self.assertEqual(
            evaluator.distribution_sha256("sha256:" + "a" * 64),
            distribution_identity("sha256:" + "a" * 64, artifact),
        )

    def test_exponential_family_rebuilds_feature_schema_and_full_support(self):
        table = build_uniform_feature_table(12, 2, include_gap_variance=False)
        family = ExponentialFamily(table)
        theta = [0.0] * len(table.stats.feature_names)
        artifact = {
            "artifact_id": "sha256:" + "c" * 64,
            "artifact_schema": "lottery.subset-probability-model/v1",
            "model_family": "complete_subset_exponential",
            "zone": "back",
            "population_size": 12,
            "selection_size": 2,
            "support": {
                "population_size": 12, "selection_size": 2,
                "support_count": comb(12, 2), "subset_order": "lexicographic_ascending",
            },
            "feature_schema": {
                "version": table.stats.feature_schema_version,
                "names": list(table.stats.feature_names),
                "candidate_names": list(table.stats.candidate_feature_names),
                "uniform_means": list(table.stats.all_means),
                "uniform_population_stds": list(table.stats.all_standard_deviations),
                "zero_variance_features": list(table.stats.zero_variance_features),
            },
            "parameters": {"theta": theta},
            "normalization": {
                "method": "full_support_logsumexp",
                "log_partition": family.log_partition(theta),
                "numeric_dtype": "float64",
            },
            "training_snapshot_sha256": "d" * 64,
            "training_cutoff_draw_id": "26130",
        }
        evaluator = FrozenArtifactEvaluator(FakeLifecycle(artifact))
        forecast = {
            "artifact_sha256": "c" * 64,
            "zone": "back",
            "model_family": "complete_subset_exponential",
            "training_snapshot_sha256": "d" * 64,
            "training_last_draw_id": "26130",
        }
        result = evaluator.evaluate(forecast, [1, 12])
        self.assertTrue(result["normalization_verified"])
        self.assertAlmostEqual(result["log_probability"], -log(comb(12, 2)), places=12)

    def test_zone_training_and_normalization_mismatch_fail_closed(self):
        artifact = conditional_artifact()
        evaluator = FrozenArtifactEvaluator(FakeLifecycle(artifact))
        forecast = {
            "artifact_sha256": "a" * 64, "zone": "front",
            "model_family": "conditional_poisson",
            "training_snapshot_sha256": "b" * 64,
            "training_last_draw_id": "26130",
        }
        with self.assertRaises(FrozenArtifactEvaluationError):
            evaluator.evaluate(forecast, [1, 2])
        artifact = conditional_artifact()
        artifact["normalization"]["log_partition"] += 0.1
        evaluator = FrozenArtifactEvaluator(FakeLifecycle(artifact))
        forecast["zone"] = "back"
        with self.assertRaisesRegex(FrozenArtifactEvaluationError, "normalization"):
            evaluator.evaluate(forecast, [1, 2])


if __name__ == "__main__":
    unittest.main()
