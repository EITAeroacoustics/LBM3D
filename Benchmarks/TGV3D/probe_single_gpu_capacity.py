"""Probe the 536^3 TGV capacity target on one GPU without field output.

Run a ten-step pilot, then a fresh process for at least 100 steps with the
same binary. The final TGV_METRICS/FIELD_SUMMARY diagnostics check the pilot.
For the long run, TGV_METRICS must also appear during time stepping and carry
min_rho and min_f; missing online evidence is reported as incomplete.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path


TARGET_CELLS = 150_000_000
STEP_END = re.compile(r"^Coarse STEP (\d+) ends\.", re.M)
STEP_MASS = re.compile(r"^Coarse STEP (\d+) ends\..*?\bSum\(Rho\) = (\S+)", re.M)
METRICS = re.compile(r"^TGV_METRICS (.+)$", re.M)
PRECISION = re.compile(r"^TGV_PRECISION real_bytes=(\d+)$", re.M)
STORAGE = re.compile(
    r"^LBM_STORAGE mode=(\S+) f_ncomp=(\d+) f_ngrow=(\d+) "
    r"macro_ncomp=(\d+) macro_ngrow=(\d+)$", re.M)
FIELD = re.compile(r"^FIELD_SUMMARY (.+)$", re.M)
ARENA = re.compile(
    r"\[The\s+Arena\]\s+(?:max space \(MB\) {kind}\s+spread across MPI|"
    r"space {kind}\s+\(MB\)):\s*\[?(\d+)")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def settings(text: str, changes: dict[str, str]) -> str:
    for key, value in changes.items():
        pattern = rf"(?m)^({re.escape(key)}\s*=\s*).*$"
        text, count = re.subn(pattern, lambda match: match.group(1) + value, text)
        if count != 1:
            raise ValueError(f"expected one {key} setting, found {count}")
    return text


def pairs(line: str) -> dict[str, str]:
    return dict(word.split("=", 1) for word in line.split() if "=" in word)


def finite(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"nonfinite diagnostic: {value}")
    return number


def arena_mb(log: str, kind: str) -> int | None:
    matches = re.findall(ARENA.pattern.format(kind=kind), log)
    return int(matches[-1]) if matches else None


def full_field_files(directory: Path) -> list[str]:
    return sorted(str(path.relative_to(directory)) for path in directory.rglob("*")
                  if path.name.lower().startswith(("plt", "plot", "chk", "checkpoint"))
                  or path.suffix.lower() in (".h5", ".hdf5", ".bp"))


def assess_log(log: str, n: int, steps: int, mass_rel_tol: float,
               real_bytes: int, require_online: bool) -> dict:
    """Parse scalar evidence. Missing evidence never counts as a pass."""
    problems: list[str] = []
    missing: list[str] = []
    cells = n**3
    step_ends = {int(match.group(1)): match.end()
                 for match in STEP_END.finditer(log)}
    ended_steps = list(step_ends)
    if steps not in ended_steps or max(ended_steps, default=0) != steps:
        problems.append(f"final step {steps} not observed")
    amrex = re.search(r"^AMReX \(([^\n]+)\) finalized$", log, re.M)
    if amrex is None:
        problems.append("AMReX finalization not observed")

    precision = PRECISION.findall(log)
    if not precision:
        missing.append("TGV_PRECISION row")
    elif any(int(width) != real_bytes for width in precision):
        problems.append(f"Real width differs from expected {real_bytes} bytes")

    storage_rows = STORAGE.findall(log)
    if not storage_rows:
        missing.append("LBM_STORAGE row")
    elif storage_rows != [("aa", "19", "1", "4", "0")]:
        problems.append("unexpected LBM_STORAGE allocation")

    mass = []
    for step_text, value in STEP_MASS.findall(log):
        try:
            mass.append({"step": int(step_text), "sum_rho": finite(value)})
        except ValueError as error:
            problems.append(str(error))
    if len(mass) < 2 or mass[0]["step"] > 1 or mass[-1]["step"] != steps:
        missing.append("initial and final step mass samples")
    elif mass[0]["sum_rho"] <= 0.0:
        problems.append("nonpositive initial mass")
    elif any(abs(row["sum_rho"] - mass[0]["sum_rho"]) /
             mass[0]["sum_rho"] > mass_rel_tol for row in mass):
        problems.append("mass drift exceeds tolerance")

    metrics = []
    metric_positions = []
    for match in METRICS.finditer(log):
        row = pairs(match.group(1))
        try:
            metric = {key: finite(row[key]) for key in
                      ("step", "cells", "mean_rho", "mean_kinetic", "nonfinite")}
            for key in ("min_rho", "min_f"):
                if key in row:
                    metric[key] = finite(row[key])
            if (metric["step"] != int(metric["step"]) or
                metric["cells"] != cells or metric["mean_rho"] <= 0.0 or
                metric["mean_kinetic"] <= 0.0 or metric["nonfinite"] != 0.0):
                problems.append("invalid TGV_METRICS values")
            if "min_rho" in metric and metric["min_rho"] <= 0.0:
                problems.append("nonpositive density")
            if "min_f" in metric and metric["min_f"] <= 0.0:
                problems.append("nonpositive population")
            metrics.append(metric)
            metric_positions.append(match.start())
        except (KeyError, ValueError) as error:
            problems.append(f"invalid TGV_METRICS row: {error}")
    metric_steps = [int(row["step"]) for row in metrics]
    if not metrics or metric_steps[-1] != steps:
        missing.append("final TGV_METRICS row")
    if len(metric_steps) != len(set(metric_steps)) or metric_steps != sorted(metric_steps):
        problems.append("duplicate or unordered TGV_METRICS steps")
    if any(step < 0 or step > steps for step in metric_steps):
        problems.append("TGV_METRICS step outside run")
    for step, position in zip(metric_steps, metric_positions):
        if step > 0:
            next_end = min((end for later, end in step_ends.items()
                            if later > step), default=len(log) + 1)
            if step not in step_ends or not step_ends[step] < position < next_end:
                problems.append(f"TGV_METRICS step {step} was not emitted online")
    if metrics:
        initial_mean = (mass[0]["sum_rho"] / cells if mass else
                        metrics[0]["mean_rho"])
        if initial_mean <= 0.0 or any(
                abs(row["mean_rho"] - initial_mean) / initial_mean >
                mass_rel_tol for row in metrics):
            problems.append("TGV_METRICS mass drift exceeds tolerance")

    minima = {}
    for match in FIELD.finditer(log):
        row = pairs(match.group(1))
        try:
            level = int(row["lev"])
            component = int(row["comp"])
            minimum = finite(row["min"])
            maximum = finite(row["max"])
            if level != 0 or component in minima or minimum > maximum:
                problems.append("invalid FIELD_SUMMARY component")
            minima[component] = minimum
        except (KeyError, ValueError) as error:
            problems.append(f"invalid FIELD_SUMMARY row: {error}")
    final_metric = metrics[-1] if metrics and metric_steps[-1] == steps else {}
    if not ("min_rho" in final_metric and "min_f" in final_metric):
        if not {0, *range(6, 25)}.issubset(minima):
            missing.append("final density and D3Q19 population minima")
        elif minima[0] <= 0.0 or min(minima[q] for q in range(6, 25)) <= 0.0:
            problems.append("nonpositive final density or population")

    online_steps = [int(row["step"]) for row in metrics
                    if 0 < row["step"] < steps and
                    "min_rho" in row and "min_f" in row]
    if require_online and (not metrics or metric_steps[0] > 1 or
                           not online_steps or
                           any("min_rho" not in row or "min_f" not in row
                               for row in metrics)):
        missing.append("online TGV_METRICS with min_rho/min_f at start, "
                       "an intermediate step, and final step")

    allocated = arena_mb(log, "allocated")
    used = arena_mb(log, "used")
    if allocated is None or used is None:
        missing.append("AMReX Arena max allocated and used")
    elif allocated <= 0 or used <= 0 or used > allocated:
        problems.append("invalid AMReX Arena memory")

    return {
        "status": "failed" if problems else "incomplete" if missing else "passed",
        "problems": problems, "missing": missing,
        "ended_steps": ended_steps, "step_mass": mass, "metrics": metrics,
        "online_metric_steps": online_steps,
        "amrex_version": amrex.group(1) if amrex else None,
        "storage": storage_rows,
        "final_min_rho": final_metric.get("min_rho", minima.get(0)),
        "final_min_f": final_metric.get("min_f", min(
            (minima[q] for q in range(6, 25) if q in minima), default=None)),
        "arena_max_allocated_mb": allocated, "arena_max_used_mb": used,
    }


def gpu_used_mib(index: int) -> int:
    output = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits",
         "-i", str(index)], text=True)
    return int(output.strip())


def nvcc_version() -> str | None:
    try:
        output = subprocess.check_output(["nvcc", "--version"], text=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return output.strip().splitlines()[-1]


def run_stage(binary: Path, case_dir: Path, run_root: Path, stage: str,
              n: int, steps: int, gpu_index: int, binary_hash: str,
              mass_rel_tol: float, real_bytes: int) -> dict:
    directory = run_root / stage
    directory.mkdir()
    inputs = directory / "inputs"
    subprocess.run([sys.executable, str(case_dir / "make_inputs.py"),
                    "capacity", str(n), str(inputs)], check=True)
    inputs.write_text(settings(inputs.read_text(), {
        "max_step": str(steps), "amr.n_cell": f"{n} {n} {n}",
        "amr.max_grid_size": "64", "amr.blocking_factor_x": "8",
        "amr.blocking_factor_y": "8", "amr.blocking_factor_z": "8",
        "lbmPhysicalParameters.nmac": "4", "amr.plot_int": "-1",
        "amr.chk_int": "-1",
    }))
    input_hash = sha256(inputs)
    command = [str(binary), str(inputs), "lbm3d.storage=aa",
               f"lbm3d.tgv_metrics_interval={max(1, steps // 2)}"]
    log_path = directory / "run.log"
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(gpu_index)
    baseline_mib = gpu_used_mib(gpu_index)
    peak_mib = baseline_mib
    sample_error = None
    binary_before = sha256(binary)
    started = time.monotonic()
    with log_path.open("w") as output:
        process = subprocess.Popen(command, cwd=directory, env=env,
                                   stdout=output, stderr=subprocess.STDOUT)
        pid = process.pid
        while process.poll() is None:
            if sample_error is None:
                try:
                    peak_mib = max(peak_mib, gpu_used_mib(gpu_index))
                except (OSError, subprocess.CalledProcessError, ValueError) as error:
                    sample_error = str(error)
            time.sleep(0.2)
        returncode = process.wait()
    elapsed = time.monotonic() - started
    log = log_path.read_text(errors="replace")
    diagnostics = assess_log(log, n, steps, mass_rel_tol, real_bytes,
                             require_online=stage == "sustained")
    fields = full_field_files(directory)
    binary_after = sha256(binary)
    if returncode != 0:
        diagnostics["problems"].append(f"process exited with code {returncode}")
    if fields:
        diagnostics["problems"].append("full field or checkpoint was written")
    if binary_before != binary_hash or binary_after != binary_hash:
        diagnostics["problems"].append("binary changed during run")
    if sample_error is not None:
        diagnostics["missing"].append("reliable nvidia-smi peak sample")
    diagnostics["status"] = ("failed" if diagnostics["problems"] else
                             "incomplete" if diagnostics["missing"] else "passed")
    return {
        "stage": stage, "n": n, "cells": n**3, "target_steps": steps,
        "pid": pid, "returncode": returncode, "command": command,
        "binary_sha256_before": binary_before,
        "binary_sha256_after": binary_after,
        "input": str(inputs), "input_sha256": input_hash,
        "log": str(log_path), "log_sha256": sha256(log_path),
        "wall_s": elapsed, "gpu_baseline_mib": baseline_mib,
        "gpu_peak_mib": peak_mib, "gpu_peak_delta_mib": peak_mib - baseline_mib,
        "gpu_sample_interval_s": 0.2, "gpu_sample_error": sample_error,
        "full_field_files": fields, "diagnostics": diagnostics,
        "status": diagnostics["status"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path,
                        help="lbm3d_tgv3d_summary binary")
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--n", type=int, default=536)
    parser.add_argument("--steps", type=int, default=100)
    parser.add_argument("--gpu-index", type=int, default=0)
    parser.add_argument("--real-bytes", type=int, choices=(4, 8), default=8)
    parser.add_argument("--mass-rel-tol", type=float, default=1.0e-8)
    args = parser.parse_args()
    if args.n < 8 or args.n % 8 or args.steps < 100 or \
       not math.isfinite(args.mass_rel_tol) or args.mass_rel_tol <= 0.0:
        parser.error("n must be a multiple of 8, steps >= 100, mass tolerance positive")

    binary = args.binary.resolve(strict=True)
    case_dir = args.case_dir.resolve(strict=True)
    run_root = args.run_root.resolve()
    report_path = args.report.resolve()
    run_root.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    binary_hash = sha256(binary)
    gpu = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=index,name,memory.total,driver_version,uuid",
         "--format=csv,noheader", "-i", str(args.gpu_index)], text=True).strip()
    report = {
        "target": "> 150000000 cells on one GPU, 10-step pilot and >= 100 steps",
        "n": args.n, "cells": args.n**3,
        "max_grid_size": 64, "blocking_factor": 8, "nmac": 4,
        "storage": "aa", "online_metric_interval": "half the run length",
        "real_bytes_expected": args.real_bytes,
        "mass_relative_tolerance": args.mass_rel_tol,
        "binary": str(binary), "binary_sha256": binary_hash,
        "input_generator_sha256": sha256(case_dir / "make_inputs.py"),
        "gpu": gpu, "cuda_visible_devices": str(args.gpu_index),
        "host": platform.node(), "python": platform.python_version(),
        "nvcc_version": nvcc_version(),
        "runs": [], "status": "running",
    }

    for stage, steps in (("pilot", 10), ("sustained", args.steps)):
        print(f"{stage}: {args.n}^3, {steps} steps", flush=True)
        row = run_stage(binary, case_dir, run_root, stage, args.n, steps,
                        args.gpu_index, binary_hash, args.mass_rel_tol,
                        args.real_bytes)
        report["runs"].append(row)
        report["status"] = ("passed" if args.n**3 > TARGET_CELLS and
                            stage == "sustained" and row["status"] == "passed"
                            else row["status"] if row["status"] != "passed"
                            else "below_target" if args.n**3 <= TARGET_CELLS
                            else "pilot_passed")
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print(f"  status={row['status']} peak={row['gpu_peak_mib']} MiB", flush=True)
        if row["status"] != "passed":
            break

    print(f"report={report_path}", flush=True)
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
