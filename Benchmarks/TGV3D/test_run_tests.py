"""CPU-only checks for the TGV test entry point."""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import run_tests


class TestTgvAgent(unittest.TestCase):
    @staticmethod
    def args(summary_binary=None):
        return SimpleNamespace(
            summary_binary=summary_binary, timing_binary=None,
            baseline_summary_binary=None, summary_build_dir=None,
            timing_build_dir=None, rank_wrapper=None, mpirun="mpirun",
            mpi_options="", cmake="cmake", stability_seconds=600)

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
            binary = Path(temporary) / "lbm3d_tgv3d_summary"
            shutil.copy2(sys.executable, binary)
            result = subprocess.run(
                [sys.executable, str(run_tests.HERE / "run_tests.py"),
                 "--mode", "quick", "--only", "build_summary",
                 "--summary-binary", str(binary),
                 "--run-root", str(root)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            report = json.loads((root / "result.json").read_text())
            self.assertEqual(report["status"], "not_run")
            self.assertEqual(report["tasks"][0]["status"], "passed")
            self.assertEqual(report["tasks"][0]["verification"], "prebuilt_hash")
            self.assertEqual(report["tasks"][0]["binary"]["sha256"],
                             hashlib.sha256(binary.read_bytes()).hexdigest())

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

    def test_non_json_scaling_error_remains_a_reported_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outcome = run_tests.check_task("scaling", self.args(), root)
            self.assertEqual(outcome["status"], "failed")
            self.assertEqual(outcome["assessment"], {})
            self.assertTrue(Path(outcome["log"]).is_file())

    def test_stability_requires_a_completed_step(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake = root / "lbm3d_tgv3d_summary"
            fake.write_text("#!/bin/sh\n"
                            "echo 'LBM wall time limit reached after 600 s at step 0'\n")
            fake.chmod(0o755)
            outcome = run_tests.stability(self.args(fake), root)
            self.assertEqual(outcome["status"], "failed")
            self.assertIn("no completed step or online numerical assessment",
                          outcome["problems"])

    def test_attempted_missing_precision_diagnostics_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake = root / "lbm3d_tgv3d_summary"
            fake.write_text("#!/bin/sh\necho 'AMReX (26.11) finalized'\n")
            fake.chmod(0o755)
            outcome = run_tests.quick_precision(self.args(fake), root)
            self.assertEqual(outcome["status"], "failed")
            self.assertIn("missing TGV_PRECISION", outcome["reason"])

    def test_build_directory_infers_target_path_before_plan(self):
        with tempfile.TemporaryDirectory() as temporary:
            build = Path(temporary) / "build"
            build.mkdir()
            root = Path(temporary) / "plan"
            result = subprocess.run(
                [sys.executable, str(run_tests.HERE / "run_tests.py"),
                 "--mode", "quick", "--summary-build-dir", str(build),
                 "--run-root", str(root), "--plan-only"],
                text=True, capture_output=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            plan = json.loads((root / "plan.json").read_text())
            self.assertEqual(plan["tasks"][1]["commands"][0][0],
                             str((build / "lbm3d_tgv3d_summary").resolve()))


if __name__ == "__main__":
    unittest.main()
