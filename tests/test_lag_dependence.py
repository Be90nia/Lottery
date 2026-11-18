import unittest

from lottery.lag_dependence import analyze, holm_adjust, rotate_time


def draw(draw_id, front, back):
    return {
        "draw_id": str(draw_id),
        "draw_date": f"2020-01-{draw_id:02d}",
        "front_numbers": front,
        "back_numbers": back,
    }


class LagDependenceTests(unittest.TestCase):
    def test_circular_rotation_direction(self):
        self.assertEqual(rotate_time(0b0001, 1, 4, 0b1111), 0b0010)

    def test_report_has_eight_holm_controlled_omnibus_tests(self):
        rows = [
            draw(i, [1, 2, 3, 4, 5], [1, 2])
            for i in range(1, 9)
        ]
        report = analyze(rows, "a" * 64)
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
            for item in report["omnibus_tests_holm"]
        ))

    def test_constant_features_do_not_create_nan_statistics(self):
        rows = [
            draw(i, [1, 2, 3, 4, 5], [1, 2])
            for i in range(1, 9)
        ]
        report = analyze(rows, "b" * 64)
        self.assertTrue(all(
            item["exact_circular_shift_p"] == 1.0
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
