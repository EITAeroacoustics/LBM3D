"""Run all migrated examples and compare the two IBM cases with upstream."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
CASES = {
    2: (("Cavity_flow", "lbm3d_cavity"),
        ("Couette_flow", "lbm3d_couette"),
        ("Cylinder_flow", "lbm3d_cylinder"),
        ("ForceValidation", "lbm3d_force_validation"),
        ("Pitching_airfoil", "lbm3d_pitching_airfoil"),
        ("Taylor_Green_Vortex", "lbm3d_taylor_green_2d")),
    3: (("Sphere_flow", "lbm3d_sphere"),
        ("SquareDuct_flow", "lbm3d_square_duct")),
}
COMPARE = re.compile(r"BIT_COMPARE var=(\w+) mismatches=(\d+) max_abs=([0-9.eE+-]+)")
SPHERE_FIELD_TOLERANCE = 1e-14


def run(binary: Path, inputs: Path, directory: Path, plots: bool) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    command = [str(binary), str(inputs), "max_step=2", "amr.chk_int=-1",
               "amr.regrid_int=-1", f"amr.plot_int={1 if plots else -1}"]
    if plots:
        command.append("amr.plot_file=plt")
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = "0"
    log = directory / "run.log"
    with log.open("w") as output:
        result = subprocess.run(command, cwd=directory, env=env,
                                stdout=output, stderr=subprocess.STDOUT)
    text = log.read_text(errors="replace")
    complete = (result.returncode == 0 and "Coarse STEP 2 ends" in text and
                "finalized" in text)
    row = {"command": command, "log": str(log.resolve()),
           "returncode": result.returncode, "complete": complete}
    if not complete:
        raise RuntimeError(f"example failed: {log}")
    return row


def compare(binary: Path, reference: Path, other: Path, tolerance: float) -> dict:
    result = subprocess.run([str(binary), str(reference), str(other)],
                            text=True, capture_output=True)
    fields = {name: {"mismatches": int(count), "max_abs": float(max_abs)}
              for name, count, max_abs in COMPARE.findall(result.stdout)}
    if result.returncode not in (0, 1) or len(fields) != 4 or \
            any(item["max_abs"] > tolerance for item in fields.values()):
        raise RuntimeError(f"field mismatch: {reference} {other}\n{result.stdout}")
    if tolerance == 0.0 and (result.returncode or any(item["mismatches"] for item in fields.values())):
        raise RuntimeError(f"bitwise mismatch: {reference} {other}\n{result.stdout}")
    return fields


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("build_2d", "build_3d", "baseline_pitching", "baseline_sphere",
                 "compare_2d", "compare_3d", "work"):
        parser.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    args = parser.parse_args()
    builds = {2: args.build_2d.resolve(), 3: args.build_3d.resolve()}
    comparators = {2: args.compare_2d.resolve(), 3: args.compare_3d.resolve()}
    args.work.mkdir(parents=True, exist_ok=True)
    rows = []
    for dim, cases in CASES.items():
        for case_name, target in cases:
            row = run(builds[dim] / target, HERE / case_name / "inputs",
                      args.work / "smoke" / case_name, False)
            rows.append({"dimension": dim, "case": case_name, **row})
            print(f"{case_name}: complete", flush=True)

    ibm = []
    for dim, case_name, target, baseline in (
            (2, "Pitching_airfoil", "lbm3d_pitching_airfoil", args.baseline_pitching),
            (3, "Sphere_flow", "lbm3d_sphere", args.baseline_sphere)):
        upstream_input = HERE.parent / "iLBMReX" / "Examples" / case_name / "inputs"
        reference = args.work / "ibm" / case_name / "upstream"
        migrated = args.work / "ibm" / case_name / "modular"
        run(baseline.resolve(), upstream_input, reference, True)
        run(builds[dim] / target, HERE / case_name / "inputs", migrated, True)
        tolerance = SPHERE_FIELD_TOLERANCE if dim == 3 else 0.0
        fields = {str(step): compare(comparators[dim],
                                    reference / f"plt{step:05d}",
                                    migrated / f"plt{step:05d}", tolerance)
                  for step in (0, 1, 2)}
        baseline_repeat = None
        if dim == 3:
            repeated = args.work / "ibm" / case_name / "upstream-repeat"
            run(baseline.resolve(), upstream_input, repeated, True)
            baseline_repeat = {str(step): compare(comparators[dim],
                                                 reference / f"plt{step:05d}",
                                                 repeated / f"plt{step:05d}",
                                                 tolerance)
                               for step in (0, 1, 2)}
        reference_force = (reference / "force.dat").read_bytes()
        migrated_force = (migrated / "force.dat").read_bytes()
        if reference_force != migrated_force:
            raise RuntimeError(f"force mismatch: {case_name}")
        if baseline_repeat is not None and reference_force != (repeated / "force.dat").read_bytes():
            raise RuntimeError(f"upstream repeat force mismatch: {case_name}")
        ibm.append({"case": case_name, "dimension": dim, "fields": fields,
                    "field_tolerance": tolerance, "upstream_repeat": baseline_repeat,
                    "force_sha256": hashlib.sha256(reference_force).hexdigest(),
                    "force_equal": True})
        print(f"{case_name}: upstream fields within {tolerance:g}, force equal", flush=True)

    motion_original = subprocess.run(
        [str(builds[2] / "lbm3d_motion_original")], text=True, capture_output=True, check=True)
    motion_modular = subprocess.run(
        [str(builds[2] / "lbm3d_motion_modular")], text=True, capture_output=True, check=True)
    samples = motion_original.stdout.splitlines()
    if len(samples) != 6 or motion_original.stdout != motion_modular.stdout:
        raise RuntimeError("pitching-airfoil marker position or velocity differs")
    report = {"smoke": rows, "ibm_regression": ibm,
              "marker_motion": {"samples": samples, "equal": True}}
    (args.work / "examples-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Pitching_airfoil: marker position and velocity equal", flush=True)


if __name__ == "__main__":
    main()
