import math
import unittest

from lottery.lag_model import lag_probabilities, rolling_origin_lag_backtest


def draw(draw_id, front, back):
    return {
        "draw_id": str(draw_id),
        "draw_date": f"2020-01-{draw_id:02d}",
        "front_numbers": front,
        "back_numbers": back,
    }


class LagModelTests(unittest.TestCase):
    def sample_rows(self, count=12):
        return [
            draw(
                i,
                [((i + j - 1) % 35) + 1 for j in range(5)],
                [((i + j - 1) % 12) + 1 for j in range(2)],
            )
            for i in range(1, count + 1)
        ]

    def test_probabilities_sum_to_legal_pick_count(self):
        rows = self.sample_rows()
        front, front_theta, _ = lag_probabilities(rows[:8], "front_numbers", 35, 5)
        back, back_theta, _ = lag_probabilities(rows[:8], "back_numbers", 12, 2)
        self.assertAlmostEqual(sum(front), 5.0, places=8)
        self.assertAlmostEqual(sum(back), 2.0, places=8)
        self.assertTrue(all(0 < p < 1 for p in front + back))
        self.assertTrue(all(math.isfinite(value) for value in front_theta + back_theta))

    def test_prediction_uses_only_four_prior_draws(self):
        rows = self.sample_rows()
        first, _, _ = lag_probabilities(rows[:8], "front_numbers", 35, 5)
        second, _, _ = lag_probabilities(rows[:8], "front_numbers", 35, 5)
        self.assertEqual(first, second)

    def test_rolling_backtest_uses_same_targets_and_reports_all_baselines(self):
        result = rolling_origin_lag_backtest(self.sample_rows(), min_train=8)
        self.assertEqual(result["evaluated_draws"], 4)
        self.assertEqual(result["first_evaluation_draw"], "9")
        self.assertEqual(result["last_evaluation_draw"], "12")
        self.assertEqual(
            set(result["paired_score_delta_vs_baselines"]),
            {"uniform", "expanding", "ewma"},
        )
        self.assertEqual(
            set(result["metrics"]["lag_logistic"]),
            {"front", "back"},
        )
        self.assertEqual(
            result["settings"]["lags"],
            [1, 2, 3, 4],
        )
        self.assertIn("eligible_for_promotion", result["promotion_gate"])

    def test_rejects_insufficient_training_history(self):
        with self.assertRaisesRegex(ValueError, "min_train"):
            rolling_origin_lag_backtest(self.sample_rows(), min_train=4)


if __name__ == "__main__":
    unittest.main()
