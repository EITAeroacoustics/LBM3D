"""Compare compact final-field statistics without writing full fields."""

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
SUMMARY = re.compile(r"^FIELD_SUMMARY lev=(\d+) comp=(\d+) "
                     r"sum=(\S+) norm2=(\S+) min=(\S+) max=(\S+)$", re.M)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(binary: Path, inputs: Path, root: Path, ranks: int) -> dict:
    visible, launcher = CONFIGS[ranks]
    root.mkdir(parents=True, exist_ok=True)
    log = root / "run.log"
    command = [*launcher, str(binary), str(inputs), "max_step=10",
               "amr.plot_int=-1", "amr.chk_int=-1"]
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = visible
    with log.open("w") as output:
        result = subprocess.run(command, cwd=root, env=env, stdout=output,
                                stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"run failed ({result.returncode}): {log}")
    summaries = {f"{lev}:{comp}": [total, norm, minimum, maximum]
                 for lev, comp, total, norm, minimum, maximum
                 in SUMMARY.findall(log.read_text(errors="replace"))}
    if len(summaries) != 23:
        raise RuntimeError(f"expected 23 final-field summaries, got {len(summaries)}: {log}")
    return {"command": command, "visible_devices": visible,
            "log": str(log.resolve()), "log_sha256": sha256(log),
            "fields": summaries}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline_binary", type=Path)
    parser.add_argument("optimized_binary", type=Path)
    parser.add_argument("input", type=Path)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    binaries = {"baseline": args.baseline_binary.resolve(),
                "optimized": args.optimized_binary.resolve()}
    inputs = args.input.resolve()
    runs = {}
    for ranks in CONFIGS:
        pair = {}
        for name, binary in binaries.items():
            print(f"running {name} on {ranks} GPU(s)", flush=True)
            pair[name] = run(binary, inputs, args.run_root / f"{ranks}gpu" / name,
                             ranks)
        pair["summary_equal"] = pair["baseline"]["fields"] == pair["optimized"]["fields"]
        runs[str(ranks)] = pair
        print(f"  summary_equal={pair['summary_equal']}", flush=True)
    report = {"input_sha256": sha256(inputs),
              "binary_sha256": {name: sha256(path) for name, path in binaries.items()},
              "runs": runs}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    if not all(pair["summary_equal"] for pair in runs.values()):
        raise SystemExit("final-field summary differs; see report")


if __name__ == "__main__":
    main()
