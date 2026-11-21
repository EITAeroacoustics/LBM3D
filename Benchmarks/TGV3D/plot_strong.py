"""Plot median 500-step timing from run_strong.py JSON."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    summary = json.loads(args.report.read_text())["summary"]
    counts = [1, 2, 4]
    medians = [1000 * summary[str(n)]["median_sec_per_step"] for n in counts]
    low = [1000 * (summary[str(n)]["median_sec_per_step"] -
                   summary[str(n)]["min_sec_per_step"]) for n in counts]
    high = [1000 * (summary[str(n)]["max_sec_per_step"] -
                    summary[str(n)]["median_sec_per_step"]) for n in counts]

    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    ax.bar([str(n) for n in counts], medians, color="#377eb8")
    ax.errorbar([str(n) for n in counts], medians, yerr=[low, high],
                fmt="none", color="black", capsize=4)
    ax.set(xlabel="V100 GPUs", ylabel="Wall time per step (ms)",
           title="Original solver strong scaling, 256³")
    ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(args.output, dpi=180)


if __name__ == "__main__":
    main()
