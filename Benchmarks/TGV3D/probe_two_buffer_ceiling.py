"""Measure the current FP64 two-buffer TGV ceiling without field output.

Each edge runs in a fresh process for ten steps.  The first GPU out-of-memory
failure bounds the capacity; another failure stops the sweep without claiming
an OOM limit.  Use the same summary binary and nmac=4 as the AA capacity test.

  python3 Benchmarks/TGV3D/probe_two_buffer_ceiling.py BINARY RUN_ROOT REPORT \
      --edges 400 408 416 424 432

Run with a new RUN_ROOT; the JSON report and per-edge logs retain the result.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

import check_precision_no_fields as precision
import probe_single_gpu_capacity as capacity


HERE = Path(__file__).resolve().parent
STEPS = 10
OOM = re.compile(r"out of memory|cudaErrorMemoryAllocation|"
                 r"CUDA_ERROR_OUT_OF_MEMORY|bad_alloc|failed to allocate",
                 re.I)


def run_edge(binary: Path, root: Path, edge: int, gpu_index: int,
             binary_hash: str) -> dict:
    directory = root / f"n{edge}"
    directory.mkdir()
    inputs = directory / "inputs"
    subprocess.run([sys.executable, str(HERE / "make_inputs.py"), "capacity",
                    str(edge), str(inputs)], check=True)
    inputs.write_text(capacity.settings(inputs.read_text(), {
        "max_step": str(STEPS), "amr.n_cell": f"{edge} {edge} {edge}",
        "amr.max_grid_size": "64", "amr.blocking_factor_x": "8",
        "amr.blocking_factor_y": "8", "amr.blocking_factor_z": "8",
        "lbmPhysicalParameters.nmac": "4", "amr.plot_int": "-1",
        "amr.chk_int": "-1",
    }))
    input_hash = capacity.sha256(inputs)
    command = [str(binary), str(inputs), "lbm3d.storage=two_buffer"]
    baseline_mib = capacity.gpu_used_mib(gpu_index)
    peak_mib = baseline_mib
    sample_error = None
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(gpu_index)
    log_path = directory / "run.log"
    started = time.monotonic()
    with log_path.open("w") as output:
        process = subprocess.Popen(command, cwd=directory, env=env,
                                   stdout=output, stderr=subprocess.STDOUT)
        while process.poll() is None:
            if sample_error is None:
                try:
                    peak_mib = max(peak_mib, capacity.gpu_used_mib(gpu_index))
                except (OSError, subprocess.CalledProcessError, ValueError) as error:
                    sample_error = str(error)
            time.sleep(0.2)
        returncode = process.wait()
    log = log_path.read_text(errors="replace")
    fields = capacity.full_field_files(directory)
    problems = []
    if fields:
        problems.append("full-field output found")
    if capacity.sha256(binary) != binary_hash or capacity.sha256(inputs) != input_hash:
        problems.append("binary or input changed during run")
    if sample_error:
        problems.append("GPU memory sampling failed")
    if returncode == 0:
        if f"Coarse STEP {STEPS} ends" not in log or not re.search(
                r"^AMReX \([^\n]+\) finalized$", log, re.M):
            problems.append("final step or AMReX finalization missing")
        if precision.PRECISION.findall(log) != ["8"]:
            problems.append("FP64 diagnostic missing")
        if capacity.STORAGE.findall(log):
            problems.append("unexpected AA storage marker")
        try:
            metric = precision.parse_metric(log, edge, STEPS)
            summaries = precision.parse_fields(log)
            if (metric["nonfinite"] != 0.0 or
                abs(metric["mean_rho"] - 1.0) > 1.0e-8):
                problems.append("mass or finiteness check failed")
        except ValueError as error:
            problems.append(str(error))
            metric = None
            summaries = None
        allocated = capacity.arena_mb(log, "allocated")
        used = capacity.arena_mb(log, "used")
        if allocated is None or used is None or used > allocated:
            problems.append("AMReX Arena diagnostic missing or invalid")
        status = "passed" if not problems else "failed"
    else:
        metric = None
        summaries = None
        allocated = capacity.arena_mb(log, "allocated")
        used = capacity.arena_mb(log, "used")
        status = "oom" if OOM.search(log) and not problems else "failed"
        if status == "failed":
            problems.append(f"process exited with code {returncode}")

    boxes_per_axis = math.ceil(edge / 64)
    field_budget_mib = ((edge + 2 * boxes_per_axis)**3 *
                        2 * (19 + 4) * 8 / 1024**2)
    return {
        "edge": edge, "cells": edge**3, "status": status,
        "returncode": returncode, "command": command,
        "input": str(inputs), "input_sha256": input_hash,
        "log": str(log_path), "log_sha256": capacity.sha256(log_path),
        "wall_s": time.monotonic() - started,
        "gpu_baseline_mib": baseline_mib, "gpu_peak_mib": peak_mib,
        "gpu_sample_interval_s": 0.2, "gpu_sample_error": sample_error,
        "arena_max_allocated_mb": allocated, "arena_max_used_mb": used,
        "two_buffer_field_budget_mib": field_budget_mib,
        "metric": metric, "min_rho": summaries["0"]["min"] if summaries else None,
        "min_f": min(summaries[str(q)]["min"] for q in range(6, 25))
        if summaries else None,
        "full_field_files": fields, "problems": problems,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--edges", type=int, nargs="+", required=True)
    parser.add_argument("--gpu-index", type=int, default=0)
    parser.add_argument("--max-gpu-used-mib", type=int, default=1024)
    args = parser.parse_args()
    if (sorted(set(args.edges)) != args.edges or
        any(edge < 8 or edge % 8 for edge in args.edges)):
        parser.error("--edges must be increasing multiples of 8")
    if args.max_gpu_used_mib < 0:
        parser.error("--max-gpu-used-mib must be nonnegative")
    binary = args.binary.resolve(strict=True)
    if binary.name != "lbm3d_tgv3d_summary" or not os.access(binary, os.X_OK):
        parser.error("binary must be executable lbm3d_tgv3d_summary")
    root = args.run_root.resolve()
    if root.exists():
        parser.error(f"run root already exists: {root}")
    baseline_mib = capacity.gpu_used_mib(args.gpu_index)
    if baseline_mib > args.max_gpu_used_mib:
        parser.error(f"GPU {args.gpu_index} already uses {baseline_mib} MiB")
    root.mkdir(parents=True)
    report_path = args.report.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    binary_hash = capacity.sha256(binary)
    gpu = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=index,name,memory.total,driver_version,uuid",
         "--format=csv,noheader", "-i", str(args.gpu_index)], text=True).strip()
    report = {
        "schema_version": 1, "storage": "two_buffer", "real_bytes": 8,
        "nmac": 4, "steps": STEPS, "max_grid_size": 64, "blocking_factor": 8,
        "binary": str(binary), "binary_sha256": binary_hash,
        "input_generator_sha256": capacity.sha256(HERE / "make_inputs.py"),
        "gpu": gpu, "gpu_index": args.gpu_index,
        "gpu_initial_mib": baseline_mib, "host": platform.node(),
        "edges": args.edges, "runs": [], "status": "running",
    }
    for edge in args.edges:
        if capacity.gpu_used_mib(args.gpu_index) > args.max_gpu_used_mib:
            report["status"] = "stopped_gpu_busy"
            break
        print(f"two_buffer: {edge}^3", flush=True)
        row = run_edge(binary, root, edge, args.gpu_index, binary_hash)
        report["runs"].append(row)
        report["last_passed_edge"] = max(
            (item["edge"] for item in report["runs"] if item["status"] == "passed"),
            default=None)
        report["first_oom_edge"] = next(
            (item["edge"] for item in report["runs"] if item["status"] == "oom"),
            None)
        report["status"] = ("bounded_by_oom" if row["status"] == "oom" and
                            report["last_passed_edge"] is not None else
                            "failed" if row["status"] == "failed" else
                            "oom_before_first_pass" if row["status"] == "oom" else
                            "no_oom_in_range")
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print(f"  {row['status']}; peak {row['gpu_peak_mib']} MiB", flush=True)
        if row["status"] != "passed":
            break
    else:
        report["status"] = "no_oom_in_range"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"report={report_path}", flush=True)
    if report["status"] in ("failed", "stopped_gpu_busy"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
