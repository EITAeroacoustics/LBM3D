"""Versioned, no-field TGV3D test entry point (T-01/T-02).

Write plan.json before touching a GPU.  Every selected check ends as passed,
failed, or not_run; a missing binary, GPU, or baseline is never a pass.
Existing case drivers retain the numerical and timing definitions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import check_precision_no_fields as precision
import compare_field_summary as summary
import probe_single_gpu_capacity as capacity
import run_strong
import run_weak


VERSION = "1.0"
HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1]
CONFIG_PATH = HERE / "test_config.json"
CONFIG = json.loads(CONFIG_PATH.read_text())
P1_COMMIT = CONFIG["p1_reference_commit"]
QUICK = ("build_summary", "quick_precision", "compact_even", "compact_odd")
FULL = (*QUICK, "build_timing", "full_precision", "capacity", "strong",
        "weak", "scaling", "stability")
AA_OPTIONS = tuple(CONFIG["solver_options"])
MASS_TOL = precision.LIMITS["fp64"]["mass"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def command_output(command: list[str]) -> dict:
    try:
        result = subprocess.run(command, text=True, capture_output=True,
                                timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"command": command, "available": False, "error": str(error)}
    return {"command": command, "available": result.returncode == 0,
            "returncode": result.returncode,
            "output": (result.stdout or result.stderr).strip()}


def git_identity() -> dict:
    revision = command_output(["git", "-C", str(SOURCE), "rev-parse", "HEAD"])
    state = command_output(["git", "-C", str(SOURCE), "status", "--porcelain"])
    return {"source": str(SOURCE), "commit": revision.get("output") if
            revision["available"] else None, "dirty": bool(state.get("output")),
            "status": state.get("output", ""), "p1_reference_commit": P1_COMMIT}


def cache_options(binary: Path | None) -> dict:
    if binary is None:
        return {}
    cache = binary.parent / "CMakeCache.txt"
    if not cache.is_file():
        return {}
    names = ("AMReX_DIR", "CMAKE_BUILD_TYPE", "CMAKE_CUDA_COMPILER",
             "CMAKE_CXX_COMPILER", "LBM_TIMING", "LBM_ENABLE_IBM")
    options = {name: line.split("=", 1)[1]
               for line in cache.read_text(errors="replace").splitlines()
               for name in names if line.startswith(name + ":")}
    return {"cmake_cache": str(cache), "cmake_cache_sha256": sha256(cache),
            "options": options}


def binary_identity(path: Path | None) -> dict:
    if path is None:
        return {"path": None, "available": False}
    item = {"path": str(path), "available": path.is_file()}
    if path.is_file():
        item["sha256"] = sha256(path)
        item.update(cache_options(path))
    return item


def expected_binary(path: Path | None, target: str) -> bool:
    return (path is not None and path.name == target and path.is_file() and
            os.access(path, os.X_OK))


def gpu_inventory() -> dict:
    result = command_output(["nvidia-smi", "--query-gpu=index,name,memory.total,"
                             "memory.used,driver_version,uuid",
                             "--format=csv,noheader,nounits"])
    rows = []
    if result["available"]:
        try:
            for line in result["output"].splitlines():
                index, name, total, used, driver, uuid = [part.strip()
                    for part in line.split(",", 5)]
                rows.append({"index": int(index), "name": name,
                             "memory_total_mib": int(total),
                             "memory_used_mib": int(used),
                             "driver": driver, "uuid": uuid})
        except (ValueError, TypeError):
            result["available"] = False
            result["error"] = "could not parse nvidia-smi inventory"
            rows = []
    result["gpus"] = rows
    result["topology"] = command_output(["nvidia-smi", "topo", "-m"])
    return result


def environment(args: argparse.Namespace) -> dict:
    binaries = {name: binary_identity(getattr(args, name)) for name in
                ("summary_binary", "timing_binary", "baseline_summary_binary")}
    inputs = {path.name: sha256(path) for path in
              [*(HERE / f"inputs_physics_{n}" for n in (64, 128)),
               HERE / "inputs_strong_256",
               *(HERE / f"inputs_weak_{n}gpu" for n in (1, 2, 4)),
               HERE / "reference_physics.csv"]}
    return {"host": platform.node(), "python": platform.python_version(),
            "utc": datetime.now(timezone.utc).isoformat(),
            "git": git_identity(), "binaries": binaries, "inputs_sha256": inputs,
            "gpu": gpu_inventory(), "cuda": command_output(["nvcc", "--version"]),
            "mpi": command_output([args.mpirun, "--version"]),
            "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
            "ucx_tls": os.environ.get("UCX_TLS"),
            "ld_library_path": os.environ.get("LD_LIBRARY_PATH"),
            "path": os.environ.get("PATH")}


def v100_resources(inventory: dict, needed: tuple[int, ...],
                   max_used_mib: int) -> str | None:
    gpus = {row["index"]: row for row in inventory["gpu"]["gpus"]}
    absent = sorted(set(needed) - set(gpus))
    if absent:
        return f"GPU indices unavailable: {absent}"
    for index in needed:
        gpu = gpus[index]
        if (CONFIG["hardware"]["gpu_name_contains"] not in gpu["name"] or
            gpu["memory_total_mib"] < CONFIG["hardware"]["minimum_memory_mib"]):
            return "frozen acceptance hardware is V100 32 GB"
        if gpu["memory_used_mib"] > max_used_mib:
            return f"GPU {index} already uses {gpu['memory_used_mib']} MiB"
    return None


def script_command(script: str, *parts: str) -> list[str]:
    return [sys.executable, str(HERE / script), *parts]


def commands(args: argparse.Namespace, root: Path) -> dict[str, list[list[str]]]:
    summ = str(args.summary_binary) if args.summary_binary else "SUMMARY_BINARY"
    timed = str(args.timing_binary) if args.timing_binary else "TIMING_BINARY"
    base = (str(args.baseline_summary_binary) if args.baseline_summary_binary
            else "BASELINE_SUMMARY_BINARY")
    common = [option for item in AA_OPTIONS for option in ("--input-option", item)]
    precision_options = [option for item in AA_OPTIONS for option in
                         ("--candidate-option", item)]
    tool_options = ["--mpirun", args.mpirun, "--mpi-options", args.mpi_options]
    if args.rank_wrapper:
        tool_options += ["--rank-wrapper", str(args.rank_wrapper)]
    result = {
        "build_summary": ([[args.cmake, "--build", str(args.summary_build_dir),
                            "--target", "lbm3d_tgv3d_summary"]]
                          if args.summary_build_dir else []),
        "build_timing": ([[args.cmake, "--build", str(args.timing_build_dir),
                           "--target", "lbm3d_tgv3d"]]
                         if args.timing_build_dir else []),
        "quick_precision": [[summ, str(HERE / f"inputs_physics_{n}"),
                             f"max_step={int(t * n / 64)}", "amr.plot_int=-1",
                             "amr.chk_int=-1", *AA_OPTIONS]
                            for n in CONFIG["precision"]["grids"]
                            for t in CONFIG["precision"]["physical_times"]],
        "compact_even": [], "compact_odd": [],
        "full_precision": [script_command("check_precision_no_fields.py",
                             base, summ, str(root / "full_precision"),
                             "--candidate-precision", "fp64",
                             *precision_options)],
        "capacity": [script_command("probe_single_gpu_capacity.py", summ,
                        str(HERE), str(root / "capacity"),
                        str(root / "capacity.json"), "--n",
                        str(CONFIG["capacity"]["grid"]), "--steps",
                        str(CONFIG["capacity"]["sustained_steps"]),
                        "--mass-rel-tol",
                        str(MASS_TOL), "--real-bytes", "8")],
        "strong": [script_command("run_strong.py", timed,
                       str(HERE / "inputs_strong_256"), str(root / "strong"),
                       str(root / "strong.json"), "--repeats",
                       str(CONFIG["scaling"]["repeats"]),
                       "--mass-check-interval",
                       str(CONFIG["scaling"]["mass_check_interval"]), *tool_options,
                       *common)],
        "weak": [script_command("run_weak.py", timed,
                     str(root / "weak"), str(root / "weak.json"),
                     "--repeats", str(CONFIG["scaling"]["repeats"]),
                     "--mass-check-interval", str(CONFIG["scaling"]["mass_check_interval"]),
                     *tool_options, *common)],
        "scaling": [script_command("check_scaling.py", str(root / "strong.json"),
                        str(root / "weak.json"), "--target",
                        str(CONFIG["scaling"]["efficiency_target_strictly_greater_than"]),
                        "--min-repeats", str(CONFIG["scaling"]["repeats"]))],
        "stability": [[summ, str(HERE / "inputs_strong_256"),
                       "max_step=100000000", "stop_time=1.e30",
                       "amr.plot_int=-1", "amr.chk_int=-1",
                       f"lbm3d.wall_time_limit_s={args.stability_seconds}",
                       "lbm3d.tgv_metrics_interval=100",
                       "lbm3d.mass_check_interval=1", *AA_OPTIONS]],
    }
    for task, steps in zip(("compact_even", "compact_odd"),
                           CONFIG["precision"]["compact_steps"]):
        for ranks, (_, launcher) in summary.CONFIGS.items():
            mpi_launcher = ([args.mpirun, *shlex.split(args.mpi_options),
                             *launcher[1:]] if launcher else [])
            application = [summ, str(HERE / "inputs_physics_128"),
                           *AA_OPTIONS, f"max_step={steps}",
                           "amr.plot_int=-1", "amr.chk_int=-1"]
            if launcher and args.rank_wrapper:
                application = ["python3", str(args.rank_wrapper), *application]
            result[task].append([*mpi_launcher, *application])
    return result


def selected_tasks(args: argparse.Namespace) -> tuple[str, ...]:
    return tuple(task for task in (QUICK if args.mode == "quick" else FULL)
                 if args.only is None or task == args.only)


def make_plan(args: argparse.Namespace, root: Path, inventory: dict) -> dict:
    task_commands = commands(args, root)
    tasks = []
    selection = selected_tasks(args)
    for task in (QUICK if args.mode == "quick" else FULL):
        replay = [sys.executable, str(HERE / "run_tests.py"),
                  "--mode", args.mode, "--run-root", str(root) + "-retry"]
        if task != "scaling":
            replay += ["--only", task]
        for name in ("summary_binary", "timing_binary", "baseline_summary_binary",
                     "summary_build_dir", "timing_build_dir", "rank_wrapper"):
            value = getattr(args, name)
            if value is not None:
                replay += ["--" + name.replace("_", "-"), str(value)]
        replay += ["--mpirun", args.mpirun, "--mpi-options", args.mpi_options,
                   "--cmake", args.cmake,
                   "--stability-seconds", str(args.stability_seconds),
                   "--max-gpu-used-mib", str(args.max_gpu_used_mib)]
        planned_reason = prerequisite(task, args, inventory)
        if planned_reason and task not in ("build_summary", "build_timing") and (
                ("summary-binary" in planned_reason and args.summary_build_dir) or
                ("timing-binary" in planned_reason and args.timing_build_dir)):
            planned_reason = "binary expected after build"
        tasks.append({"id": task, "selected": task in selection,
                      "status": "not_run", "reason": "pending" if task in selection
                      else "filtered by --only", "commands": task_commands[task],
                      "planned_action": "run" if planned_reason is None else "defer",
                      "planned_reason": planned_reason,
                      "rerun_command": shlex.join(replay)})
    return {"schema_version": 1, "agent_version": VERSION,
            "config": str(CONFIG_PATH), "config_sha256": sha256(CONFIG_PATH),
            "mode": args.mode, "created_utc": inventory["utc"],
            "source_commit": inventory["git"]["commit"],
            "hardware_scope": "4 x Tesla V100-SXM2-32GB; GPU maps 0 / 0,2 / 0,1,2,3",
            "reference": {"historical_commit": P1_COMMIT,
                          "baseline_binary_commit_verified": False,
                          "physics": "reference_physics.csv",
                          "strong": "Reports/P1/tgv-modular-strong-256.json"},
            "criteria": {"physics": "nine frozen P1 checks on 64^3 and 128^3",
                         "compact": "23 positive/finite FP64 components; equal coordinate fingerprints across 1/2/4 GPU, numeric absolute difference <=1e-9; 10 and 11 steps",
                         "capacity": "536^3 >150M, 10-step pilot and >=100 steps, positive finite online diagnostics and measured peak GPU memory",
                         "scaling": "three repeats per 1/2/4 GPU, 100 warmup + 500 timed steps; strong T1/(N*TN), weak T1/TN, each 2/4 GPU efficiency >0.85",
                         "stability": f"one GPU, 256^3, >= {args.stability_seconds:g} s, online finite/positive metrics"},
            "no_full_field": True, "tasks": tasks}


def run_script(command: list[str], log: Path) -> dict:
    with log.open("w") as output:
        result = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT,
                                check=False)
    lines = log.read_text(errors="replace").splitlines()
    return {"command": command, "returncode": result.returncode,
            "log": str(log), "log_sha256": sha256(log),
            "log_tail": lines[-12:]}


def quick_precision(args: argparse.Namespace, root: Path) -> dict:
    runs: dict[str, dict] = {}
    for n in CONFIG["precision"]["grids"]:
        runs[str(n)] = {}
        for physical_time in CONFIG["precision"]["physical_times"]:
            step = int(physical_time * n / 64)
            row = precision.run_case(args.summary_binary, n, step, 8,
                                     root / "quick_precision" / str(n) /
                                     str(physical_time), list(AA_OPTIONS))
            runs[str(n)][str(physical_time)] = row
            if row["status"] != "passed":
                return {"status": row["status"], "reason": row.get("reason"),
                        "runs": runs}
    hashes = {case["binary_sha256"] for grid in runs.values()
              for case in grid.values()}
    if hashes != {sha256(args.summary_binary)}:
        return {"status": "failed", "reason": "summary binary changed between checkpoints",
                "runs": runs}
    checks = precision.physics_checks(runs, precision.LIMITS["fp64"])
    reference_checks = precision.reference_checks(runs)
    passed = all(checks.values()) and all(row["passed"] for row in
                                               reference_checks.values())
    return {"status": "passed" if passed else "failed", "runs": runs,
            "physics_checks": checks, "reference_checks": reference_checks,
            "classification": "P1 strict FP64"}


def compact(args: argparse.Namespace, root: Path, steps: int) -> dict:
    rows = {}
    binary_hash = sha256(args.summary_binary)
    for ranks in (1, 2, 4):
        row = summary.run(args.summary_binary, HERE / "inputs_physics_128",
                          root / f"compact_{'even' if steps == 10 else 'odd'}" /
                          f"{ranks}gpu", ranks, args.mpirun, args.mpi_options,
                          args.rank_wrapper, list(AA_OPTIONS), 23, steps)
        log = Path(row["log"]).read_text(errors="replace")
        if (f"Coarse STEP {steps} ends" not in log or
            not re.search(r"^AMReX \([^\n]+\) finalized$", log, re.M)):
            raise ValueError(f"final step or finalization missing: {row['log']}")
        if precision.PRECISION.findall(log) != ["8"]:
            raise ValueError(f"precision diagnostic missing or wrong: {row['log']}")
        metric = precision.parse_metric(log, 128, steps)
        if (metric["nonfinite"] != 0.0 or
            abs(metric["mean_rho"] - 1.0) > MASS_TOL):
            raise ValueError(f"invalid compact mass or nonfinite diagnostic: {row['log']}")
        precision.parse_fields(log)
        if capacity.full_field_files(Path(row["log"]).parent):
            raise ValueError(f"full-field output found: {row['log']}")
        row["metric"] = metric
        rows[str(ranks)] = row
        if sha256(args.summary_binary) != binary_hash:
            raise ValueError("summary binary changed during compact comparison")
    baseline = rows["1"]["fields"]
    checks = {}
    for ranks, row in rows.items():
        fields = row["fields"]
        max_difference = summary.max_numeric_difference(baseline, fields)
        hashes_equal = (baseline.keys() == fields.keys() and all(
            baseline[key][4:] == fields[key][4:] for key in baseline))
        halo = row["directional_halo_active"] and (
            int(ranks) == 1 or bool(row["rank0_halo_send_values"]))
        tolerance = CONFIG["precision"]["compact_numeric_atol"]
        checks[ranks] = {"max_numeric_abs_diff": max_difference,
                         "fingerprints_equal": hashes_equal,
                         "directional_halo": halo,
                         "passed": max_difference <= tolerance and hashes_equal and halo}
    return {"status": "passed" if all(v["passed"] for v in checks.values())
            else "failed", "steps": steps, "runs": rows, "checks": checks,
            "note": "compact fingerprints are not full-field bitwise proof"}


def stability(args: argparse.Namespace, root: Path) -> dict:
    directory = root / "stability"
    directory.mkdir()
    command = commands(args, root)["stability"][0]
    log_path = directory / "run.log"
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = "0"
    started = time.monotonic()
    with log_path.open("w") as output:
        code = subprocess.run(command, cwd=directory, env=env, stdout=output,
                              stderr=subprocess.STDOUT, check=False).returncode
    log = log_path.read_text(errors="replace")
    match = re.search(r"LBM wall time limit reached after ([0-9.eE+-]+) s at step (\d+)", log)
    steps = int(match.group(2)) if match else 0
    assessment = (capacity.assess_log(log, 256, steps, MASS_TOL, 8,
                                      require_online=True) if steps else None)
    fields = capacity.full_field_files(directory)
    problems = []
    if code:
        problems.append(f"exit code {code}")
    if not match or float(match.group(1)) < args.stability_seconds:
        problems.append("wall time target not observed")
    if steps <= 0 or assessment is None:
        problems.append("no completed step or online numerical assessment")
    if fields:
        problems.append("full-field output found")
    if assessment and assessment["status"] != "passed":
        problems.extend(assessment["problems"] + assessment["missing"])
    return {"status": "failed" if problems else "passed", "problems": problems,
            "returncode": code, "solver_seconds": float(match.group(1)) if match
            else None, "steps": steps, "wall_seconds": time.monotonic() - started,
            "command": command, "log": str(log_path),
            "log_sha256": sha256(log_path), "full_field_files": fields,
            "diagnostics": assessment}


def timing_diagnostics(report: dict, kind: str) -> tuple[bool, list[dict]]:
    """Check completed steps, mass, halo and output for every timed repeat."""
    evidence = []
    all_passed = True
    for row in report.get("runs", []):
        log_path = Path(row["log"])
        problems = []
        if not log_path.is_file() or sha256(log_path) != row["log_sha256"]:
            problems.append("timing log missing or hash changed")
        else:
            log = log_path.read_text(errors="replace")
            mass = re.findall(r"^Coarse STEP 600 ends\..*\bSum\(Rho\) = (\S+)",
                              log, re.M)
            expected = CONFIG["scaling"]["weak_cells_per_gpu"] * (
                row["gpus"] if kind == "weak" else 1)
            if len(mass) != 1:
                problems.append("final step or final mass diagnostic missing")
            else:
                try:
                    measured = float(mass[0])
                    if (not math.isfinite(measured) or
                        abs(measured - expected) / expected > MASS_TOL):
                        problems.append("final mass outside tolerance")
                except ValueError:
                    problems.append("invalid final mass diagnostic")
            if not re.search(r"^AMReX \([^\n]+\) finalized$", log, re.M):
                problems.append("AMReX finalization missing")
            if "LBM_DIRECTIONAL_HALO active=1" not in log:
                problems.append("directional halo diagnostic missing")
            if capacity.full_field_files(log_path.parent):
                problems.append("full-field output found")
        evidence.append({"gpus": row["gpus"], "repeat": row["repeat"],
                         "log": str(log_path), "problems": problems,
                         "passed": not problems})
        all_passed &= not problems
    return all_passed, evidence


def prerequisite(task: str, args: argparse.Namespace, inventory: dict) -> str | None:
    binaries = inventory["binaries"]
    if task == "build_summary":
        if args.summary_build_dir:
            return None if args.summary_build_dir.is_dir() else "summary CMake build directory unavailable"
        return (None if expected_binary(args.summary_binary, "lbm3d_tgv3d_summary")
                else "executable lbm3d_tgv3d_summary unavailable")
    if task == "build_timing":
        if args.timing_build_dir:
            return None if args.timing_build_dir.is_dir() else "timing CMake build directory unavailable"
        return (None if expected_binary(args.timing_binary, "lbm3d_tgv3d")
                else "executable lbm3d_tgv3d unavailable")
    if task == "scaling":
        return None
    required = ("timing_binary",) if task in ("strong", "weak") else (
        "baseline_summary_binary", "summary_binary") if task == "full_precision" else (
        "summary_binary",)
    for name in required:
        if not binaries[name]["available"]:
            return f"{name.replace('_', '-')} unavailable"
        target = ("lbm3d_tgv3d" if name == "timing_binary" else
                  "lbm3d_tgv3d_summary")
        if not expected_binary(getattr(args, name), target):
            return f"{name.replace('_', '-')} is not executable {target}"
    if task in ("compact_even", "compact_odd", "strong", "weak"):
        if args.rank_wrapper and not args.rank_wrapper.is_file():
            return "rank wrapper unavailable"
        if not inventory["mpi"]["available"]:
            return "MPI launcher unavailable"
        return v100_resources(inventory, (0, 1, 2, 3), args.max_gpu_used_mib)
    if task in ("quick_precision", "full_precision", "capacity", "stability"):
        return v100_resources(inventory, (0,), args.max_gpu_used_mib)
    return None


def check_task(task: str, args: argparse.Namespace, root: Path) -> dict:
    if task in ("build_summary", "build_timing"):
        binary = (args.summary_binary if task == "build_summary" else
                  args.timing_binary)
        build_dir = (args.summary_build_dir if task == "build_summary" else
                     args.timing_build_dir)
        result = {}
        if build_dir:
            command = commands(args, root)[task][0]
            result = run_script(command, root / f"{task}.log")
            if result["returncode"]:
                return {**result, "status": "failed", "reason": "CMake build failed"}
        target = ("lbm3d_tgv3d_summary" if task == "build_summary" else
                  "lbm3d_tgv3d")
        if not expected_binary(binary, target):
            return {**result, "status": "failed",
                    "reason": f"expected executable {target} missing after build"}
        return {**result, "status": "passed", "binary": binary_identity(binary),
                "verification": "cmake_build" if build_dir else "prebuilt_hash",
                "reason": "CMake build completed" if build_dir else
                          "prebuilt target filename, executable bit and hash verified"}
    if task == "quick_precision":
        return quick_precision(args, root)
    if task in ("compact_even", "compact_odd"):
        return compact(args, root, 10 if task == "compact_even" else 11)
    if task == "stability":
        return stability(args, root)
    command = commands(args, root)[task][0]
    result = run_script(command, root / f"{task}.log")
    report_path = {"full_precision": root / "full_precision" / "report.json",
                   "capacity": root / "capacity.json", "strong": root / "strong.json",
                   "weak": root / "weak.json"}.get(task)
    if task == "scaling":
        try:
            result["assessment"] = json.loads((root / "scaling.log").read_text())
        except json.JSONDecodeError:
            result["assessment"] = {}
        if not isinstance(result["assessment"], dict):
            result["assessment"] = {}
        result["status"] = ("passed" if result["returncode"] == 0 and
                            result["assessment"].get("passed") else "failed")
    elif report_path and report_path.is_file():
        result["report"] = str(report_path)
        result["report_sha256"] = sha256(report_path)
        report = json.loads(report_path.read_text())
        if task == "full_precision":
            result["classification"] = report["status"]
            passed = report["status"] == "passed"
            hashes = {variant: {case["binary_sha256"]
                        for grid in runs.values() for case in grid.values()}
                      for variant, runs in report["runs"].items()}
            passed &= (hashes.get("baseline") ==
                       {sha256(args.baseline_summary_binary)} and
                       hashes.get("candidate") == {sha256(args.summary_binary)})
            result["run_binary_hashes"] = {name: sorted(values)
                                            for name, values in hashes.items()}
        elif task == "capacity":
            passed = report["status"] == "passed"
            result["peak_mib"] = [row.get("gpu_peak_mib") for row in
                                   report.get("runs", [])]
        elif task in ("strong", "weak"):
            diagnostics_passed, diagnostics = timing_diagnostics(report, task)
            result["run_diagnostics"] = diagnostics
            passed = (len(report.get("runs", [])) == 9 and diagnostics_passed and
                      report.get("binary_sha256") == sha256(args.timing_binary))
            result["summary"] = report.get("summary")
            if task == "strong" and passed:
                p1_path = SOURCE / "Reports/P1/tgv-modular-strong-256.json"
                p1 = json.loads(p1_path.read_text())
                result["p1_historical_step_time_ratio"] = {
                    str(n): report["summary"][str(n)]["median_sec_per_step"] /
                    p1["summary"][str(n)]["median_sec_per_step"]
                    for n in (1, 2, 4)}
                result["p1_reference_sha256"] = sha256(p1_path)
        result["status"] = ("passed" if result["returncode"] == 0 and passed
                            else "failed")
    else:
        result["status"] = "failed"
    if result["status"] == "failed":
        result["reason"] = "see driver log and case logs for the first failing check"
    return result


def markdown(plan: dict, report: dict) -> str:
    lines = [f"# TGV3D test run ({plan['mode']})", "",
             f"Agent {VERSION}; status **{report['status']}**; "
             f"commit `{plan['source_commit'] or 'unknown'}`.", "",
             "| Check | Status | Evidence / reason |", "| --- | --- | --- |"]
    for task in report["tasks"]:
        evidence = task.get("reason") or task.get("report") or task.get("log") or ""
        lines.append(f"| {task['id']} | {task['status']} | {str(evidence).replace('|', '/')} |")
    if report.get("provenance_problems"):
        lines += ["", "Provenance: " + "; ".join(report["provenance_problems"])]
    tasks = {task["id"]: task for task in report["tasks"]}
    quick = tasks.get("quick_precision", {})
    if quick.get("physics_checks"):
        physics = quick["physics_checks"]
        reference = quick["reference_checks"]
        lines += ["", f"Online physics: {sum(physics.values())}/{len(physics)} "
                  f"P1 checks; {sum(row['passed'] for row in reference.values())}/"
                  f"{len(reference)} scalar reference checks."]
    cap = tasks.get("capacity", {})
    if cap.get("peak_mib"):
        lines += ["", "536³ capacity GPU peak MiB (pilot, sustained): " +
                  ", ".join(str(value) for value in cap["peak_mib"]) + "."]
    if tasks.get("strong", {}).get("summary") and tasks.get("weak", {}).get("summary"):
        strong = tasks["strong"]
        weak = tasks["weak"]
        assessment = tasks.get("scaling", {}).get("assessment") or {}
        lines += ["", "## Performance", "",
                  "| GPU | Strong ms/step | Weak ms/step | Strong efficiency | Weak efficiency | P1 strong time ratio |",
                  "| ---: | ---: | ---: | ---: | ---: | ---: |"]
        for n in (1, 2, 4):
            key = str(n)
            strong_ms = 1000 * strong["summary"][key]["median_sec_per_step"]
            weak_ms = 1000 * weak["summary"][key]["median_sec_per_step"]
            strong_eff = assessment.get("strong", {}).get(key)
            weak_eff = assessment.get("weak", {}).get(key)
            p1_ratio = strong.get("p1_historical_step_time_ratio", {}).get(key)
            strong_text = f"{strong_eff:.1%}" if strong_eff is not None else "—"
            weak_text = f"{weak_eff:.1%}" if weak_eff is not None else "—"
            p1_text = f"{p1_ratio:.3f}" if p1_ratio is not None else "—"
            lines.append(f"| {n} | {strong_ms:.3f} | {weak_ms:.3f} | "
                         f"{strong_text} | {weak_text} | {p1_text} |")
        lines += ["", "P1 ratios compare historical wall time only. The >85% "
                  "efficiency gate uses this run's own single-GPU median."]
    lines += ["", "## Reproduce", ""]
    for task in report["tasks"]:
        if task["status"] != "passed" and task["selected"]:
            lines.append(f"- {task['id']}: `{task['rerun_command']}`")
    lines += ["", "`plan.json` was saved before execution. `result.json` and case "
              "logs contain hashes, inputs, commands, diagnostics, and failures.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("quick", "full"), default="quick")
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--summary-binary", type=Path)
    parser.add_argument("--timing-binary", type=Path)
    parser.add_argument("--baseline-summary-binary", type=Path)
    parser.add_argument("--summary-build-dir", type=Path)
    parser.add_argument("--timing-build-dir", type=Path)
    parser.add_argument("--mpirun", default="mpirun")
    parser.add_argument("--cmake", default="cmake")
    parser.add_argument("--mpi-options", default="")
    parser.add_argument("--rank-wrapper", type=Path)
    parser.add_argument("--stability-seconds", type=float,
                        default=CONFIG["stability"]["duration_seconds"])
    parser.add_argument("--max-gpu-used-mib", type=int,
                        default=CONFIG["hardware"]["maximum_idle_memory_used_mib"])
    parser.add_argument("--only", choices=FULL)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    if args.only == "scaling":
        parser.error("scaling requires fresh strong and weak reports; rerun full mode")
    if CONFIG["agent_version"] != VERSION or any(
            CONFIG["hardware"]["gpu_maps"][str(n)] != visible
            for configs in (summary.CONFIGS, run_strong.CONFIGS, run_weak.CONFIGS)
            for n, (visible, _) in configs.items()):
        parser.error("test_config.json version or GPU maps differ from drivers")
    if args.only and args.only not in (QUICK if args.mode == "quick" else FULL):
        parser.error("--only task is outside the chosen mode")
    if args.stability_seconds <= 0 or not math.isfinite(args.stability_seconds):
        parser.error("--stability-seconds must be finite and positive")
    if (args.mode == "full" and args.stability_seconds <
            CONFIG["stability"]["duration_seconds"]):
        parser.error("full acceptance stability duration cannot be shortened")
    if args.max_gpu_used_mib < 0:
        parser.error("--max-gpu-used-mib must be nonnegative")
    for name in ("summary_binary", "timing_binary", "baseline_summary_binary",
                 "summary_build_dir", "timing_build_dir", "rank_wrapper"):
        value = getattr(args, name)
        if value is not None:
            setattr(args, name, value.resolve())
    for name, target in (("summary", "lbm3d_tgv3d_summary"),
                         ("timing", "lbm3d_tgv3d")):
        build_dir = getattr(args, f"{name}_build_dir")
        binary = getattr(args, f"{name}_binary")
        if build_dir:
            built_binary = build_dir / target
            if binary and binary != built_binary:
                parser.error(f"--{name}-binary must be {built_binary} when building")
            setattr(args, f"{name}_binary", built_binary)
    root = args.run_root.resolve()
    if root.exists():
        parser.error(f"run root already exists: {root}")
    inventory = environment(args)
    plan = make_plan(args, root, inventory)
    root.mkdir(parents=True)
    write_json(root / "environment.json", inventory)
    write_json(root / "plan.json", plan)
    report = {"schema_version": 1, "agent_version": VERSION,
              "mode": args.mode, "status": "not_run", "tasks": plan["tasks"],
              "baseline_binary_provenance": {
                  "source_commit_verified": False,
                  "scope": "supplied FP64 P1 diagnostic build; source relationship not proven by SHA-256",
                  "sha256": inventory["binaries"]["baseline_summary_binary"].get("sha256")},
              "plan": str(root / "plan.json"), "environment": str(root / "environment.json")}
    write_json(root / "result.json", report)
    for task in report["tasks"]:
        if not task["selected"] or args.plan_only:
            task["reason"] = "plan only" if args.plan_only and task["selected"] else task["reason"]
            continue
        past = {row["id"]: row for row in report["tasks"]}
        if (task["id"] in ("quick_precision", "compact_even", "compact_odd",
                           "full_precision", "capacity", "stability") and
            past["build_summary"]["status"] == "failed"):
            task["reason"] = "summary build failed"
            continue
        if (task["id"] in ("strong", "weak") and
            past["build_timing"]["status"] == "failed"):
            task["reason"] = "timing build failed"
            continue
        if (task["id"] == "capacity" and
            past["full_precision"]["status"] == "failed"):
            task["reason"] = "full precision failed"
            continue
        if task["id"] == "scaling" and not all(
                row["status"] == "passed" for row in report["tasks"] if
                row["id"] in ("strong", "weak")):
            task["reason"] = "strong and weak reports are required"
            continue
        inventory = environment(args)
        reason = prerequisite(task["id"], args, inventory)
        if reason:
            task["reason"] = reason
            continue
        print(f"{task['id']}: running", flush=True)
        try:
            outcome = check_task(task["id"], args, root)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError,
                subprocess.SubprocessError) as error:
            outcome = {"status": "failed", "reason": str(error)}
        task.update(outcome)
        write_json(root / "result.json", report)
        print(f"{task['id']}: {task['status']}", flush=True)
    statuses = [task["status"] for task in report["tasks"]]
    report["status"] = ("failed" if "failed" in statuses else
                        "not_run" if "not_run" in statuses
                        else "passed")
    report["completed_utc"] = datetime.now(timezone.utc).isoformat()
    final_environment = environment(args)
    write_json(root / "environment_after.json", final_environment)
    report["environment_after"] = str(root / "environment_after.json")
    provenance_problems = []
    if final_environment["git"]["commit"] != plan["source_commit"]:
        provenance_problems.append("source commit changed during run")
    if final_environment["git"]["status"] != inventory["git"]["status"]:
        provenance_problems.append("source worktree changed during run")
    if final_environment["inputs_sha256"] != inventory["inputs_sha256"]:
        provenance_problems.append("test inputs changed during run")
    for task_name, binary_name in (("build_summary", "summary_binary"),
                                   ("build_timing", "timing_binary")):
        build_task = next((row for row in report["tasks"]
                           if row["id"] == task_name), None)
        if build_task and build_task["status"] == "passed" and (
                build_task["binary"]["sha256"] !=
                final_environment["binaries"][binary_name].get("sha256")):
            provenance_problems.append(f"{binary_name} changed after verification")
    if provenance_problems:
        report["provenance_problems"] = provenance_problems
        report["status"] = "failed"
    write_json(root / "result.json", report)
    (root / "report.md").write_text(markdown(plan, report))
    history = root.parent / "history.json"
    previous = json.loads(history.read_text()) if history.is_file() else {"schema_version": 1,
                                                                            "runs": []}
    previous["runs"].append({"root": str(root), "mode": args.mode,
                             "commit": plan["source_commit"],
                             "status": report["status"],
                             "completed_utc": report["completed_utc"],
                             "plan": str(root / "plan.json"),
                             "result": str(root / "result.json"),
                             "report": str(root / "report.md")})
    write_json(history, previous)
    print(f"{report['status']}: {root / 'report.md'}", flush=True)
    if report["status"] != "passed":
        raise SystemExit(1 if report["status"] == "failed" else 2)


if __name__ == "__main__":
    main()
