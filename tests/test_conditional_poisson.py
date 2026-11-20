import unittest

from lottery.conditional_poisson import ConditionalPoisson


class ConditionalPoissonCalibrationTests(unittest.TestCase):
    def test_near_stationary_float64_objective_plateau_still_converges(self):
        # Regression fixture for the historical reported-index EWMA fit at
        # draw 24009. The final Armijo decrease is below one float64 ULP;
        # calibration must use a bounded roundoff envelope and strong-Wolfe
        # curvature, rather than stall above the registered 1e-8 tolerance.
        target = [
            0.16017510254396758, 0.1611401785283237, 0.139659921488918,
            0.1359630432940723, 0.15555093732338443, 0.13700075525027966,
            0.1578925505808904, 0.16366680567766112, 0.13979100783114323,
            0.1251110350575263, 0.16391489825454603, 0.1426264617061025,
            0.14725028894003464, 0.129652454008409, 0.1251622903120403,
            0.14094735637680605, 0.11968602754719541, 0.1365627523466471,
            0.15387228023683566, 0.14038663976901095, 0.14355355646868073,
            0.15735785946067507, 0.11361206066578453, 0.1255734592192581,
            0.15091040448223034, 0.15479261290114193, 0.1293970611709547,
            0.1470502082736747, 0.13800231562880913, 0.16804326001035405,
            0.1468259765006516, 0.1315560115228683, 0.13107731091987324,
            0.14445137875156738, 0.14178373694968177,
        ]
        result = ConditionalPoisson.calibrate(
            target, 5, tolerance=1e-8, max_iterations=5000, history_size=10
        )
        self.assertTrue(result.converged, msg=result.message)
        self.assertEqual(result.terminal_status, "converged")
        self.assertLessEqual(result.maximum_absolute_residual, 1e-8)
        self.assertLessEqual(result.gradient_infinity_norm, 1e-8)
        self.assertEqual(len(result.centered_log_weights), 35)


if __name__ == "__main__":
    unittest.main()
