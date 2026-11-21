"""Measure initialization and t=0 plotfile cost outside the strong-scaling timer."""

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import time
from pathlib import Path


CONFIGS = {
    1: ("0", []),
    2: ("0,2", ["mpirun", "--map-by", "ppr:1:numa", "--bind-to", "numa", "-np", "2"]),
    4: ("0,1,2,3", ["mpirun", "--map-by", "ppr:2:numa", "--bind-to", "numa", "-np", "4"]),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("input", type=Path)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve()
    input_path = args.input.resolve()
    args.run_root.mkdir(parents=True, exist_ok=True)
    rows = []

    for ranks, (visible, launcher) in CONFIGS.items():
        for repeat in (1, 2, 3):
            for output in (False, True):
                run_dir = args.run_root / f"{ranks}gpu-r{repeat}-{'plot' if output else 'init'}"
                run_dir.mkdir(exist_ok=True)
                command = [*launcher, str(binary), str(input_path),
                           "max_step=0", f"amr.plot_int={1 if output else -1}"]
                env = os.environ.copy()
                env["CUDA_VISIBLE_DEVICES"] = visible
                log = run_dir / "run.log"
                print(f"{ranks} GPU repeat {repeat} plot={output}", flush=True)
                start = time.perf_counter()
                with log.open("w") as destination:
                    result = subprocess.run(command, cwd=run_dir, env=env,
                                            stdout=destination, stderr=subprocess.STDOUT)
                elapsed = time.perf_counter() - start
                if result.returncode:
                    raise RuntimeError(f"run failed: {log}")
                plot = run_dir / "plt00000"
                if output != plot.exists():
                    raise RuntimeError(f"unexpected plotfile state: {run_dir}")
                rows.append({"gpus": ranks, "repeat": repeat, "plot": output,
                             "wall_s": elapsed, "command": command,
                             "log": str(log.resolve())})
                print(f"  wall={elapsed:.4f} s", flush=True)

    summary = {}
    for ranks in CONFIGS:
        init = statistics.median(x["wall_s"] for x in rows
                                 if x["gpus"] == ranks and not x["plot"])
        combined = statistics.median(x["wall_s"] for x in rows
                                     if x["gpus"] == ranks and x["plot"])
        summary[str(ranks)] = {"init_median_s": init,
                               "init_plus_plot_median_s": combined,
                               "estimated_plot_s": combined - init}
    report = {"binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
              "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
              "method": "process wall-time median difference; includes startup/finalize in both runs",
              "measurements": rows, "summary": summary}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
