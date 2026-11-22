"""Measure exposed receive wait in a four-rank Nsight Systems halo trace.

Usage on the GPU workstation:
  python3 halo_recv_critical_path.py rank-{0,1,2,3}.sqlite \
      --output halo-recv-critical-path-20261122.json

The interval endpoints in one Nsight SQLite file use the same nanosecond
timestamp basis for MPI CPU events, CUDA runtime calls and GPU kernels.
"""

import argparse
import bisect
import json
import sqlite3
import statistics
from pathlib import Path


HALO_KERNELS = """SELECT k.start, k.end FROM CUPTI_ACTIVITY_KIND_KERNEL k
JOIN StringIds s ON s.id = k.demangledName
WHERE s.value LIKE '%LaunchDirectionalHalo%' ORDER BY k.start"""
MPI_WAITS = """SELECT m.start, m.end, m.requestHandle FROM MPI_START_WAIT_EVENTS m
JOIN StringIds s ON s.id = m.textId
WHERE s.value = 'MPI_Wait' ORDER BY m.start"""
MPI_P2P = """SELECT m.start, s.value, m.requestHandle FROM MPI_P2P_EVENTS m
JOIN StringIds s ON s.id = m.textId ORDER BY m.start"""


def summarize(values):
    ordered = sorted(values)
    return {
        "mean_ms": statistics.mean(values),
        "median_ms": statistics.median(values),
        "p95_ms": ordered[round(0.95 * (len(ordered) - 1))],
        "max_ms": ordered[-1],
    }


def analyze(path, warmup):
    db = sqlite3.connect(path)
    kernels = list(db.execute(HALO_KERNELS))
    waits = list(db.execute(MPI_WAITS))
    p2p = list(db.execute(MPI_P2P))
    steps = len(kernels) // 3
    assert len(kernels) == 3 * steps and len(waits) == 6 * steps
    assert 0 <= warmup < steps

    # MPI request handles are reused. Classify each Wait against the most
    # recent Irecv/Isend for that handle, then check the code's six-Wait order.
    events = [(start, 0, kind, handle) for start, kind, handle in p2p]
    events += [(start, 1, None, handle) for start, _, handle in waits]
    current = {}
    kinds = []
    for _, order, kind, handle in sorted(events):
        if order == 0:
            current[handle] = kind
        else:
            kinds.append(current.pop(handle))
    assert kinds == [kind for _ in range(steps)
                     for kind in ("MPI_Irecv",) * 3 + ("MPI_Isend",) * 3]

    # A correlated CUDA runtime launch and GPU kernel in the same report are
    # close in time, which also checks the CPU/GPU timestamp alignment.
    launch_offsets = [row[0] - row[1] for row in db.execute("""
        SELECT k.start, r.end FROM CUPTI_ACTIVITY_KIND_KERNEL k
        JOIN StringIds s ON s.id = k.demangledName
        JOIN CUPTI_ACTIVITY_KIND_RUNTIME r
          ON r.correlationId = k.correlationId
        WHERE s.value LIKE '%LaunchDirectionalHalo%'""")]
    assert len(launch_offsets) == len(kernels)

    metrics = {key: [] for key in (
        "recv_wait", "local_gpu_copy", "overlap_with_local_copy",
        "exposed_recv_after_local_copy", "send_wait")}
    bad_order = 0
    for step in range(warmup, steps):
        send_kernel = kernels[3 * step]
        local_start, local_end = kernels[3 * step + 1]
        recv_kernel = kernels[3 * step + 2]
        group = waits[6 * step:6 * step + 6]
        recv_start, recv_end = group[0][0], group[2][1]
        if not (send_kernel[0] <= local_start < recv_kernel[0]
                and recv_start <= recv_end <= recv_kernel[0]):
            bad_order += 1
        metrics["recv_wait"].append(
            sum(end - start for start, end, _ in group[:3]) / 1e6)
        metrics["local_gpu_copy"].append((local_end - local_start) / 1e6)
        metrics["overlap_with_local_copy"].append(
            max(0, min(recv_end, local_end) - max(recv_start, local_start)) / 1e6)
        metrics["exposed_recv_after_local_copy"].append(
            max(0, recv_end - local_end) / 1e6)
        metrics["send_wait"].append(
            sum(end - start for start, end, _ in group[3:]) / 1e6)
    assert bad_order == 0

    # No other GPU compute kernel should run inside the measured exposed
    # interval. Device DMA may still operate during this interval.
    all_kernels = list(db.execute(
        "SELECT start, end FROM CUPTI_ACTIVITY_KIND_KERNEL ORDER BY start"))
    kernel_starts = [start for start, _ in all_kernels]
    other_kernel_steps = 0
    for step in range(warmup, steps):
        start = kernels[3 * step + 1][1]
        end = waits[6 * step + 2][1]
        if start >= end:
            continue
        upto = bisect.bisect_left(kernel_starts, end)
        other_kernel_steps += any(kstart < end and kend > start
                                  for kstart, kend in all_kernels[:upto])
    db.close()
    return {
        "file": str(path),
        "steps": steps,
        "timed_steps": steps - warmup,
        "event_order_errors": bad_order,
        "other_gpu_compute_kernel_steps_in_exposed_window": other_kernel_steps,
        "cpu_gpu_launch_offset_us": {
            "min": min(launch_offsets) / 1000,
            "max": max(launch_offsets) / 1000,
        },
        "metrics": {key: summarize(values) for key, values in metrics.items()},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sqlite", nargs="+", type=Path)
    parser.add_argument("--warmup", type=int, default=100)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = {
        "definition": "max(0, last receive MPI_Wait.end - local halo GPU kernel.end)",
        "time_unit": "milliseconds; source timestamps are nanoseconds",
        "warmup_steps": args.warmup,
        "ranks": [analyze(path, args.warmup) for path in args.sqlite],
    }
    encoded = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded)
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
