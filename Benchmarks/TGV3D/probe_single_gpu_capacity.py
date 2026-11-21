"""Measure the ten-step TGV3D capacity on one GPU without field output."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional


def gpu_memory_mib() -> int:
    output = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits", "-i", "0"],
        text=True)
    return int(output.strip())


def replace_setting(text: str, key: str, value: str) -> str:
    pattern = rf"(?m)^({re.escape(key)}\s*=\s*).*$"
    updated, count = re.subn(pattern, lambda match: match.group(1) + value, text)
    if count != 1:
        raise ValueError(f"expected one {key} setting, found {count}")
    return updated


def arena_mib(log: str, kind: str) -> Optional[int]:
    pattern = (rf"\[The\s+Arena\]\s+"
               rf"(?:max space \(MB\) {kind}\s+spread across MPI|"
               rf"space {kind}\s+\(MB\)):\s*\[?(\d+)")
    matches = re.findall(pattern, log)
    return int(matches[-1]) if matches else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--max-grid-sizes", type=int, nargs="+", default=[64, 128, 256])
    parser.add_argument("--start", type=int, default=328)
    parser.add_argument("--stop", type=int, default=400)
    parser.add_argument("--step", type=int, default=8)
    parser.add_argument("--steps", type=int, default=10)
    parser.add_argument("--blocking-factor", type=int, default=8)
    args = parser.parse_args()

    binary = args.binary.resolve()
    case_dir = args.case_dir.resolve()
    args.run_root = args.run_root.resolve()
    args.report = args.report.resolve()
    args.run_root.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    report = {
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "gpu": subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader", "-i", "0"],
            text=True).strip(),
        "capacity_rule": f"{args.steps} steps, normal exit, no plotfile or checkpoint",
        "blocking_factor": args.blocking_factor,
        "measurements": rows,
    }

    for max_grid_size in args.max_grid_sizes:
        for n in range(args.start, args.stop + 1, args.step):
            run_dir = args.run_root / f"grid{max_grid_size}-n{n}"
            run_dir.mkdir(exist_ok=True)
            inputs = run_dir / "inputs"
            generator_n = ((n + 7) // 8) * 8
            subprocess.run(["python3", str(case_dir / "make_inputs.py"),
                            "capacity", str(generator_n), str(inputs)], check=True)
            input_text = replace_setting(inputs.read_text(), "amr.max_grid_size",
                                         str(max_grid_size))
            input_text = replace_setting(input_text, "amr.n_cell", f"{n} {n} {n}")
            input_text = replace_setting(input_text, "max_step", str(args.steps))
            for axis in "xyz":
                input_text = replace_setting(input_text, f"amr.blocking_factor_{axis}",
                                             str(args.blocking_factor))
            inputs.write_text(input_text)
            if not re.search(r"(?m)^amr.plot_int\s*=\s*-1$", input_text):
                raise ValueError("capacity input must disable plotfiles")
            if not re.search(r"(?m)^amr.chk_int\s*=\s*-1$", input_text):
                raise ValueError("capacity input must disable checkpoints")

            log_path = run_dir / "run.log"
            command = [str(binary), str(inputs)]
            env = os.environ.copy()
            env["CUDA_VISIBLE_DEVICES"] = "0"
            peak_mib = gpu_memory_mib()
            print(f"max_grid_size={max_grid_size} n={n}", flush=True)
            start = time.monotonic()
            with log_path.open("w") as log_file:
                proc = subprocess.Popen(command, cwd=run_dir, env=env,
                                        stdout=log_file, stderr=subprocess.STDOUT)
                while proc.poll() is None:
                    peak_mib = max(peak_mib, gpu_memory_mib())
                    time.sleep(0.05)
                returncode = proc.wait()
            output = log_path.read_text(errors="replace")
            complete = (returncode == 0 and f"Coarse STEP {args.steps} ends" in output
                        and "finalized" in output)
            row = {
                "n": n, "cells": n**3, "max_grid_size": max_grid_size,
                "completed_steps": complete, "target_steps": args.steps,
                "returncode": returncode,
                "peak_vram_mib": peak_mib,
                "arena_max_allocated_mb": arena_mib(output, "allocated"),
                "arena_max_used_mb": arena_mib(output, "used"),
                "out_of_memory": "OutOfMemoryError" in output,
                "wall_s": time.monotonic() - start,
                "input_sha256": hashlib.sha256(inputs.read_bytes()).hexdigest(),
                "command": command, "log": str(log_path.resolve()),
            }
            rows.append(row)
            args.report.write_text(json.dumps(report, indent=2) + "\n")
            print(f"  complete={complete} peak={peak_mib} MiB", flush=True)
            if not complete:
                break

    print(f"report={args.report}", flush=True)


if __name__ == "__main__":
    main()
