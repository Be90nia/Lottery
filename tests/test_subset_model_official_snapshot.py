"""One-step pooled-model smoke run against the pinned official draw snapshot.

This is a computational integration smoke test, not LOT-055 confirmatory
validation, not ball-set-conditioned evaluation, and not a production forecast.
"""
import hashlib
import json
import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.subset_model import (
    BACK_POPULATION,
    BACK_SELECTION,
    FRONT_POPULATION,
    FRONT_SELECTION,
    ExponentialFamily,
    build_uniform_feature_table,
)


SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / "data/processed/draws-20261118.jsonl"
EXPECTED_SHA256 = "9f4cc51b76fd258dd056e0b86f675192d3d9a41c2901f771cab778c65ec2b6aa"
EXPECTED_ROWS = 2949


class OfficialSnapshotSubsetSmokeTests(unittest.TestCase):
    def test_fit_score_and_sample_latest_official_draw_without_lookahead(self):
        raw = SNAPSHOT_PATH.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        self.assertEqual(digest, EXPECTED_SHA256)
        rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]
        self.assertEqual(len(rows), EXPECTED_ROWS)
        self.assertEqual(rows[0]["draw_id"], "07001")
        self.assertEqual(rows[-1]["draw_id"], "26131")
        self.assertEqual(len({row["draw_id"] for row in rows}), EXPECTED_ROWS)

        previous_id = None
        previous_date = None
        for row in rows:
            draw_id = row["draw_id"]
            draw_date = row["draw_date"]
            self.assertTrue(isinstance(draw_id, str) and len(draw_id) == 5 and draw_id.isdigit())
            self.assertTrue(isinstance(draw_date, str) and len(draw_date) == 10)
            if previous_id is not None:
                self.assertGreater(draw_id, previous_id)
                self.assertGreater(draw_date, previous_date)
            front = row["front_numbers"]
            back = row["back_numbers"]
            self.assertEqual(len(front), FRONT_SELECTION)
            self.assertEqual(len(set(front)), FRONT_SELECTION)
            self.assertEqual(front, sorted(front))
            self.assertTrue(all(type(value) is int and 1 <= value <= FRONT_POPULATION for value in front))
            self.assertEqual(len(back), BACK_SELECTION)
            self.assertEqual(len(set(back)), BACK_SELECTION)
            self.assertEqual(back, sorted(back))
            self.assertTrue(all(type(value) is int and 1 <= value <= BACK_POPULATION for value in back))
            previous_id, previous_date = draw_id, draw_date

        training = rows[:-1]
        target = rows[-1]
        self.assertEqual(len(training), 2948)
        self.assertLess(training[-1]["draw_id"], target["draw_id"])

        front_table = build_uniform_feature_table(
            FRONT_POPULATION, FRONT_SELECTION, include_gap_variance=True
        )
        back_table = build_uniform_feature_table(
            BACK_POPULATION, BACK_SELECTION, include_gap_variance=False
        )
        front_model = ExponentialFamily(front_table)
        back_model = ExponentialFamily(back_table)

        front_fit = front_model.fit([tuple(row["front_numbers"]) for row in training])
        back_fit = back_model.fit([tuple(row["back_numbers"]) for row in training])
        self.assertTrue(front_fit.converged, msg=front_fit)
        self.assertTrue(back_fit.converged, msg=back_fit)

        front_logp = front_model.log_probability(target["front_numbers"], front_fit.theta)
        back_logp = back_model.log_probability(target["back_numbers"], back_fit.theta)
        front_uniform_nll = math.log(math.comb(FRONT_POPULATION, FRONT_SELECTION))
        back_uniform_nll = math.log(math.comb(BACK_POPULATION, BACK_SELECTION))
        front_nll = -front_logp
        back_nll = -back_logp

        front_rng = random.Random(20261118)
        back_rng = random.Random(20261119)
        front_samples = front_model.sample_many(5, front_fit.theta, front_rng)
        back_samples = back_model.sample_many(5, back_fit.theta, back_rng)
        tickets = [
            {"front": list(front), "back": list(back)}
            for front, back in zip(front_samples, back_samples)
        ]
        result = {
            "run_type": "one_step_pooled_model_smoke_not_confirmatory",
            "snapshot_sha256": digest,
            "snapshot_rows": len(rows),
            "snapshot_trust_status": "manifest_complete_not_officially_authenticated",
            "training_rows": len(training),
            "training_cutoff_draw_id": training[-1]["draw_id"],
            "target_draw_id": target["draw_id"],
            "front": {
                "terminal_status": front_fit.terminal_status,
                "iterations": front_fit.iterations,
                "gradient_inf_norm": front_fit.gradient_infinity_norm,
                "candidate_exact_set_nll": front_nll,
                "uniform_exact_set_nll": front_uniform_nll,
                "candidate_minus_uniform_nll": front_nll - front_uniform_nll,
                "theta": list(front_fit.theta),
            },
            "back": {
                "terminal_status": back_fit.terminal_status,
                "iterations": back_fit.iterations,
                "gradient_inf_norm": back_fit.gradient_infinity_norm,
                "candidate_exact_set_nll": back_nll,
                "uniform_exact_set_nll": back_uniform_nll,
                "candidate_minus_uniform_nll": back_nll - back_uniform_nll,
                "theta": list(back_fit.theta),
            },
            "sampled_tickets": tickets,
            "warning": "One target only; pooled equipment-blind model; not a confirmatory score, not three ball-set models, and not evidence of predictive advantage.",
        }
        print("SUBSET_MODEL_OFFICIAL_SMOKE=" + json.dumps(result, sort_keys=True))
        self.assertEqual(len(tickets), 5)
        self.assertTrue(all(len(ticket["front"]) == 5 and len(ticket["back"]) == 2 for ticket in tickets))


if __name__ == "__main__":
    unittest.main()
