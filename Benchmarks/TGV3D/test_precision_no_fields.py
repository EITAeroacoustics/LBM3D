import unittest

from check_precision_no_fields import parse_metric


class MetricTimeTest(unittest.TestCase):
    @staticmethod
    def metric(time):
        return (f"TGV_METRICS step=10 time={time} cells=64000000 "
                "mean_rho=1 mean_kinetic=1e-5 init_linf=0 nonfinite=0\n")

    def test_roundoff_at_non_power_of_two_grid(self):
        self.assertEqual(parse_metric(self.metric("1.5999999999999999"),
                                      400, 10)["step"], 10)

    def test_wrong_time_still_fails(self):
        with self.assertRaises(ValueError):
            parse_metric(self.metric("1.6001"), 400, 10)


if __name__ == "__main__":
    unittest.main()
