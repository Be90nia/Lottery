from __future__ import annotations

import math
import unittest

from lottery.subset_model import ExponentialFamily, build_uniform_feature_table, enumerate_support


class ExactInclusionMarginalTests(unittest.TestCase):
    def setUp(self):
        self.table = build_uniform_feature_table(8, 3, include_gap_variance=True)
        self.model = ExponentialFamily(self.table)

    def test_uniform_parameters_produce_uniform_item_marginals(self):
        theta = [0.0] * self.model.dimension
        marginals = self.model.inclusion_marginals(theta)
        self.assertEqual(len(marginals), 8)
        for value in marginals:
            self.assertAlmostEqual(value, 3 / 8, places=12)
        self.assertAlmostEqual(sum(marginals), 3.0, places=12)

    def test_feature_cell_item_counts_reconcile_to_complete_support(self):
        self.assertEqual(self.table.multiplicity_sum, math.comb(8, 3))
        for item in range(8):
            count = sum(cell.item_inclusion_counts[item] for cell in self.table.cells)
            self.assertEqual(count, math.comb(7, 2))

    def test_nonuniform_marginals_match_exhaustive_support_oracle(self):
        theta = [0.17, -0.09, 0.11, 0.04, -0.13]
        marginals = self.model.inclusion_marginals(theta)
        support = tuple(enumerate_support(8, 3))
        probabilities = [math.exp(self.model.log_probability(subset, theta)) for subset in support]
        oracle = [
            sum(probability for subset, probability in zip(support, probabilities) if item in subset)
            for item in range(1, 9)
        ]
        for actual, expected in zip(marginals, oracle):
            self.assertAlmostEqual(actual, expected, places=12)
        self.assertAlmostEqual(sum(marginals), 3.0, places=12)


if __name__ == "__main__":
    unittest.main()
