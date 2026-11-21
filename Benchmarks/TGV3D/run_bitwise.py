"""Probe 1/2/4 GPU rho and velocity bit patterns at steps 0 and 10."""

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


CONFIGS = {
    1: ("0", []),
    2: ("0,2", ["mpirun", "--map-by", "ppr:1:numa", "--bind-to", "numa", "-np", "2"]),
    4: ("0,1,2,3", ["mpirun", "--map-by", "ppr:2:numa", "--bind-to", "numa", "-np", "4"]),
}
COMPARISON = re.compile(r"BIT_COMPARE var=(\w+) mismatches=(\d+) first_local=\(([^)]+)\)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("comparator", type=Path)
    parser.add_argument("input", type=Path)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve()
    comparator = args.comparator.resolve()
    input_path = args.input.resolve()
    args.run_root.mkdir(parents=True, exist_ok=True)
    rows = []

    for ranks, (visible, launcher) in CONFIGS.items():
        run_dir = args.run_root / f"{ranks}gpu"
        run_dir.mkdir(exist_ok=True)
        command = [*launcher, str(binary), str(input_path)]
        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = visible
        log = run_dir / "run.log"
        print(f"bitwise: running {ranks} GPU", flush=True)
        with log.open("w") as output:
            result = subprocess.run(command, cwd=run_dir, env=env,
                                    stdout=output, stderr=subprocess.STDOUT)
        if result.returncode or not (run_dir / "plt00010").exists():
            raise RuntimeError(f"bitwise probe failed: {log}")
        rows.append({"gpus": ranks, "command": command, "log": str(log.resolve())})

    comparisons = []
    for ranks in (2, 4):
        for step in (0, 10):
            reference = args.run_root / "1gpu" / f"plt{step:05d}"
            other = args.run_root / f"{ranks}gpu" / f"plt{step:05d}"
            result = subprocess.run([str(comparator), str(reference), str(other)],
                                    text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT)
            fields = {name: {"mismatches": int(count), "first_local": first}
                      for name, count, first in COMPARISON.findall(result.stdout)}
            if len(fields) != 4:
                raise RuntimeError(f"incomplete comparator output: {result.stdout}")
            comparisons.append({"gpus": ranks, "step": step, "fields": fields,
                                "bitwise_equal": all(x["mismatches"] == 0
                                                     for x in fields.values())})
            print(f"  1 vs {ranks} GPU step {step}: {fields}", flush=True)

    report = {"binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
              "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
              "runs": rows, "comparisons": comparisons}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(f"report={args.report}", flush=True)


if __name__ == "__main__":
    main()
