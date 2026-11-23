# TGV3D test run (full)

Agent 1.0; status **passed**; commit `f462f14e4a45ce8275e82d9e15705ac5526506a3`.

| Check | Status | Evidence / reason |
| --- | --- | --- |
| build_summary | passed | CMake build completed |
| quick_precision | passed |  |
| compact_even | passed |  |
| compact_odd | passed |  |
| build_timing | passed | CMake build completed |
| full_precision | passed | /home/hanbo/workspace/LBM/deps/lbm3d-p2-final-20261123/runs/full-001/full_precision/report.json |
| capacity | passed | /home/hanbo/workspace/LBM/deps/lbm3d-p2-final-20261123/runs/full-001/capacity.json |
| strong | passed | /home/hanbo/workspace/LBM/deps/lbm3d-p2-final-20261123/runs/full-001/strong.json |
| weak | passed | /home/hanbo/workspace/LBM/deps/lbm3d-p2-final-20261123/runs/full-001/weak.json |
| scaling | passed | /home/hanbo/workspace/LBM/deps/lbm3d-p2-final-20261123/runs/full-001/scaling.log |
| stability | passed | /home/hanbo/workspace/LBM/deps/lbm3d-p2-final-20261123/runs/full-001/stability/run.log |

Online physics: 9/9 P1 checks; 6/6 scalar reference checks.

536³ capacity GPU peak MiB (pilot, sustained): 30863, 30863.

## Performance

| GPU | Strong ms/step | Weak ms/step | Strong efficiency | Weak efficiency | P1 strong time ratio |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 14.723 | 14.727 | — | — | 0.218 |
| 2 | 7.650 | 14.863 | 96.2% | 99.1% | 0.051 |
| 4 | 4.194 | 16.259 | 87.8% | 90.6% | 0.022 |

P1 ratios compare historical wall time only. The >85% efficiency gate uses this run's own single-GPU median.

## Reproduce


`plan.json` was saved before execution. `result.json` and case logs contain hashes, inputs, commands, diagnostics, and failures.
