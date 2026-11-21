"""Compare two single-GPU TGV3D timed runs in alternating order."""

import argparse
import hashlib
import json
import os
import re
import statistics
import subprocess
from pathlib import Path


TIMING = re.compile(
    r"LBM_BASELINE_TIMING steps=500 elapsed_max_s=([0-9.eE+-]+) "
    r"sec_per_step=([0-9.eE+-]+)")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def setting(text: str, key: str) -> str:
    matches = re.findall(rf"(?m)^{re.escape(key)}\s*=\s*(.*)$", text)
    if len(matches) != 1:
        raise ValueError(f"expected one {key} setting")
    return matches[0].strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left_binary", type=Path)
    parser.add_argument("left_input", type=Path)
    parser.add_argument("right_binary", type=Path)
    parser.add_argument("right_input", type=Path)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    args.run_root = args.run_root.resolve()
    args.report = args.report.resolve()
    args.run_root.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)

    cases = {
        "left": (args.left_binary.resolve(), args.left_input.resolve()),
        "right": (args.right_binary.resolve(), args.right_input.resolve()),
    }
    input_text = {name: path.read_text() for name, (_, path) in cases.items()}
    for name, text in input_text.items():
        if setting(text, "amr.plot_int") != "-1" or setting(text, "amr.chk_int") != "-1":
            raise ValueError(f"{name} input must disable full-field output")
        if setting(text, "max_step") != "600":
            raise ValueError(f"{name} input must run 100 warmup plus 500 timed steps")
    if setting(input_text["left"], "amr.n_cell") != setting(input_text["right"],
                                                               "amr.n_cell"):
        raise ValueError("both inputs must use the same grid")

    report = {
        "grid": setting(input_text["left"], "amr.n_cell"),
        "gpus": "0", "warmup_steps": 100, "timed_steps": 500,
        "cases": {name: {"binary": str(binary), "binary_sha256": sha256(binary),
                         "input": str(inputs), "input_sha256": sha256(inputs),
                         "max_grid_size": setting(input_text[name], "amr.max_grid_size")}
                  for name, (binary, inputs) in cases.items()},
        "runs": [],
    }

    for repeat in range(1, args.repeats + 1):
        order = ("left", "right") if repeat % 2 else ("right", "left")
        for name in order:
            binary, inputs = cases[name]
            run_dir = args.run_root / f"r{repeat}-{name}"
            run_dir.mkdir(exist_ok=True)
            log_path = run_dir / "run.log"
            command = [str(binary), str(inputs)]
            env = os.environ.copy()
            env["CUDA_VISIBLE_DEVICES"] = "0"
            print(f"repeat={repeat} case={name}", flush=True)
            with log_path.open("w") as output:
                result = subprocess.run(command, cwd=run_dir, env=env,
                                        stdout=output, stderr=subprocess.STDOUT)
            log = log_path.read_text(errors="replace")
            match = TIMING.search(log)
            if result.returncode or not match or "Coarse STEP 600 ends" not in log:
                raise RuntimeError(f"timed run failed: {log_path}")
            row = {"repeat": repeat, "case": name,
                   "sec_per_step": float(match.group(2)),
                   "elapsed_max_s": float(match.group(1)),
                   "command": command, "log": str(log_path)}
            report["runs"].append(row)
            args.report.write_text(json.dumps(report, indent=2) + "\n")
            print(f"  {row['sec_per_step'] * 1000:.3f} ms/step", flush=True)

    times = {name: [row["sec_per_step"] for row in report["runs"]
                    if row["case"] == name] for name in cases}
    report["summary"] = {
        name: {"median_sec_per_step": statistics.median(values),
               "min_sec_per_step": min(values), "max_sec_per_step": max(values)}
        for name, values in times.items()}
    report["summary"]["ratio_right_to_left"] = (
        report["summary"]["right"]["median_sec_per_step"] /
        report["summary"]["left"]["median_sec_per_step"])
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(f"report={args.report}", flush=True)


if __name__ == "__main__":
    main()
