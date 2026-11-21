"""Probe ten-step TGV3D cubic capacity on one, two and four V100 GPUs."""

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path


CONFIGS = {
    1: ([0], [], (256, 320, 384)),
    2: ([0, 2], ["mpirun", "--map-by", "ppr:1:numa", "--bind-to", "numa", "-np", "2"],
        (256, 320, 384, 448, 512, 576)),
    4: ([0, 1, 2, 3], ["mpirun", "--map-by", "ppr:2:numa", "--bind-to", "numa", "-np", "4"],
        (256, 320, 384, 448, 512, 576, 640, 704)),
}


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
    parser.add_argument("run_root", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve()
    case_dir = args.case_dir.resolve()
    args.run_root.mkdir(parents=True, exist_ok=True)
    rows = []
    limits = {}
    binary_sha256 = hashlib.sha256(binary.read_bytes()).hexdigest()

    def probe(ranks: int, devices: list[int], launcher: list[str], n: int) -> bool:
        run_dir = args.run_root / f"{ranks}gpu-{n}"
        run_dir.mkdir(exist_ok=True)
        inputs = run_dir / "inputs"
        subprocess.run(["python3", str(case_dir / "make_inputs.py"),
                        "capacity", str(n), str(inputs)], check=True)
        command = [*launcher, str(binary), str(inputs)]
        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = ",".join(map(str, devices))
        peaks = {device: 0 for device in devices}
        log = run_dir / "run.log"
        print(f"capacity: {ranks} GPU, {n}³", flush=True)
        start = time.monotonic()
        with log.open("w") as output:
            proc = subprocess.Popen(command, cwd=run_dir, env=env,
                                    stdout=output, stderr=subprocess.STDOUT)
            while proc.poll() is None:
                try:
                    current = gpu_memory()
                    for device in devices:
                        peaks[device] = max(peaks[device], current[device])
                except subprocess.CalledProcessError:
                    pass
                time.sleep(0.1)
            returncode = proc.wait()
        output_text = log.read_text(errors="replace")
        complete = (returncode == 0 and "Coarse STEP 10 ends" in output_text
                    and "finalized" in output_text)
        row = {"gpus": ranks, "n": n, "cells": n**3,
               "gpu_indices": devices, "peak_vram_mib": peaks,
               "completed_ten_steps": complete, "returncode": returncode,
               "wall_s": time.monotonic() - start, "command": command,
               "input_sha256": hashlib.sha256(inputs.read_bytes()).hexdigest(),
               "log": str(log.resolve())}
        rows.append(row)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({"binary_sha256": binary_sha256,
                                           "measurements": rows,
                                           "limits": limits}, indent=2) + "\n")
        print(f"  completed={complete} peak MiB={peaks}", flush=True)
        return complete

    for ranks, (devices, launcher, sizes) in CONFIGS.items():
        success = None
        failure = None
        for n in sizes:
            if probe(ranks, devices, launcher, n):
                success = n
            else:
                failure = n
                break
        if success is not None and failure is not None:
            while failure - success > 8:
                middle = ((success + failure) // 16) * 8
                if probe(ranks, devices, launcher, middle):
                    success = middle
                else:
                    failure = middle
        limits[str(ranks)] = {"max_success_n": success, "first_failed_n": failure,
                              "granularity_n": 8}
        args.report.write_text(json.dumps({"binary_sha256": binary_sha256,
                                           "measurements": rows,
                                           "limits": limits}, indent=2) + "\n")

    print(f"report={args.report}", flush=True)


if __name__ == "__main__":
    main()
