"""Synthetic scalar-log checks for the 150M-cell capacity probe."""

import tempfile
import unittest
from pathlib import Path

from probe_single_gpu_capacity import assess_log, arena_mb, full_field_files


N = 536
CELLS = N**3


def metric(step: int, *, min_f: str = "0.01",
           mean_rho: str = "1.0", minima: bool = True) -> str:
    row = (f"TGV_METRICS step={step} time={step} cells={CELLS} "
           f"mean_rho={mean_rho} mean_kinetic=0.00001 "
           "init_linf=0 nonfinite=0")
    return row + (" min_rho=0.999 min_f=" + min_f if minima else "")


def log(steps: int, *, online: bool, final_minima: bool = True) -> str:
    rows = [f"Coarse STEP 1 ends. TIME = 1 Sum(Rho) = {CELLS}"]
    if online:
        rows.extend((metric(1),
                     f"Coarse STEP {steps // 2} ends. TIME = {steps // 2}",
                     metric(steps // 2)))
    rows.extend((f"Coarse STEP {steps} ends. TIME = {steps} "
                 f"Sum(Rho) = {CELLS}",
                 "TGV_PRECISION real_bytes=8",
                 metric(steps, minima=final_minima)))
    if not final_minima:
        rows.extend(f"FIELD_SUMMARY lev=0 comp={q} sum=1 norm2=1 "
                    "min=0.01 max=1 hash0=1 hash1=1"
                    for q in (0, *range(6, 25)))
    rows.extend((
        "[The         Arena] max space (MB) allocated spread across MPI: "
        "[31000 ... 31000]",
        "[The         Arena] max space (MB) used      spread across MPI: "
        "[30000 ... 30000]",
        "AMReX (26.11) finalized",
    ))
    return "\n".join(rows) + "\n"


class CapacityParserTest(unittest.TestCase):
    def assess(self, output: str, steps: int, online: bool) -> dict:
        return assess_log(output, N, steps, 1.0e-8, 8, online)

    def test_pilot_accepts_final_scalar_and_field_summary(self):
        result = self.assess(log(10, online=False, final_minima=False), 10, False)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["final_min_f"], 0.01)
        self.assertEqual(result["arena_max_used_mb"], 30000)

    def test_sustained_accepts_online_diagnostics(self):
        result = self.assess(log(100, online=True), 100, True)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["online_metric_steps"], [1, 50])

    def test_final_only_diagnostics_are_incomplete_for_sustained_run(self):
        result = self.assess(log(100, online=False), 100, True)
        self.assertEqual(result["status"], "incomplete")
        self.assertTrue(any("online TGV_METRICS" in item
                            for item in result["missing"]))

    def test_nonpositive_population_fails(self):
        output = log(100, online=True).replace(
            metric(50), metric(50, min_f="-0.01"))
        result = self.assess(output, 100, True)
        self.assertEqual(result["status"], "failed")
        self.assertIn("nonpositive population", result["problems"])

    def test_metric_mass_drift_fails(self):
        output = log(100, online=True).replace(
            metric(50), metric(50, mean_rho="1.0001"))
        result = self.assess(output, 100, True)
        self.assertEqual(result["status"], "failed")
        self.assertIn("TGV_METRICS mass drift exceeds tolerance",
                      result["problems"])

    def test_wrong_final_step_fails(self):
        result = self.assess(log(100, online=True), 101, True)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("final step 101" in item
                            for item in result["problems"]))

    def test_nonfinite_metric_fails(self):
        output = log(100, online=True).replace(
            "mean_kinetic=0.00001", "mean_kinetic=nan", 1)
        self.assertEqual(self.assess(output, 100, True)["status"], "failed")

    def test_wrong_precision_fails(self):
        output = log(100, online=True).replace(
            "TGV_PRECISION real_bytes=8", "TGV_PRECISION real_bytes=4")
        self.assertEqual(self.assess(output, 100, True)["status"], "failed")

    def test_repeated_matching_precision_is_valid(self):
        output = log(100, online=True).replace(
            "TGV_PRECISION real_bytes=8",
            "TGV_PRECISION real_bytes=8\nTGV_PRECISION real_bytes=8")
        self.assertEqual(self.assess(output, 100, True)["status"], "passed")

    def test_missing_arena_is_incomplete(self):
        output = log(100, online=True)
        output = "\n".join(line for line in output.splitlines()
                           if "[The         Arena]" not in line)
        self.assertEqual(self.assess(output, 100, True)["status"], "incomplete")

    def test_metrics_appended_after_run_are_not_online(self):
        output = log(100, online=True)
        early = metric(50)
        output = output.replace(early + "\n", "")
        output += early + "\n"
        result = self.assess(output, 100, True)
        self.assertEqual(result["status"], "failed")
        self.assertIn("TGV_METRICS step 50 was not emitted online",
                      result["problems"])

    def test_arena_and_full_field_detection(self):
        self.assertEqual(arena_mb(
            "[The Arena] space allocated (MB): 123\n", "allocated"), 123)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "plt00010").mkdir()
            (root / "plotfile100").mkdir()
            self.assertEqual(full_field_files(root), ["plotfile100", "plt00010"])


if __name__ == "__main__":
    unittest.main()
