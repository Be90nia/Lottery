import math
import sys
import unittest
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.subset_model import (
    BACK_SUPPORT_SIZE,
    FRONT_SUPPORT_SIZE,
    InvalidSubsetError,
    build_uniform_feature_table,
    enumerate_support,
    extract_features,
    support_size,
    validate_subset,
)


class SupportTests(unittest.TestCase):
    def test_full_lottery_support_cardinalities(self):
        self.assertEqual(FRONT_SUPPORT_SIZE, 324632)
        self.assertEqual(BACK_SUPPORT_SIZE, 66)
        self.assertEqual(support_size(8, 3), math.comb(8, 3))

    def test_small_support_is_complete_unique_and_lexicographic(self):
        values = list(enumerate_support(7, 3))
        self.assertEqual(len(values), math.comb(7, 3))
        self.assertEqual(len(set(values)), len(values))
        self.assertEqual(values, sorted(values))

    def test_rejects_bad_population_parameters(self):
        for m, k in ((True, 1), (5, True), (0, 0), (5, -1), (3, 4), (5.0, 2)):
            with self.subTest(m=m, k=k):
                with self.assertRaises(ValueError):
                    support_size(m, k)

    def test_subset_validation_never_repairs_input(self):
        for value in ((2, 1), (1, 1), (0, 2), (1, 9), (True, 2), (1.0, 2), (1,), "12"):
            with self.subTest(value=value):
                with self.assertRaises(InvalidSubsetError):
                    validate_subset(value, 8, 2)


class FeatureTests(unittest.TestCase):
    def test_hand_calculated_front_features(self):
        self.assertEqual(
            extract_features((1, 2, 4, 7, 10), 35, 5, include_gap_variance=True),
            (24, 2, 9, 1, Fraction(35, 16)),
        )

    def test_hand_calculated_back_features_omit_gap_variance(self):
        self.assertEqual(
            extract_features((3, 12), 12, 2, include_gap_variance=False),
            (15, 1, 9, 0),
        )

    def test_permutation_is_not_silently_canonicalized(self):
        with self.assertRaises(InvalidSubsetError):
            extract_features((10, 2, 4, 7, 1), 35, 5, include_gap_variance=True)

    def test_feature_schema_for_back_is_four_dimensions(self):
        table = build_uniform_feature_table(12, 2, include_gap_variance=False)
        self.assertEqual(table.stats.feature_names, ("sum", "odd_count", "range", "adjacent_count"))
        self.assertNotIn("gap_variance", table.stats.feature_names)


class UniformTableTests(unittest.TestCase):
    def test_exact_uniform_moments_on_toy_support(self):
        table = build_uniform_feature_table(5, 2, include_gap_variance=True)
        support = list(enumerate_support(5, 2))
        raw = [extract_features(item, 5, 2, include_gap_variance=True) for item in support]
        for index in range(len(table.stats.feature_names)):
            mean = sum(Fraction(row[index]) for row in raw) / len(raw)
            variance = sum((Fraction(row[index]) - mean) ** 2 for row in raw) / len(raw)
            self.assertEqual(table.stats.mean_fractions[index], f"{mean.numerator}/{mean.denominator}")
            self.assertEqual(table.stats.variance_fractions[index], f"{variance.numerator}/{variance.denominator}")

    def test_standardized_non_degenerate_features_have_zero_mean_unit_variance(self):
        table = build_uniform_feature_table(8, 3, include_gap_variance=True)
        for index, name in enumerate(table.stats.feature_names):
            if name in table.stats.zero_variance_features:
                continue
            weighted_mean = sum(
                cell.standardized_features[index] * cell.multiplicity for cell in table.cells
            ) / table.stats.support_count
            weighted_var = sum(
                (cell.standardized_features[index] ** 2) * cell.multiplicity for cell in table.cells
            ) / table.stats.support_count
            self.assertAlmostEqual(weighted_mean, 0.0, places=12)
            self.assertAlmostEqual(weighted_var, 1.0, places=12)

    def test_multiplicity_sum_equals_complete_support(self):
        front = build_uniform_feature_table(35, 5, include_gap_variance=True)
        back = build_uniform_feature_table(12, 2, include_gap_variance=False)
        self.assertEqual(front.multiplicity_sum, FRONT_SUPPORT_SIZE)
        self.assertEqual(back.multiplicity_sum, BACK_SUPPORT_SIZE)
        self.assertTrue(all(cell.multiplicity > 0 for cell in front.cells + back.cells))

    def test_back_zero_variance_feature_is_explicitly_omitted(self):
        table = build_uniform_feature_table(12, 2, include_gap_variance=True)
        self.assertIn("gap_variance", table.stats.zero_variance_features)
        self.assertEqual(len(table.stats.standard_deviations), 5)


if __name__ == "__main__":
    unittest.main()
