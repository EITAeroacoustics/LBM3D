"""Check one 512^3 periodic FP64 AA TGV run without field files.

The frozen 128^3 energy values are a grid-consistency reference, not an
analytic 512^3 solution.  Run in a new directory on one GPU.
"""

import argparse
import csv
import json
import math
import os
import re
import subprocess
import time
from pathlib import Path

import check_precision_no_fields as precision


HERE = Path(__file__).resolve().parent
REFERENCE = HERE / "reference_physics.csv"
GRID = 512
CELLS = GRID**3


def run_case(binary: Path, inputs: Path, root: Path, step: int,
             gpu: int) -> tuple[dict, str]:
    directory = root / ("initial" if step == 0 else "final")
    directory.mkdir()
    command = [str(binary), str(inputs), f"max_step={step}",
               "lbm3d.storage=aa", "lbmPhysicalParameters.nmac=4",
               "amr.plot_int=-1", "amr.chk_int=-1"]
    if step:
        command.append("lbm3d.tgv_metrics_interval=256")
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(gpu)
    log_path = directory / "run.log"
    start = time.monotonic()
    with log_path.open("w") as output:
        code = subprocess.run(command, cwd=directory, env=env, stdout=output,
                              stderr=subprocess.STDOUT).returncode
    log = log_path.read_text(errors="replace")
    fields = precision.full_field_files(directory)
    result = {"command": command, "returncode": code,
              "elapsed_seconds": time.monotonic() - start,
              "log": str(log_path.resolve()), "log_sha256": precision.sha256(log_path),
              "full_field_files": fields}
    return result, log


def verify_run(result: dict, log: str, step: int) -> None:
    if (result["returncode"] or result["full_field_files"] or
        (step and f"Coarse STEP {step} ends" not in log) or
        not re.search(r"^AMReX \([^\n]+\) finalized$", log, re.M)):
        raise ValueError(f"incomplete or field-writing run: {result['log']}")
    if precision.PRECISION.findall(log) != ["8"]:
        raise ValueError(f"FP64 diagnostic missing: {result['log']}")
    result["fields"] = precision.parse_fields(log)


def online_metrics(log: str) -> dict[int, dict[str, float]]:
    rows = {}
    for match in precision.METRICS.finditer(log):
        fields = dict(word.split("=", 1) for word in match.group(1).split()
                      if "=" in word)
        values = precision.numbers(fields, ("step", "time", "cells", "mean_rho",
                                            "mean_kinetic", "nonfinite",
                                            "min_rho", "min_f"))
        step = int(values["step"])
        if step not in (256, 512):
            continue
        if step in rows or values["step"] != step or \
           not math.isclose(values["time"], step / 8, rel_tol=0.0,
                            abs_tol=1e-12) or \
           values["cells"] != CELLS or values["nonfinite"] != 0 or \
           values["min_rho"] <= 0 or values["min_f"] <= 0:
            raise ValueError(f"invalid 512^3 online metric at step {step}")
        rows[step] = values
    if set(rows) != {256, 512}:
        raise ValueError("missing 512^3 online metrics at steps 256 and 512")
    return rows


def reference_energy() -> dict[int, float]:
    with REFERENCE.open(newline="") as source:
        rows = {int(float(row["time"])): float(row["mean_kinetic"])
                for row in csv.DictReader(source) if row["grid"] == "128"}
    return {step: rows[step // 8] for step in (256, 512)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("input", type=Path)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--gpu", type=int, default=0,
                        help="physical GPU index (default: 0)")
    args = parser.parse_args()
    binary = args.binary.resolve()
    inputs = args.input.resolve()
    if not binary.is_file() or not inputs.is_file():
        parser.error("summary binary and 512^3 input must exist")
    case = inputs.read_text()
    if not re.search(r"^amr\.n_cell\s*=\s*512 512 512\s*$", case, re.M) or \
       not re.search(r"^geometry\.is_periodic\s*=\s*1 1 1\s*$", case, re.M):
        parser.error("input must describe a periodic 512^3 grid")
    args.run_root.mkdir(parents=True, exist_ok=False)
    report = {"status": "failed", "grid": GRID, "cells": CELLS,
              "gpu": args.gpu,
              "binary": str(binary), "binary_sha256": precision.sha256(binary),
              "input": str(inputs), "input_sha256": precision.sha256(inputs),
              "reference": str(REFERENCE),
              "reference_sha256": precision.sha256(REFERENCE),
              "reference_role": "128^3 grid-consistency check, not analytic truth",
              "runs": {}, "checks": {}}
    try:
        initial, initial_log = run_case(binary, inputs, args.run_root, 0,
                                        args.gpu)
        report["runs"]["0"] = initial
        verify_run(initial, initial_log, 0)
        final, final_log = run_case(binary, inputs, args.run_root, 512,
                                    args.gpu)
        report["runs"]["512"] = final
        verify_run(final, final_log, 512)
        t0 = precision.parse_metric(initial_log, GRID, 0)
        later = online_metrics(final_log)
        reference = reference_energy()
        checks = {
            "initial": t0["init_linf"] <= 1e-12 and
                       abs(t0["mean_rho"] - 1.0) <= 1e-12 and
                       abs(t0["mean_kinetic"] - 5e-5) <= 1e-12,
            "mass_32": abs(later[256]["mean_rho"] - t0["mean_rho"]) /
                       t0["mean_rho"] <= 1e-8,
            "mass_64": abs(later[512]["mean_rho"] - t0["mean_rho"]) /
                       t0["mean_rho"] <= 1e-8,
            "energy_decay": t0["mean_kinetic"] > later[256]["mean_kinetic"] >
                            later[512]["mean_kinetic"] > 0,
            "energy_grid_32": abs(later[256]["mean_kinetic"] - reference[256]) /
                              reference[256] <= 0.01,
            "energy_grid_64": abs(later[512]["mean_kinetic"] - reference[512]) /
                              reference[512] <= 0.01,
            "finite": t0["nonfinite"] == 0,
        }
        report["metrics"] = {"0": t0, "256": later[256], "512": later[512]}
        report["reference_energy"] = {str(k): v for k, v in reference.items()}
        report["checks"] = checks
        report["status"] = "passed" if all(checks.values()) else "failed"
        if report["status"] == "failed":
            report["reason"] = "one or more frozen 512^3 checks failed"
    except (ValueError, KeyError) as error:
        report["reason"] = str(error)
    if precision.sha256(binary) != report["binary_sha256"] or \
       precision.sha256(inputs) != report["input_sha256"]:
        report["status"] = "failed"
        report["reason"] = "binary or input changed during the run"
    (args.run_root / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"{report['status']}: {args.run_root / 'report.json'}", flush=True)
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
