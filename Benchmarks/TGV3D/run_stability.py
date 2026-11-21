"""Run six ten-minute TGV3D stability cases and save resource evidence."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path


CONFIGS = {
    1: ([0], []),
    2: ([0, 2], ["mpirun", "--map-by", "ppr:1:numa", "--bind-to", "numa", "-np", "2"]),
    4: ([0, 1, 2, 3], ["mpirun", "--map-by", "ppr:2:numa", "--bind-to", "numa", "-np", "4"]),
}
WALL_LIMIT = re.compile(r"LBM wall time limit reached after ([0-9.eE+-]+) s at step (\d+)")


def gpu_memory() -> dict[int, int]:
    output = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=index,memory.used", "--format=csv,noheader,nounits"],
        text=True)
    return {int(index.strip()): int(used.strip()) for index, used in
            (line.split(",", 1) for line in output.splitlines())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("capacity_report", type=Path)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--duration", type=float, default=600.0)
    args = parser.parse_args()
    binary = args.binary.resolve()
    case_dir = args.case_dir.resolve()
    limits = json.loads(args.capacity_report.read_text())["limits"]
    args.run_root.mkdir(parents=True, exist_ok=True)
    rows = []

    for ranks, (devices, launcher) in CONFIGS.items():
        max_n = limits[str(ranks)]["max_success_n"]
        capacity_n = int((0.8 * max_n**3)**(1.0 / 3.0) // 8) * 8
        for kind, n in (("fixed", 256), ("capacity80", capacity_n)):
            run_dir = args.run_root / f"{ranks}gpu-{kind}-{n}"
            run_dir.mkdir(exist_ok=True)
            inputs = run_dir / "inputs"
            subprocess.run(["python3", str(case_dir / "make_inputs.py"),
                            "capacity", str(n), str(inputs)], check=True)
            command = [*launcher, str(binary), str(inputs),
                       "max_step=100000", "stop_time=100000",
                       "amr.plot_file=plt", "amr.plot_int=100000",
                       "amr.chk_int=-1", f"lbm3d.wall_time_limit_s={args.duration}"]
            env = os.environ.copy()
            env["CUDA_VISIBLE_DEVICES"] = ",".join(map(str, devices))
            log = run_dir / "run.log"
            peaks = {device: 0 for device in devices}
            start = time.monotonic()
            print(f"stability: {ranks} GPU {kind} {n}³ for {args.duration} s", flush=True)
            with log.open("w") as output:
                proc = subprocess.Popen(command, cwd=run_dir, env=env,
                                        stdout=output, stderr=subprocess.STDOUT)
                while proc.poll() is None:
                    current = gpu_memory()
                    for device in devices:
                        peaks[device] = max(peaks[device], current[device])
                    time.sleep(1.0)
                returncode = proc.wait()
            log_text = log.read_text(errors="replace")
            match = WALL_LIMIT.search(log_text)
            plots = sorted(path.name for path in run_dir.glob("plt[0-9]*") if path.is_dir())
            complete = (returncode == 0 and match is not None and
                        float(match.group(1)) >= args.duration and
                        "finalized" in log_text and len(plots) >= 2)
            row = {
                "gpus": ranks, "kind": kind, "n": n, "cells": n**3,
                "capacity_fraction": (n / max_n)**3 if kind == "capacity80" else None,
                "visible_devices": devices, "peak_vram_mib": peaks,
                "solver_elapsed_s": float(match.group(1)) if match else None,
                "completed_steps": int(match.group(2)) if match else None,
                "process_wall_s": time.monotonic() - start,
                "plotfiles": plots, "returncode": returncode,
                "complete": complete, "command": command,
                "input_sha256": hashlib.sha256(inputs.read_bytes()).hexdigest(),
                "log": str(log.resolve()),
            }
            rows.append(row)
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps({
                "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                "duration_s": args.duration, "measurements": rows,
            }, indent=2) + "\n")
            print(f"  complete={complete} steps={row['completed_steps']} "
                  f"peak MiB={peaks} plots={plots}", flush=True)
            if not complete:
                raise RuntimeError(f"stability run failed: {log}")


if __name__ == "__main__":
    main()
