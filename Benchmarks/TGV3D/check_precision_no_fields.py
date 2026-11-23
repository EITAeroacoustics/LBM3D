"""Run TGV physics without field files and compare a fresh FP64 baseline.

The lbm3d_tgv3d_summary target must print one final TGV_METRICS row and the
23 final FIELD_SUMMARY rows.  Each physical checkpoint runs in a separate
process, so the solver does not need a diagnostic hook inside Evolve().
Missing diagnostics never count as passing tests.

The nine P1 physics checks are reported with their original FP64 limits.
FP32 additionally has separately named, predeclared physical-equivalence
limits and never receives a P1-strict pass label by accident.

Example on a GPU workstation:

  python3 check_precision_no_fields.py BASELINE_BINARY CANDIDATE_BINARY RUN_ROOT \
      --candidate-precision fp64

Each invocation uses a new RUN_ROOT.  The two input files are the checked-in
P1 physics cases; command-line overrides disable plotfiles and checkpoints.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import subprocess
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent
METRICS = re.compile(r"^TGV_METRICS (.+)$", re.M)
PRECISION = re.compile(r"^TGV_PRECISION real_bytes=(\d+)$", re.M)
FIELDS = re.compile(
    r"^FIELD_SUMMARY lev=(\d+) comp=(\d+) "
    r"sum=(\S+) norm2=(\S+) min=(\S+) max=(\S+) "
    r"hash0=(\d+) hash1=(\d+)$", re.M)
EXPECTED_COMPONENTS = {0, 1, 2, 3, *range(6, 25)}
CHECKPOINTS = (0.0, 32.0, 64.0)
LIMITS = {
    "fp64": {"initial": 1.0e-12, "mass": 1.0e-8,
             "energy_to_fp64": 1.0e-8, "rho_to_fp64": 1.0e-9,
             "field_atol": 1.0e-10, "field_rtol": 1.0e-10},
    "fp32": {"initial": 5.0e-7, "mass": 1.0e-6,
             "energy_to_fp64": 1.0e-3, "rho_to_fp64": 1.0e-6,
             "field_atol": 1.0e-5, "field_rtol": 1.0e-4},
}


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def full_field_files(directory: Path) -> list[str]:
    return sorted(str(path.relative_to(directory)) for path in directory.rglob("*")
                  if path.name.lower().startswith(("plt", "chk", "checkpoint"))
                  or path.suffix.lower() in (".h5", ".hdf5", ".bp"))


def numbers(fields: dict[str, str], names: tuple[str, ...]) -> dict[str, float]:
    result = {name: float(fields[name]) for name in names}
    if not all(math.isfinite(value) for value in result.values()):
        raise ValueError("TGV diagnostic has a non-finite metric")
    return result


def parse_metric(log: str, n: int, step: int) -> dict:
    rows = []
    for match in METRICS.finditer(log):
        fields = dict(word.split("=", 1) for word in match.group(1).split()
                      if "=" in word)
        values = numbers(fields, ("step", "time", "cells", "mean_rho",
                                  "mean_kinetic", "init_linf", "nonfinite"))
        rows.append(values)
    physical_time = 64.0 * step / n
    if len(rows) != 1:
        raise ValueError(f"expected one final TGV_METRICS row, found {len(rows)}")
    row = rows[0]
    if (row["step"] != step or row["time"] != physical_time or
        row["cells"] != n**3 or row["nonfinite"] not in (0.0, 1.0) or
        row["mean_rho"] <= 0.0 or row["mean_kinetic"] <= 0.0 or
        row["init_linf"] < 0.0):
        raise ValueError(f"invalid TGV metric at grid {n}, time {physical_time}")
    return row


def parse_fields(log: str) -> dict[str, dict]:
    fields = {}
    matches = FIELDS.findall(log)
    if not matches:
        raise ValueError("missing FIELD_SUMMARY diagnostic")
    for level, component, total, norm2, minimum, maximum, hash0, hash1 in matches:
        if level != "0" or int(component) not in EXPECTED_COMPONENTS or \
           component in fields:
            raise ValueError("unexpected or duplicate FIELD_SUMMARY component")
        values = [float(value) for value in (total, norm2, minimum, maximum)]
        if not all(math.isfinite(value) for value in values) or \
           values[1] < 0.0 or values[2] > values[3]:
            raise ValueError("invalid FIELD_SUMMARY value")
        fields[component] = dict(zip(("sum", "norm2", "min", "max"), values))
        fields[component].update(hash0=int(hash0), hash1=int(hash1))
    if {int(component) for component in fields} != EXPECTED_COMPONENTS:
        raise ValueError(f"expected 23 FIELD_SUMMARY components, found {len(fields)}")
    if fields["0"]["min"] <= 0.0 or \
       any(fields[str(component)]["min"] <= 0.0 for component in range(6, 25)):
        raise ValueError("nonpositive density or distribution function")
    return fields


def physics_checks(runs: dict[str, dict], limits: dict) -> dict[str, bool]:
    checks = {}
    for n in (64, 128):
        rows = {time: runs[str(n)][str(int(time))]["metric"]
                for time in CHECKPOINTS}
        initial = rows[0.0]
        energy = [rows[time]["mean_kinetic"] for time in CHECKPOINTS]
        checks[f"initial_{n}"] = (initial["init_linf"] <= limits["initial"] and
                                  abs(initial["mean_rho"] - 1.0) <= limits["initial"])
        checks[f"mass_{n}"] = all(
            abs(rows[t]["mean_rho"] - initial["mean_rho"]) /
            initial["mean_rho"] <= limits["mass"] for t in (32.0, 64.0))
        checks[f"decay_{n}"] = energy[0] > energy[1] > energy[2] > 0.0
    for physical_time in (32, 64):
        coarse = runs["64"][str(physical_time)]["metric"]["mean_kinetic"]
        fine = runs["128"][str(physical_time)]["metric"]["mean_kinetic"]
        checks[f"two_grid_{physical_time}"] = abs(coarse - fine) / fine <= 0.05
    checks["finite"] = all(
        case["metric"]["nonfinite"] == 0.0 for grid in runs.values()
        for case in grid.values())
    return checks


def reference_checks(baseline: dict[str, dict]) -> dict[str, dict]:
    with (HERE / "reference_physics.csv").open(newline="") as source:
        reference = {(row["grid"], str(int(float(row["time"])))): row
                     for row in csv.DictReader(source)}
    checks = {}
    for n in (64, 128):
        for physical_time in (0, 32, 64):
            actual = baseline[str(n)][str(physical_time)]["metric"]
            expected = reference[str(n), str(physical_time)]
            rho = float(expected["mean_rho"])
            energy = float(expected["mean_kinetic"])
            checks[f"{n}:{physical_time}"] = {
                "mean_rho_abs_error": abs(actual["mean_rho"] - rho),
                "mean_kinetic_rel_error": abs(actual["mean_kinetic"] - energy) / energy,
                "passed": abs(actual["mean_rho"] - rho) <= 1.0e-10 and
                          abs(actual["mean_kinetic"] - energy) / energy <= 1.0e-8,
            }
    return checks


def baseline_comparison(baseline: dict[str, dict], candidate: dict[str, dict],
                        limits: dict) -> dict:
    worst_field = {"ratio": 0.0}
    checks = {}
    all_fields = True
    for n in (64, 128):
        for physical_time in (0, 32, 64):
            old = baseline[str(n)][str(physical_time)]["metric"]
            new = candidate[str(n)][str(physical_time)]["metric"]
            rho_error = abs(new["mean_rho"] - old["mean_rho"])
            energy_error = (abs(new["mean_kinetic"] - old["mean_kinetic"]) /
                            old["mean_kinetic"])
            checks[f"{n}:{physical_time}"] = {
                "rho_abs_error": rho_error, "energy_rel_error": energy_error,
                "passed": rho_error <= limits["rho_to_fp64"] and
                          energy_error <= limits["energy_to_fp64"],
            }
            old_fields = baseline[str(n)][str(physical_time)]["fields"]
            new_fields = candidate[str(n)][str(physical_time)]["fields"]
            for component in old_fields:
                for statistic in ("sum", "norm2", "min", "max"):
                    old = old_fields[component][statistic]
                    new = new_fields[component][statistic]
                    if statistic == "sum":
                        old /= n**3
                        new /= n**3
                    elif statistic == "norm2":
                        old /= math.sqrt(n**3)
                        new /= math.sqrt(n**3)
                    ratio = abs(old - new) / (limits["field_atol"] +
                                              limits["field_rtol"] *
                                              max(abs(old), abs(new)))
                    if ratio > worst_field["ratio"]:
                        worst_field = {"ratio": ratio, "grid": n,
                                       "time": physical_time,
                                       "component": component,
                                       "statistic": statistic,
                                       "baseline": old, "candidate": new}
                    all_fields &= ratio <= 1.0
    return {"checkpoints": checks, "worst_field": worst_field,
            "fields_passed": all_fields,
            "passed": all(row["passed"] for row in checks.values()) and all_fields}


def run_case(binary: Path, n: int, step: int, real_bytes: int, directory: Path,
             extra_options: list[str]) -> dict:
    directory.mkdir(parents=True)
    inputs = HERE / f"inputs_physics_{n}"
    command = [str(binary), str(inputs), f"max_step={step}",
               "amr.plot_int=-1", "amr.chk_int=-1", *extra_options]
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = "0"
    binary_hash = sha256(binary)
    input_hash = sha256(inputs)
    start = time.monotonic()
    with (directory / "run.log").open("w") as output:
        code = subprocess.run(command, cwd=directory, env=env, stdout=output,
                              stderr=subprocess.STDOUT).returncode
    elapsed = time.monotonic() - start
    log = (directory / "run.log").read_text(errors="replace")
    result = {"binary": str(binary), "binary_sha256": binary_hash,
              "input": str(inputs), "input_sha256": input_hash,
              "command": command, "returncode": code,
              "log": str((directory / "run.log").resolve()),
              "log_sha256": sha256(directory / "run.log"),
              "elapsed_seconds": elapsed,
              "full_field_files": full_field_files(directory)}
    if (code or result["full_field_files"] or
        sha256(binary) != binary_hash or sha256(inputs) != input_hash or
        (step > 0 and f"Coarse STEP {step} ends" not in log) or
        "finalized" not in log):
        result["status"] = "failed"
        result["reason"] = "process, final step, or no-full-field requirement failed"
        return result
    try:
        precision = PRECISION.findall(log)
        if len(precision) != 1:
            raise ValueError("missing TGV_PRECISION diagnostic")
        result["real_bytes"] = int(precision[0])
        if result["real_bytes"] != real_bytes:
            raise ValueError(f"expected {real_bytes}-byte Real, got "
                             f"{result['real_bytes']}-byte Real")
        result["metric"] = parse_metric(log, n, step)
        result["fields"] = parse_fields(log)
    except (KeyError, ValueError) as error:
        result["status"] = "failed"
        result["reason"] = str(error)
        return result
    result["status"] = "passed"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline_binary", type=Path)
    parser.add_argument("candidate_binary", type=Path)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--candidate-precision", choices=LIMITS, default="fp64")
    parser.add_argument("--candidate-real-bytes", type=int, choices=(4, 8),
                        help="actual sizeof(amrex::Real); defaults to 8 for fp64, 4 for fp32")
    parser.add_argument("--candidate-option", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if any(option.split("=", 1)[0] in
           {"max_step", "amr.plot_int", "amr.chk_int"}
           for option in args.candidate_option):
        parser.error("candidate-option cannot override steps or field output")

    baseline = args.baseline_binary.resolve()
    candidate = args.candidate_binary.resolve()
    root = args.run_root.resolve()
    candidate_real_bytes = (args.candidate_real_bytes if
                            args.candidate_real_bytes is not None else
                            8 if args.candidate_precision == "fp64" else 4)
    plan = {variant: {str(n): {
                str(int(time)): [str(binary), str(HERE / f"inputs_physics_{n}"),
                                 f"max_step={int(time * n / 64)}",
                                 "amr.plot_int=-1", "amr.chk_int=-1", *options]
                for time in CHECKPOINTS}
                for n in (64, 128)}
            for variant, binary, options in
            (("baseline", baseline, []),
             ("candidate", candidate, args.candidate_option))}
    if args.dry_run:
        print(json.dumps(plan, indent=2))
        return
    if root.exists():
        parser.error(f"run_root already exists: {root}")
    if not baseline.is_file() or not candidate.is_file():
        parser.error("both binaries must exist")
    if baseline == candidate:
        parser.error("fresh baseline and candidate must be separate binaries")
    root.mkdir(parents=True)

    runs = {"baseline": {}, "candidate": {}}
    for variant, binary in (("baseline", baseline), ("candidate", candidate)):
        for n in (64, 128):
            runs[variant][str(n)] = {}
            options = [] if variant == "baseline" else args.candidate_option
            real_bytes = 8 if variant == "baseline" else candidate_real_bytes
            for physical_time in CHECKPOINTS:
                step = int(physical_time * n / 64)
                print(f"running {variant} TGV {n}^3 to t={physical_time:g}",
                      flush=True)
                runs[variant][str(n)][str(int(physical_time))] = run_case(
                    binary, n, step, real_bytes,
                    root / variant / str(n) / str(int(physical_time)), options)
    report = {"schema_version": 1,
              "candidate_precision": args.candidate_precision,
              "candidate_real_bytes": candidate_real_bytes,
              "limits": LIMITS[args.candidate_precision],
              "reference": {"path": str(HERE / "reference_physics.csv"),
                            "sha256": sha256(HERE / "reference_physics.csv")},
              "runs": runs, "checks": {}, "status": "not_run"}
    states = [case["status"] for variant in runs.values()
              for grid in variant.values() for case in grid.values()]
    if all(state == "passed" for state in states):
        physics_baseline = physics_checks(runs["baseline"], LIMITS["fp64"])
        physics_candidate_strict = physics_checks(runs["candidate"],
                                                  LIMITS["fp64"])
        physics_candidate_mode = physics_checks(runs["candidate"],
                                                LIMITS[args.candidate_precision])
        reference = reference_checks(runs["baseline"])
        comparison = baseline_comparison(runs["baseline"], runs["candidate"],
                                         LIMITS[args.candidate_precision])
        report["checks"] = {"baseline_p1_physics": physics_baseline,
                            "candidate_p1_strict": physics_candidate_strict,
                            "candidate_mode_physics": physics_candidate_mode,
                            "p1_reference": reference,
                            "candidate_to_fp64": comparison}
        report["candidate_p1_strict_passed"] = all(
            physics_candidate_strict.values())
        equivalent = (all(physics_baseline.values()) and
                      all(physics_candidate_mode.values()) and
                      all(row["passed"] for row in reference.values()) and
                      comparison["passed"])
        report["status"] = ("passed" if equivalent and
                            args.candidate_precision == "fp64" and
                            report["candidate_p1_strict_passed"] else
                            "passed_fp32_equivalence" if equivalent and
                            args.candidate_precision == "fp32" else "failed")
    elif "failed" in states:
        report["status"] = "failed"
    (root / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"precision acceptance: {report['status']} ({root / 'report.json'})")
    if report["status"] not in ("passed", "passed_fp32_equivalence"):
        raise SystemExit(2 if report["status"] == "not_run" else 1)


if __name__ == "__main__":
    main()
