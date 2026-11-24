# TGV3D test run (full)

Agent 1.1; status **passed**; commit `b1ac7633ac3392ed99dbee3febff7453e4f93260`.

| Check | Status | Evidence / reason |
| --- | --- | --- |
| build_summary | passed | CMake build completed |
| quick_precision | passed |  |
| compact_even | passed |  |
| compact_odd | passed |  |
| build_timing | passed | CMake build completed |
| full_precision | passed | /home/hanbo/workspace/LBM/deps/lbm3d-tgv512-20261124/runs/full-002/full_precision/report.json |
| capacity | passed | /home/hanbo/workspace/LBM/deps/lbm3d-tgv512-20261124/runs/full-002/capacity.json |
| strong | passed | /home/hanbo/workspace/LBM/deps/lbm3d-tgv512-20261124/runs/full-002/strong.json |
| weak | passed | /home/hanbo/workspace/LBM/deps/lbm3d-tgv512-20261124/runs/full-002/weak.json |
| scaling | passed | /home/hanbo/workspace/LBM/deps/lbm3d-tgv512-20261124/runs/full-002/scaling.log |
| stability | passed | /home/hanbo/workspace/LBM/deps/lbm3d-tgv512-20261124/runs/full-002/stability/run.log |

Online physics: 9/9 P1 checks; 6/6 scalar reference checks.

536³ capacity GPU peak MiB (pilot, sustained): 30863, 30863.

## Performance

| GPU | Strong ms/step | Weak ms/step | Strong efficiency | Weak efficiency |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 145.865 | 145.743 | — | — |
| 2 | 72.166 | 145.763 | 101.1% | 100.0% |
| 4 | 38.906 | 159.271 | 93.7% | 91.5% |

The >85% efficiency gate uses this run's own single-GPU median.

## Reproduce


`plan.json` was saved before execution. `result.json` and case logs contain hashes, inputs, commands, diagnostics, and failures.
