"""Run the 3D Sphere and SquareDuct examples without full-field output."""

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
CASES = (
    ("Sphere_flow", "lbm3d_sphere"),
    ("SquareDuct_flow", "lbm3d_square_duct"),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()

    build = args.build.resolve()
    work = args.work.resolve()
    env = os.environ.copy()
    env.setdefault("CUDA_VISIBLE_DEVICES", "0")
    rows = []
    for name, target in CASES:
        binary = build / target
        inputs = HERE / name / "inputs"
        run_dir = work / name
        run_dir.mkdir(parents=True, exist_ok=True)
        command = [str(binary), str(inputs), "max_step=2",
                   "amr.plot_int=-1", "amr.chk_int=-1"]
        log = run_dir / "run.log"
        with log.open("w") as output:
            result = subprocess.run(command, cwd=run_dir, env=env,
                                    stdout=output, stderr=subprocess.STDOUT)
        text = log.read_text(errors="replace")
        if result.returncode or "Coarse STEP 2 ends" not in text or "finalized" not in text:
            raise RuntimeError(f"{name} short run failed: {log}")
        if any(path.name.startswith(("plt", "chk")) for path in run_dir.rglob("*")):
            raise RuntimeError(f"{name} wrote full-field output: {run_dir}")
        rows.append({"case": name, "command": command,
                     "binary_sha256": sha256(binary), "input_sha256": sha256(inputs),
                     "log": str(log), "passed": True})
        print(f"{name}: passed", flush=True)

    work.mkdir(parents=True, exist_ok=True)
    (work / "examples-report.json").write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
