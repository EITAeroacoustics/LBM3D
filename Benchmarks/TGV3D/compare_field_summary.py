"""Compare compact final-field statistics without writing full fields."""

import argparse
import hashlib
import json
import math
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Optional


CONFIGS = {
    1: ("0", []),
    2: ("0,2", ["mpirun", "--map-by", "ppr:1:numa", "--bind-to", "numa", "-np", "2"]),
    4: ("0,1,2,3", ["mpirun", "--map-by", "ppr:2:numa", "--bind-to", "numa", "-np", "4"]),
}
SUMMARY = re.compile(r"^FIELD_SUMMARY lev=(\d+) comp=(\d+) "
                     r"sum=(\S+) norm2=(\S+) min=(\S+) max=(\S+) "
                     r"hash0=(\d+) hash1=(\d+)$", re.M)
HALO_SEND = re.compile(r"LBM_DIRECTIONAL_HALO active=1 .*?"
                       r"rank0_send_values=(\d+)/(\d+)")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def max_numeric_difference(baseline: dict, optimized: dict) -> float:
    if baseline.keys() != optimized.keys():
        return math.inf
    differences = [abs(float(baseline[key][i]) - float(optimized[key][i]))
                   for key in baseline for i in range(4)]
    return max(differences) if all(math.isfinite(value) for value in differences) else math.inf


def run(binary: Path, inputs: Path, root: Path, ranks: int,
        mpirun: str, mpi_options: str, rank_wrapper: Optional[Path],
        input_options: list[str], expected_fields: int) -> dict:
    visible, launcher = CONFIGS[ranks]
    root.mkdir(parents=True, exist_ok=True)
    log = root / "run.log"
    mpi_launcher = ([mpirun, *shlex.split(mpi_options), *launcher[1:]]
                    if launcher else [])
    application = [str(binary), str(inputs), "max_step=10",
                   "amr.plot_int=-1", "amr.chk_int=-1", *input_options]
    if launcher and rank_wrapper:
        application = ["python3", str(rank_wrapper), *application]
    command = [*mpi_launcher, *application]
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = visible
    if rank_wrapper:
        env["LBM_GPU_MAP"] = visible
    with log.open("w") as output:
        result = subprocess.run(command, cwd=root, env=env, stdout=output,
                                stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"run failed ({result.returncode}): {log}")
    full_fields = sorted(str(path.relative_to(root)) for path in root.iterdir()
                         if path.name.startswith(("plt", "chk")))
    if full_fields:
        raise RuntimeError(f"unexpected full-field output in {root}: {full_fields}")
    log_text = log.read_text(errors="replace")
    summaries = {f"{lev}:{comp}": [total, norm, minimum, maximum,
                                   hash0, hash1]
                 for lev, comp, total, norm, minimum, maximum, hash0, hash1
                 in SUMMARY.findall(log_text)}
    if len(summaries) != expected_fields:
        raise RuntimeError(f"expected {expected_fields} final-field summaries, "
                           f"got {len(summaries)}: {log}")
    halo_send = HALO_SEND.search(log_text)
    return {"command": command, "visible_devices": visible,
            "full_field_outputs": full_fields,
            "log": str(log.resolve()), "log_sha256": sha256(log),
            "directional_halo_active": halo_send is not None,
            "rank0_halo_send_values": int(halo_send.group(1)) if halo_send else None,
            "fields": summaries}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline_binary", type=Path)
    parser.add_argument("optimized_binary", type=Path)
    parser.add_argument("input", type=Path)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--mpirun", default="mpirun")
    parser.add_argument("--mpi-options", default="")
    parser.add_argument("--rank-wrapper", type=Path)
    parser.add_argument("--common-option", action="append", default=[])
    parser.add_argument("--baseline-option", action="append", default=[])
    parser.add_argument("--optimized-option", action="append", default=[])
    parser.add_argument("--expected-fields", type=int, default=23)
    parser.add_argument("--numeric-atol", type=float,
                        help="compare only sum/norm2/min/max within this absolute tolerance; "
                             "position fingerprints remain recorded")
    parser.add_argument("--require-directional-halo", action="store_true")
    args = parser.parse_args()
    if args.expected_fields < 1:
        parser.error("--expected-fields must be positive")
    if args.numeric_atol is not None and (not math.isfinite(args.numeric_atol) or
                                          args.numeric_atol <= 0):
        parser.error("--numeric-atol must be finite and positive")
    binaries = {"baseline": args.baseline_binary.resolve(),
                "optimized": args.optimized_binary.resolve()}
    inputs = args.input.resolve()
    runs = {}
    for ranks in CONFIGS:
        pair = {}
        for name, binary in binaries.items():
            print(f"running {name} on {ranks} GPU(s)", flush=True)
            pair[name] = run(binary, inputs, args.run_root / f"{ranks}gpu" / name,
                             ranks, args.mpirun, args.mpi_options,
                             args.rank_wrapper.resolve() if args.rank_wrapper else None,
                             [*args.common_option,
                              *(args.optimized_option if name == "optimized"
                                else args.baseline_option)], args.expected_fields)
        if args.require_directional_halo:
            if pair["baseline"]["directional_halo_active"]:
                raise RuntimeError(f"baseline unexpectedly used directional halo on {ranks} GPU(s)")
            if not pair["optimized"]["directional_halo_active"]:
                raise RuntimeError(f"directional halo was inactive on {ranks} GPU(s)")
            if ranks > 1 and not pair["optimized"]["rank0_halo_send_values"]:
                raise RuntimeError(f"directional halo sent no remote values on {ranks} GPU(s)")
        pair["summary_equal"] = pair["baseline"]["fields"] == pair["optimized"]["fields"]
        pair["max_numeric_abs_diff"] = max_numeric_difference(
            pair["baseline"]["fields"], pair["optimized"]["fields"])
        pair["passed"] = (pair["summary_equal"] if args.numeric_atol is None else
                          pair["max_numeric_abs_diff"] <= args.numeric_atol)
        runs[str(ranks)] = pair
        print(f"  summary_equal={pair['summary_equal']} passed={pair['passed']}", flush=True)
    report = {"input_sha256": sha256(inputs),
              "binary_sha256": {name: sha256(path) for name, path in binaries.items()},
              "common_options": args.common_option,
              "baseline_options": args.baseline_option,
              "optimized_options": args.optimized_option,
              "expected_fields": args.expected_fields,
              "numeric_atol": args.numeric_atol,
              "runs": runs}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    if not all(pair["passed"] for pair in runs.values()):
        raise SystemExit("final-field summary comparison failed; see report")


if __name__ == "__main__":
    main()
