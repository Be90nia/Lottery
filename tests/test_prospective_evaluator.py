from __future__ import annotations

from math import comb, log
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
