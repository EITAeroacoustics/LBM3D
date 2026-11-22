"""Check 1/2/4-GPU strong and weak scaling against an efficiency target."""

import argparse
import json
from pathlib import Path


def median_time(report: dict, ranks: int) -> float:
    return report["summary"][str(ranks)]["median_sec_per_step"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("strong_report", type=Path)
    parser.add_argument("weak_report", type=Path)
    parser.add_argument("--target", type=float, default=0.85)
    parser.add_argument("--min-repeats", type=int, choices=(1, 2, 3), default=3)
    args = parser.parse_args()

    strong = json.loads(args.strong_report.read_text())
    weak = json.loads(args.weak_report.read_text())
    if strong["binary_sha256"] != weak["binary_sha256"]:
        raise SystemExit("strong and weak reports must use the same binary")
    if strong.get("mass_check_interval") != weak.get("mass_check_interval"):
        raise SystemExit("strong and weak reports must use the same mass check interval")
    if strong.get("input_options", []) != weak.get("input_options", []):
        raise SystemExit("strong and weak reports must use the same input options")
    for name, report in (("strong", strong), ("weak", weak)):
        if report["warmup_steps"] != 100 or report["timed_steps"] != 500:
            raise SystemExit(f"{name} report must time 500 steps after 100 warmup steps")
        for ranks in (1, 2, 4):
            runs = [run for run in report["runs"] if run["gpus"] == ranks]
            if len({run["repeat"] for run in runs}) < args.min_repeats:
                raise SystemExit(f"{name} {ranks}-GPU report has fewer than {args.min_repeats} repeats")
            if any(run["full_field_outputs"] for run in runs):
                raise SystemExit(f"{name} {ranks}-GPU report wrote full-field output")
    result = {"target": args.target, "strong": {}, "weak": {}}
    for ranks in (2, 4):
        strong_eff = median_time(strong, 1) / (ranks * median_time(strong, ranks))
        weak_eff = median_time(weak, 1) / median_time(weak, ranks)
        result["strong"][str(ranks)] = strong_eff
        result["weak"][str(ranks)] = weak_eff
    result["passed"] = all(value > args.target
                           for name in ("strong", "weak")
                           for value in result[name].values())
    print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
