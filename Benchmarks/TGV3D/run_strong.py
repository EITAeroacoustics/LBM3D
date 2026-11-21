"""Run and summarize the original-core 256^3 strong-scaling baseline."""

import argparse
import hashlib
import json
import os
import re
import shlex
import statistics
import subprocess
from pathlib import Path


TIMING = re.compile(r"LBM_BASELINE_TIMING steps=500 elapsed_max_s=([0-9.eE+-]+) sec_per_step=([0-9.eE+-]+)")
CONFIGS = {
    1: ("0", []),
    2: ("0,2", ["mpirun", "--map-by", "ppr:1:numa", "--bind-to", "numa", "-np", "2"]),
    4: ("0,1,2,3", ["mpirun", "--map-by", "ppr:2:numa", "--bind-to", "numa", "-np", "4"]),
}
RUN_ORDER = ((1, 2, 4), (4, 2, 1), (1, 2, 4))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("input", type=Path)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--repeats", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--mpirun", default="mpirun")
    parser.add_argument("--mpi-options", default="")
    parser.add_argument("--rank-wrapper", type=Path)
    parser.add_argument("--mass-check-interval", type=int)
    args = parser.parse_args()
    binary = args.binary.resolve()
    input_path = args.input.resolve()
    args.run_root.mkdir(parents=True, exist_ok=True)
    runs = []

    for repeat, order in enumerate(RUN_ORDER[:args.repeats], start=1):
        for ranks in order:
            visible, launcher = CONFIGS[ranks]
            run_dir = args.run_root / f"{ranks}gpu-r{repeat}"
            run_dir.mkdir(exist_ok=True)
            log = run_dir / "run.log"
            mpi_launcher = ([args.mpirun, *shlex.split(args.mpi_options),
                             *launcher[1:]] if launcher else [])
            application = [str(binary), str(input_path)]
            if args.mass_check_interval is not None:
                application.append(f"lbm3d.mass_check_interval={args.mass_check_interval}")
            if launcher and args.rank_wrapper:
                application = ["python3", str(args.rank_wrapper.resolve()),
                               *application]
            command = [*mpi_launcher, *application]
            env = os.environ.copy()
            env["CUDA_VISIBLE_DEVICES"] = visible
            if args.rank_wrapper:
                env["LBM_GPU_MAP"] = visible
            print(f"running {ranks} GPU repeat {repeat}: {' '.join(command)}", flush=True)
            with log.open("w") as output:
                result = subprocess.run(command, cwd=run_dir, env=env,
                                        stdout=output, stderr=subprocess.STDOUT)
            if result.returncode:
                raise RuntimeError(f"run failed ({result.returncode}): {log}")
            match = TIMING.search(log.read_text(errors="replace"))
            if not match:
                raise RuntimeError(f"missing synchronized 500-step timing: {log}")
            full_fields = sorted(str(path.relative_to(run_dir))
                                 for path in run_dir.iterdir()
                                 if path.name.startswith(("plt", "chk")))
            if full_fields:
                raise RuntimeError(f"unexpected full-field output in {run_dir}: {full_fields}")
            runs.append({"gpus": ranks, "repeat": repeat,
                         "visible_devices": visible, "command": command,
                         "elapsed_max_s": float(match.group(1)),
                         "sec_per_step": float(match.group(2)),
                         "log": str(log.resolve()), "log_sha256": sha256(log),
                         "full_field_outputs": full_fields})
            print(f"  {float(match.group(2)):.6g} sec/step", flush=True)

    summary = {}
    for ranks in CONFIGS:
        times = [row["sec_per_step"] for row in runs if row["gpus"] == ranks]
        summary[str(ranks)] = {"median_sec_per_step": statistics.median(times),
                               "min_sec_per_step": min(times),
                               "max_sec_per_step": max(times)}
    report = {"binary_sha256": sha256(binary), "input_sha256": sha256(input_path),
              "mass_check_interval": args.mass_check_interval,
              "warmup_steps": 100, "timed_steps": 500,
              "run_order": [list(order) for order in RUN_ORDER[:args.repeats]],
              "runs": runs,
              "summary": summary}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
