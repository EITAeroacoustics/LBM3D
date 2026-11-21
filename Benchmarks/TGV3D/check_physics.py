"""Analyze the two TGV3D runs and apply the frozen P1 physics criteria."""

import argparse
import csv
import hashlib
import json
import re
import subprocess
from pathlib import Path


METRIC = re.compile(r"TGV_METRICS (.+)")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def analyze(binary: Path, plot: Path) -> dict:
    result = subprocess.run([str(binary), str(plot)], text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            check=True)
    match = METRIC.search(result.stdout)
    if not match:
        raise RuntimeError(f"no TGV_METRICS in analyzer output for {plot}\n{result.stdout}")
    fields = dict(item.split("=", 1) for item in match.group(1).split())
    return {
        "step": int(fields["step"]), "time": float(fields["time"]),
        "cells": int(fields["cells"]), "mean_rho": float(fields["mean_rho"]),
        "mean_kinetic": float(fields["mean_kinetic"]),
        "init_linf": float(fields["init_linf"]),
        "nonfinite": bool(int(fields["nonfinite"])),
        "plotfile": str(plot.resolve()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("analyzer", type=Path)
    parser.add_argument("run64", type=Path)
    parser.add_argument("run128", type=Path)
    parser.add_argument("output", type=Path, help="JSON report path")
    args = parser.parse_args()

    rows = []
    for n, directory, steps in ((64, args.run64, (0, 32, 64)),
                                (128, args.run128, (0, 64, 128))):
        for step in steps:
            row = analyze(args.analyzer, directory / f"plt{step:05d}")
            row["grid"] = n
            rows.append(row)

    by_key = {(row["grid"], row["time"]): row for row in rows}
    checks = {}
    for n in (64, 128):
        initial = by_key[n, 0.0]
        energies = [by_key[n, t]["mean_kinetic"] for t in (0.0, 32.0, 64.0)]
        checks[f"initial_{n}"] = (initial["init_linf"] <= 1e-12 and
                                   abs(initial["mean_rho"] - 1.0) <= 1e-12)
        checks[f"mass_{n}"] = all(
            abs(by_key[n, t]["mean_rho"] - initial["mean_rho"]) /
            initial["mean_rho"] <= 1e-8 for t in (32.0, 64.0))
        checks[f"decay_{n}"] = energies[0] > energies[1] > energies[2] > 0
    for t in (32.0, 64.0):
        coarse = by_key[64, t]["mean_kinetic"]
        fine = by_key[128, t]["mean_kinetic"]
        checks[f"two_grid_{int(t)}"] = abs(coarse - fine) / fine <= 0.05
    checks["finite"] = not any(row["nonfinite"] for row in rows)

    report = {
        "protocol": "Benchmarks/TGV3D/protocol.md",
        "analyzer_sha256": sha256(args.analyzer),
        "input_sha256": {
            "64": sha256(Path(__file__).with_name("inputs_physics_64")),
            "128": sha256(Path(__file__).with_name("inputs_physics_128")),
        },
        "measurements": rows, "checks": checks,
        "passed": all(checks.values()),
    }
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    csv_path = args.output.with_suffix(".csv")
    with csv_path.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys(),
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(checks, indent=2))
    print(f"passed={report['passed']} report={args.output} csv={csv_path}")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
