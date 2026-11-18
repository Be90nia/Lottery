import unittest

from lottery.backtest import rolling_origin_backtest, _probabilities


def draw(draw_id, front, back):
    return {"draw_id": str(draw_id), "draw_date": f"2020-01-{draw_id:02d}",
            "front_numbers": front, "back_numbers": back, "source_id": "test"}


class BacktestTests(unittest.TestCase):
    def test_probability_mass_matches_pick_count(self):
        rows = [draw(1, [1, 2, 3, 4, 5], [1, 2]),
                draw(2, [2, 3, 4, 5, 6], [2, 3])]
        for model in ("uniform", "expanding", "ewma"):
            front = _probabilities(rows, "front_numbers", 35, 5, model=model)
            back = _probabilities(rows, "back_numbers", 12, 2, model=model)
            self.assertAlmostEqual(sum(front), 5)
            self.assertAlmostEqual(sum(back), 2)

    def test_backtest_is_strictly_time_ordered_and_reports_all_models(self):
        rows = [draw(i, [1, 2, 3, 4, 5], [1, 2]) for i in range(1, 8)]
        result = rolling_origin_backtest(rows, min_train=3)
        self.assertEqual(result["evaluated_draws"], 4)
        self.assertEqual(result["first_evaluation_draw"], "4")
        self.assertEqual(set(result["metrics"]), {"uniform", "expanding", "ewma"})
        era = result["calendar_era_stability"]["eras"]["2017-2021"]
        self.assertEqual(era["evaluation_draws"], 4)
        self.assertEqual(era["first_evaluation_draw"], "4")
        self.assertEqual(era["last_evaluation_draw"], "7")
        delta = era["paired_score_delta_vs_uniform"]["ewma"]["front"]["brier"]
        self.assertEqual(delta["replicates"], 1000)
        self.assertEqual(delta["block_length_draws"], 4)

    def test_duplicate_draw_ids_rejected(self):
        rows = [draw(1, [1, 2, 3, 4, 5], [1, 2]),
                draw(1, [2, 3, 4, 5, 6], [2, 3])]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            rolling_origin_backtest(rows, min_train=1)

    def test_invalid_duplicate_numbers_rejected(self):
        rows = [draw(1, [1, 1, 3, 4, 5], [1, 2]),
                draw(2, [2, 3, 4, 5, 6], [2, 3])]
        with self.assertRaisesRegex(ValueError, "invalid front_numbers"):
            rolling_origin_backtest(rows, min_train=1)


if __name__ == "__main__":
    unittest.main()
