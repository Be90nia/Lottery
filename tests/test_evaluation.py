import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lottery.evaluation import (
    EvaluationGateError,
    build_evaluation_receipt,
    verify_evaluation_receipt, _digest,
)


def rows(count=240, candidate_delta=-0.02):
    result = []
    for i in range(count):
        models = {}
        for name, delta in (("candidate", candidate_delta), ("champion", 0.0), ("uniform", 0.0)):
            models[name] = {
                "front": {"brier": 0.2 + delta, "log_loss": 0.4 + delta},
                "back": {"brier": 0.3 + delta, "log_loss": 0.5 + delta},
            }
        result.append({"target_draw_id": f"26{i + 1:03d}", "model_scores": models})
    return result


class EvaluationGateTests(unittest.TestCase):
    def build(self, data=None, **kwargs):
        options = dict(candidate_model_id="candidate-v2", champion_model_id="champion-v1",
                       dataset_sha256="a" * 64, code_commit="b" * 40,
                       protocol_version="frozen-v1", min_targets=200,
                       replicates=1000, block_length=50, seed=7)
        options.update(kwargs)
        return build_evaluation_receipt(rows() if data is None else data, **options)

    def test_deterministic_receipt_and_hash(self):
        first = self.build()
        second = self.build()
        self.assertEqual(first, second)
        self.assertTrue(verify_evaluation_receipt(first))

    def test_clear_improvement_is_only_eligible_for_human_review(self):
        receipt = self.build()
        self.assertEqual(receipt["decision"], "eligible_for_human_review")
        self.assertFalse(receipt["production_ready"])
        self.assertFalse(receipt["automatic_promotion"])

    def test_regression_or_uncertainty_fails_closed(self):
        receipt = self.build(rows(candidate_delta=0.01))
        self.assertEqual(receipt["decision"], "rejected_or_inconclusive")

    def test_incomplete_coverage_rejected(self):
        with self.assertRaisesRegex(EvaluationGateError, "incomplete coverage"):
            self.build(rows(199))

    def test_thresholds_cannot_be_lowered_below_frozen_floor(self):
        with self.assertRaisesRegex(EvaluationGateError, "frozen gate requires"):
            self.build(min_targets=2)
        with self.assertRaisesRegex(EvaluationGateError, "frozen gate requires"):
            self.build(replicates=999)
        with self.assertRaisesRegex(EvaluationGateError, "frozen gate requires"):
            self.build(block_length=20)

    def test_score_rows_hash_and_evaluation_config_are_bound(self):
        receipt = self.build()
        self.assertEqual(len(receipt["score_rows_sha256"]), 64)
        self.assertEqual(receipt["evaluation_config"], {
            "min_targets": 200,
            "bootstrap_replicates": 1000,
            "block_length_draws": 50,
            "bootstrap_seed": 7,
        })
        self.assertTrue(verify_evaluation_receipt(receipt))

    def test_out_of_order_targets_rejected(self):
        data = rows()
        data[100]["target_draw_id"] = "26001"
        with self.assertRaisesRegex(EvaluationGateError, "strictly increasing"):
            self.build(data)

    def test_duplicate_target_rejected(self):
        data = rows()
        data[-1]["target_draw_id"] = data[0]["target_draw_id"]
        with self.assertRaisesRegex(EvaluationGateError, "duplicate target"):
            self.build(data)

    def test_missing_model_or_metric_rejected(self):
        data = rows()
        del data[0]["model_scores"]["uniform"]
        with self.assertRaisesRegex(EvaluationGateError, "must contain"):
            self.build(data)

    def test_invalid_numeric_score_rejected(self):
        data = rows()
        data[0]["model_scores"]["candidate"]["front"]["log_loss"] = float("nan")
        with self.assertRaisesRegex(EvaluationGateError, "invalid"):
            self.build(data)

    def test_holdout_scope_forbidden(self):
        with self.assertRaisesRegex(EvaluationGateError, "prospective holdout is forbidden"):
            self.build(scope="prospective_holdout")

    def test_recomputed_receipt_hash_cannot_lower_frozen_threshold(self):
        receipt = self.build()
        changed = copy.deepcopy(receipt)
        changed["evaluation_config"]["min_targets"] = 2
        body = {key: value for key, value in changed.items() if key != "receipt_sha256"}
        changed["receipt_sha256"] = _digest(body)
        with self.assertRaisesRegex(EvaluationGateError, "evaluation configuration is invalid"):
            verify_evaluation_receipt(changed)

    def test_recomputed_receipt_hash_cannot_mismatch_bootstrap_configuration(self):
        receipt = self.build()
        changed = copy.deepcopy(receipt)
        changed["comparisons"]["champion"]["front"]["brier"]["replicates"] = 10
        body = {key: value for key, value in changed.items() if key != "receipt_sha256"}
        changed["receipt_sha256"] = _digest(body)
        with self.assertRaisesRegex(EvaluationGateError, "configuration mismatch"):
            verify_evaluation_receipt(changed)

    def test_receipt_tampering_detected(self):
        receipt = self.build()
        changed = copy.deepcopy(receipt)
        changed["comparisons"]["champion"]["front"]["brier"]["mean_delta"] = 99
        with self.assertRaisesRegex(EvaluationGateError, "hash mismatch"):
            verify_evaluation_receipt(changed)

    def test_out_of_order_targets_rejected(self):
        data = rows()
        data[100], data[101] = data[101], data[100]
        with self.assertRaisesRegex(EvaluationGateError, "strictly increasing"):
            self.build(data)

    def test_non_integer_bootstrap_seed_rejected(self):
        with self.assertRaisesRegex(EvaluationGateError, "thresholds or seed"):
            self.build(seed="7")

    def test_cli_refuses_to_overwrite_score_input(self):
        with tempfile.TemporaryDirectory() as temp:
            scores_path = Path(temp) / "scores.json"
            original = json.dumps({"score_rows": rows()}, separators=(",", ":"))
            scores_path.write_text(original, encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, "scripts/evaluation_receipt.py", "build", str(scores_path),
                 "--candidate-model-id", "candidate-v2", "--champion-model-id", "champion-v1",
                 "--dataset-sha256", "a" * 64, "--code-commit", "b" * 40,
                 "--protocol-version", "frozen-v1", "--output", str(scores_path)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertIn("must not overwrite", completed.stderr)
            self.assertEqual(scores_path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
