"""Re-run the P1 TGV3D physics, scaling, capacity, bitwise and stability suite."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
COMPARE = re.compile(r"BIT_COMPARE var=(\w+) mismatches=(\d+)")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def command_output(command: list[str]) -> str:
    result = subprocess.run(command, text=True, capture_output=True)
    return result.stdout.strip() if result.returncode == 0 else result.stderr.strip()


def build_options(binary: Path) -> dict[str, str]:
    cache = binary.parent / "CMakeCache.txt"
    if not cache.exists():
        return {}
    names = ("AMReX_DIR", "CMAKE_BUILD_TYPE", "CMAKE_CUDA_COMPILER", "LBM_DIM",
             "LBM_BASELINE_IBM", "LBM_ENABLE_IBM", "LBM_TIMING")
    return {name: line.split("=", 1)[1] for line in cache.read_text().splitlines()
            for name in names if line.startswith(name + ":")}


def run(command: list[str], cwd: Path | None = None, log: Path | None = None) -> None:
    print(" ".join(command), flush=True)
    if log:
        with log.open("w") as output:
            subprocess.run(command, cwd=cwd, stdout=output,
                           stderr=subprocess.STDOUT, check=True)
    else:
        subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline", "baseline_timed", "modular", "modular_timed",
                 "analyzer", "comparator"):
        parser.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--stability-seconds", type=float, default=600.0)
    parser.add_argument("--source-version", help="commit from bundle manifest when no Git metadata is present")
    args = parser.parse_args()
    paths = {name: getattr(args, name).resolve() for name in
             ("baseline", "baseline_timed", "modular", "modular_timed",
              "analyzer", "comparator")}
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = "0"
    inputs = {64: HERE / "inputs_physics_64", 128: HERE / "inputs_physics_128"}
    checkpoints = {64: (0, 32, 64), 128: (0, 64, 128)}

    for solver in ("baseline", "modular"):
        for n in (64, 128):
            directory = work / f"{solver}-physics-{n}"
            directory.mkdir(exist_ok=True)
            log = directory / "run.log"
            print(f"physics: {solver} {n}³", flush=True)
            with log.open("w") as output:
                subprocess.run([str(paths[solver]), str(inputs[n])], cwd=directory,
                               env=env, stdout=output, stderr=subprocess.STDOUT, check=True)
        run(["python3", str(HERE / "check_physics.py"), str(paths["analyzer"]),
             str(work / f"{solver}-physics-64"), str(work / f"{solver}-physics-128"),
             str(work / f"{solver}-physics.json")])
        run(["python3", str(HERE / "plot_svg.py"), "physics",
             str(work / f"{solver}-physics.json"), str(work / f"{solver}-physics.svg")])

    field_checks = []
    for n in (64, 128):
        for step in checkpoints[n]:
            reference = work / f"baseline-physics-{n}" / f"plt{step:05d}"
            other = work / f"modular-physics-{n}" / f"plt{step:05d}"
            result = subprocess.run([str(paths["comparator"]), str(reference), str(other)],
                                    env=env, text=True, capture_output=True)
            fields = {name: int(count) for name, count in COMPARE.findall(result.stdout)}
            if result.returncode or len(fields) != 4 or any(fields.values()):
                raise RuntimeError(f"physics field mismatch: {n}³ step {step}\n{result.stdout}")
            field_checks.append({"grid": n, "step": step, "mismatches": fields})

    for solver in ("baseline", "modular"):
        run(["python3", str(HERE / "run_strong.py"), str(paths[f"{solver}_timed"]),
             str(HERE / "inputs_strong_256"), str(work / f"{solver}-strong"),
             str(work / f"{solver}-strong.json")])
        run(["python3", str(HERE / "plot_svg.py"), "strong",
             str(work / f"{solver}-strong.json"), str(work / f"{solver}-strong.svg")])
        run(["python3", str(HERE / "run_capacity.py"), str(paths[f"{solver}_timed"]),
             str(HERE), str(work / f"{solver}-capacity"),
             str(work / f"{solver}-capacity.json")])
        run(["python3", str(HERE / "run_init_io.py"), str(paths[f"{solver}_timed"]),
             str(HERE / "inputs_strong_256"), str(work / f"{solver}-init-io"),
             str(work / f"{solver}-init-io.json")])

    run(["python3", str(HERE / "run_bitwise.py"), str(paths["modular"]),
         str(paths["comparator"]), str(HERE / "inputs_bitwise_128"),
         str(work / "modular-bitwise"), str(work / "modular-bitwise.json")])
    run(["python3", str(HERE / "run_stability.py"), str(paths["modular"]),
         str(HERE), str(work / "modular-capacity.json"),
         str(work / "modular-stability"), str(work / "modular-stability.json"),
         "--duration", str(args.stability_seconds)])

    source_version = args.source_version or command_output(
        ["git", "-C", str(HERE.parents[1]), "rev-parse", "HEAD"])
    physics_reports = {solver: json.loads((work / f"{solver}-physics.json").read_text())
                       for solver in ("baseline", "modular")}
    strong_reports = {solver: json.loads((work / f"{solver}-strong.json").read_text())
                      for solver in ("baseline", "modular")}
    capacity_reports = {solver: json.loads((work / f"{solver}-capacity.json").read_text())
                        for solver in ("baseline", "modular")}
    bitwise_report = json.loads((work / "modular-bitwise.json").read_text())
    stability_report = json.loads((work / "modular-stability.json").read_text())
    strong_change = {str(n): {
        "baseline_sec_per_step": strong_reports["baseline"]["summary"][str(n)]["median_sec_per_step"],
        "modular_sec_per_step": strong_reports["modular"]["summary"][str(n)]["median_sec_per_step"],
        "ratio_modular_to_baseline": (
            strong_reports["modular"]["summary"][str(n)]["median_sec_per_step"] /
            strong_reports["baseline"]["summary"][str(n)]["median_sec_per_step"]),
    } for n in (1, 2, 4)}
    capacity_change = {str(n): {
        solver: capacity_reports[solver]["limits"][str(n)]["max_success_n"]
        for solver in ("baseline", "modular")
    } for n in (1, 2, 4)}
    passed = (all(item["passed"] for item in physics_reports.values()) and
              all(item["bitwise_equal"] for item in bitwise_report["comparisons"]) and
              len(stability_report["measurements"]) == 6 and
              all(item["complete"] for item in stability_report["measurements"]))
    report = {
        "source_version": source_version,
        "toolchain": {
            "gpus": command_output(["nvidia-smi", "--query-gpu=index,name,memory.total,driver_version",
                                    "--format=csv,noheader"]),
            "cuda": command_output(["/usr/local/cuda/bin/nvcc", "--version"]),
            "mpi": command_output(["mpirun", "--version"]),
        },
        "binaries": {name: {"path": str(path), "sha256": sha256(path),
                            "build_options": build_options(path)}
                     for name, path in paths.items()},
        "physics_fields": field_checks,
        "strong_change": strong_change,
        "capacity_max_success_n": capacity_change,
        "passed": passed,
        "reports": {name: str(work / name) for name in (
            "baseline-physics.json", "modular-physics.json",
            "baseline-strong.json", "modular-strong.json",
            "baseline-capacity.json", "modular-capacity.json",
            "baseline-init-io.json", "modular-init-io.json",
            "modular-bitwise.json", "modular-stability.json")},
    }
    (work / "index.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = ["# P1 TGV3D 复跑报告", "",
             f"- 项目提交：`{source_version}`",
             f"- 物理检查：原始版 `{physics_reports['baseline']['passed']}`，模块化版 `{physics_reports['modular']['passed']}`",
             f"- 两档网格三个检查点场值逐位对照：`{len(field_checks) * 4}` 项，均无差异",
             f"- 模块化版跨 1/2/4 GPU 逐位一致：`{all(item['bitwise_equal'] for item in bitwise_report['comparisons'])}`",
             f"- 六组 {args.stability_seconds:g} 秒稳定性：`{all(item['complete'] for item in stability_report['measurements'])}`",
             "", "## 同网格强扩展", "",
             "| GPU | 原始版 ms/步 | 模块化版 ms/步 | 模块化/原始 |",
             "|---:|---:|---:|---:|"]
    for count in (1, 2, 4):
        row = strong_change[str(count)]
        lines.append(f"| {count} | {row['baseline_sec_per_step'] * 1000:.3f} | "
                     f"{row['modular_sec_per_step'] * 1000:.3f} | "
                     f"{row['ratio_modular_to_baseline']:.3f} |")
    lines.extend(["", "## 10 步容量", "",
                  "| GPU | 原始版边长 | 模块化版边长 |",
                  "|---:|---:|---:|"])
    for count in (1, 2, 4):
        row = capacity_change[str(count)]
        lines.append(f"| {count} | {row['baseline']} | {row['modular']} |")
    lines.extend(["", "详细输入、二进制校验值、编译选项、工具链、日志和报告路径见 `index.json`。",
                  "图表为同目录的 `*-physics.svg` 与 `*-strong.svg`。", ""])
    (work / "summary.md").write_text("\n".join(lines))
    print(f"P1 TGV3D suite passed={passed}; index={work / 'index.json'}", flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
