import unittest

from lottery.lag_dependence import (
    _row_masks, _transition_matrices, analyze, holm_adjust,
)


def draw(draw_id, front, back):
    return {
        "draw_id": str(draw_id),
        "draw_date": f"2020-01-{draw_id:02d}",
        "front_numbers": front,
        "back_numbers": back,
    }


class LagDependenceTests(unittest.TestCase):
    def sample_rows(self):
        return [
            draw(1, [1, 2, 3, 4, 5], [1, 2]),
            draw(2, [2, 3, 4, 5, 6], [2, 3]),
            draw(3, [3, 4, 5, 6, 7], [3, 4]),
            draw(4, [4, 5, 6, 7, 8], [4, 5]),
            draw(5, [5, 6, 7, 8, 9], [5, 6]),
            draw(6, [6, 7, 8, 9, 10], [6, 7]),
            draw(7, [7, 8, 9, 10, 11], [7, 8]),
            draw(8, [8, 9, 10, 11, 12], [8, 9]),
        ]

    def test_row_masks_preserve_number_totals_under_permutation(self):
        rows = self.sample_rows()
        original = _row_masks(rows)
        shuffled = _row_masks(rows, [7, 6, 5, 4, 3, 2, 1, 0])
        for zone in ("front", "back"):
            self.assertEqual(
                [mask.bit_count() for mask in original[zone]],
                [mask.bit_count() for mask in shuffled[zone]],
            )

    def test_transition_matrix_direction_is_previous_to_current(self):
        rows = self.sample_rows()
        masks = _row_masks(rows)
        matrix = _transition_matrices(masks["front"], len(rows))[1]
        self.assertGreaterEqual(matrix[0][1], 1)

    def test_report_has_eight_holm_controlled_omnibus_tests(self):
        report = analyze(self.sample_rows(), "a" * 64, permutations=99)
        self.assertEqual(report["draw_count"], 8)
        self.assertEqual(len(report["omnibus_tests_holm"]), 8)
        self.assertEqual(
            {item["zone"] for item in report["omnibus_tests_holm"]},
            {"front", "back"},
        )
        self.assertEqual(
            {item["lag"] for item in report["omnibus_tests_holm"]},
            {1, 2, 3, 4},
        )
        self.assertTrue(all(
            0 <= item["p_value_holm"] <= 1
            and item["monte_carlo_standard_error"] >= 0
            for item in report["omnibus_tests_holm"]
        ))

    def test_constant_features_do_not_create_nan_statistics(self):
        rows = [
            draw(i, [1, 2, 3, 4, 5], [1, 2])
            for i in range(1, 9)
        ]
        report = analyze(rows, "b" * 64, permutations=99)
        self.assertTrue(all(
            item["p_value"] == 1.0
            for item in report["omnibus_tests_holm"]
        ))

    def test_holm_adjustment_is_monotone_in_sorted_p_values(self):
        items = [
            {"p_value": 0.03},
            {"p_value": 0.001},
            {"p_value": 0.02},
        ]
        holm_adjust(items)
        ordered = sorted(items, key=lambda item: item["p_value"])
        adjusted = [item["p_value_holm"] for item in ordered]
        self.assertEqual(adjusted, sorted(adjusted))
        self.assertTrue(all(value <= 1 for value in adjusted))


if __name__ == "__main__":
    unittest.main()
