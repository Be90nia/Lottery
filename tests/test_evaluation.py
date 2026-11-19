import copy
import unittest

from lottery.evaluation import (
    EvaluationGateError,
    build_evaluation_receipt,
    verify_evaluation_receipt,
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
        result.append({"target_draw_id": f"26{i:04d}", "model_scores": models})
    return result


class EvaluationGateTests(unittest.TestCase):
    def build(self, data=None, **kwargs):
        options = dict(candidate_model_id="candidate-v2", champion_model_id="champion-v1",
                       dataset_sha256="a" * 64, code_commit="b" * 40,
                       protocol_version="frozen-v1", min_targets=200,
                       replicates=200, block_length=20, seed=7)
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

    def test_receipt_tampering_detected(self):
        receipt = self.build()
        changed = copy.deepcopy(receipt)
        changed["comparisons"]["champion"]["front"]["brier"]["mean_delta"] = 99
        with self.assertRaisesRegex(EvaluationGateError, "hash mismatch"):
            verify_evaluation_receipt(changed)



