"""Plot the TGV3D mean kinetic-energy history from check_physics.py CSV."""

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    with args.csv_path.open(newline="") as source:
        rows = list(csv.DictReader(source))
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    for n in (64, 128):
        points = sorted((float(row["time"]), float(row["mean_kinetic"]))
                        for row in rows if int(row["grid"]) == n)
        ax.plot(*zip(*points), marker="o", label=f"{n}³")
    ax.set(xlabel="Physical time", ylabel="Mean kinetic energy",
           title="TGV3D energy evolution")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(args.output, dpi=180)


if __name__ == "__main__":
    main()
