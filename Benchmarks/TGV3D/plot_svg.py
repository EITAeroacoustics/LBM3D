"""Write dependency-free SVG plots for P1 physics and strong-scaling reports."""

import argparse
import json
from pathlib import Path


def canvas(title: str, xlabel: str, ylabel: str, top: float) -> list[str]:
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="720" height="470" viewBox="0 0 720 470">',
        '<rect width="720" height="470" fill="white"/>',
        f'<text x="360" y="35" text-anchor="middle" font-size="21" font-family="sans-serif">{title}</text>',
        '<line x1="90" y1="385" x2="650" y2="385" stroke="#333"/>',
        '<line x1="90" y1="385" x2="90" y2="75" stroke="#333"/>',
        f'<text x="370" y="448" text-anchor="middle" font-size="15" font-family="sans-serif">{xlabel}</text>',
        f'<text x="22" y="230" transform="rotate(-90 22 230)" text-anchor="middle" font-size="15" font-family="sans-serif">{ylabel}</text>',
    ]
    for index in range(6):
        y = 385 - index * 62
        value = top * index / 5
        parts.extend([
            f'<line x1="85" y1="{y}" x2="650" y2="{y}" stroke="#dddddd"/>',
            f'<text x="78" y="{y+5}" text-anchor="end" font-size="12" font-family="sans-serif">{value:.3g}</text>',
        ])
    return parts


def physics(report: dict) -> str:
    rows = report["measurements"]
    max_energy = max(row["mean_kinetic"] for row in rows) * 1.08
    parts = canvas("TGV3D energy evolution", "Physical time", "Mean kinetic energy", max_energy)
    for time in (0, 32, 64):
        x = 90 + time * 560 / 64
        parts.append(f'<text x="{x:.1f}" y="407" text-anchor="middle" font-size="12" font-family="sans-serif">{time}</text>')
    for grid, color in ((64, "#2171b5"), (128, "#d95f0e")):
        samples = sorted((row for row in rows if row["grid"] == grid), key=lambda row: row["time"])
        points = [(90 + row["time"] * 560 / 64,
                   385 - row["mean_kinetic"] * 310 / max_energy) for row in samples]
        data = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        parts.append(f'<polyline points="{data}" fill="none" stroke="{color}" stroke-width="2.5"/>')
        for x, y in points:
            parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4" fill="{color}"/>')
        parts.append(f'<text x="{500 if grid == 64 else 575}" y="{65}" fill="{color}" font-size="14" font-family="sans-serif">{grid}³</text>')
    return "\n".join([*parts, "</svg>", ""])


def strong(report: dict) -> str:
    summary = report["summary"]
    top = max(row["max_sec_per_step"] * 1000 for row in summary.values()) * 1.15
    parts = canvas("TGV3D strong scaling, 256³", "V100 GPUs", "Wall time per step (ms)", top)
    for index, count in enumerate((1, 2, 4)):
        row = summary[str(count)]
        x = 175 + 185 * index
        median = row["median_sec_per_step"] * 1000
        minimum = row["min_sec_per_step"] * 1000
        maximum = row["max_sec_per_step"] * 1000
        y = 385 - median * 310 / top
        ylo = 385 - minimum * 310 / top
        yhi = 385 - maximum * 310 / top
        parts.extend([
            f'<rect x="{x-31}" y="{y:.2f}" width="62" height="{385-y:.2f}" fill="#377eb8"/>',
            f'<line x1="{x}" y1="{yhi:.2f}" x2="{x}" y2="{ylo:.2f}" stroke="#222"/>',
            f'<line x1="{x-8}" y1="{yhi:.2f}" x2="{x+8}" y2="{yhi:.2f}" stroke="#222"/>',
            f'<line x1="{x-8}" y1="{ylo:.2f}" x2="{x+8}" y2="{ylo:.2f}" stroke="#222"/>',
            f'<text x="{x}" y="407" text-anchor="middle" font-size="12" font-family="sans-serif">{count}</text>',
        ])
    return "\n".join([*parts, "</svg>", ""])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("physics", "strong"))
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    args.output.write_text(physics(report) if args.kind == "physics" else strong(report))


if __name__ == "__main__":
    main()
