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
    parser.add_argument("--target", type=float, default=0.90)
    args = parser.parse_args()

    strong = json.loads(args.strong_report.read_text())
    weak = json.loads(args.weak_report.read_text())
    if strong["binary_sha256"] != weak["binary_sha256"]:
        raise SystemExit("strong and weak reports must use the same binary")
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
