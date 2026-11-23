"""CPU-only checks for the TGV test entry point."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import run_tests


class TestTgvAgent(unittest.TestCase):
    def test_plan_only_records_unrun_matrix_and_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "quick-1"
            result = subprocess.run(
                [sys.executable, str(run_tests.HERE / "run_tests.py"),
                 "--mode", "quick", "--run-root", str(root), "--plan-only"],
                text=True, capture_output=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            plan = json.loads((root / "plan.json").read_text())
            report = json.loads((root / "result.json").read_text())
            history = json.loads((Path(temporary) / "history.json").read_text())
            self.assertEqual(plan["agent_version"], run_tests.VERSION)
            self.assertEqual(len(plan["tasks"]), 4)
            self.assertEqual([len(row["commands"]) for row in plan["tasks"]],
                             [0, 6, 3, 3])
            self.assertEqual(report["status"], "not_run")
            self.assertTrue(all(row["status"] == "not_run" for row in
                                report["tasks"]))
            self.assertEqual(history["runs"][0]["status"], "not_run")

    def test_timed_run_requires_final_mass_and_no_field_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            log = directory / "run.log"
            log.write_text("LBM_DIRECTIONAL_HALO active=1\n"
                           "Coarse STEP 600 ends. TIME = 600 DT = 1 "
                           "Sum(Rho) = 16777216\n"
                           "AMReX (26.11) finalized\n")
            row = {"gpus": 1, "repeat": 1, "log": str(log),
                   "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}
            passed, evidence = run_tests.timing_diagnostics({"runs": [row]},
                                                              "strong")
            self.assertTrue(passed, evidence)
            (directory / "plt00000").mkdir()
            passed, evidence = run_tests.timing_diagnostics({"runs": [row]},
                                                              "strong")
            self.assertFalse(passed)
            self.assertIn("full-field output found", evidence[0]["problems"])

    def test_prebuilt_binary_verification_does_not_require_cmake(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "build-check"
            result = subprocess.run(
                [sys.executable, str(run_tests.HERE / "run_tests.py"),
                 "--mode", "quick", "--only", "build_summary",
                 "--summary-binary", sys.executable,
                 "--run-root", str(root)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            report = json.loads((root / "result.json").read_text())
            self.assertEqual(report["status"], "not_run")
            self.assertEqual(report["tasks"][0]["status"], "passed")
            self.assertEqual(report["tasks"][0]["binary"]["sha256"],
                             hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest())

    def test_scaling_gate_is_strictly_above_85_percent(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            paths = {name: directory / f"{name}.json" for name in
                     ("strong", "weak")}
            for efficiency in (0.85, 0.86):
                for kind, path in paths.items():
                    times = {1: 0.01,
                             2: 0.01 / ((2 if kind == "strong" else 1) * efficiency),
                             4: 0.01 / ((4 if kind == "strong" else 1) * efficiency)}
                    report = {
                        "binary_sha256": "same", "mass_check_interval": 100,
                        "input_options": list(run_tests.AA_OPTIONS),
                        "warmup_steps": 100, "timed_steps": 500,
                        "summary": {str(n): {"median_sec_per_step": value}
                                    for n, value in times.items()},
                        "runs": [{"gpus": n, "repeat": repeat,
                                  "full_field_outputs": []}
                                 for repeat in (1, 2, 3) for n in (1, 2, 4)]}
                    path.write_text(json.dumps(report))
                result = subprocess.run(
                    [sys.executable, str(run_tests.HERE / "check_scaling.py"),
                     str(paths["strong"]), str(paths["weak"]),
                     "--target", "0.85"], text=True, capture_output=True)
                self.assertEqual(result.returncode, 0 if efficiency > 0.85 else 1)


if __name__ == "__main__":
    unittest.main()
