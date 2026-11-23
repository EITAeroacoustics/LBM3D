# TGV3D 持续测试入口（T-01/T-02）

版本 1.0 的统一入口是 `run_tests.py`，冻结配置在 `test_config.json`。当前只测试三维 CUDA、D3Q19、AA 存储的 TGV。每次先写 `plan.json` 和环境快照，随后执行可用项目，保存 `result.json`、`report.md`、各案例日志，以及运行目录同级的 `history.json`。状态只用 `passed`、`failed`、`not_run`；只要有失败，整轮为失败；有未运行项，整轮不能通过。

## 构建和调用

摘要程序来自普通构建的 `lbm3d_tgv3d_summary`；计时程序来自单独的 `LBM_TIMING=ON` 构建的 `lbm3d_tgv3d`。P1 双精度摘要程序由独立的 P1 构建提供。默认验证已有二进制并保存哈希；需要在测试入口内重建时显式传 `--summary-build-dir`、`--timing-build-dir`，必要时用 `--cmake` 指定 CMake 3.25 以上的程序。有 CMake 缓存时记录其配置；计时构建由运行日志中的同步 500 步计时标记最终核实。构建后再次记录二进制哈希。

```sh
python3 Benchmarks/TGV3D/run_tests.py \
  --mode quick \
  --summary-binary /path/to/summary-build/lbm3d_tgv3d_summary \
  --mpirun mpirun \
  --mpi-options '--mca pml ucx' \
  --rank-wrapper Benchmarks/TGV3D/rank_gpu.py \
  --run-root /path/to/test-runs/quick-001
```

```sh
python3 Benchmarks/TGV3D/run_tests.py \
  --mode full \
  --summary-binary /path/to/summary-build/lbm3d_tgv3d_summary \
  --baseline-summary-binary /path/to/p1-build/lbm3d_tgv3d_summary \
  --timing-binary /path/to/timing-build/lbm3d_tgv3d \
  --mpirun mpirun \
  --mpi-options '--mca pml ucx' \
  --rank-wrapper Benchmarks/TGV3D/rank_gpu.py \
  --run-root /path/to/test-runs/full-001
```

每轮使用**新的**运行目录。`--plan-only` 只生成计划与 `not_run` 报告，不调用 GPU。`--only CHECK` 可单独复跑失败项目；独立复跑的其余项目仍为 `not_run`，因此不能把它当作完整验收。`report.md` 保存逐项复跑命令，须为复跑指定尚不存在的目录。若 MPI 在 `MPI_Init` 前初始化 CUDA，按工作站设置使用 `rank_gpu.py`。GPU 映射固定为 1 卡 `0`、2 卡 `0,2`、4 卡 `0,1,2,3`；并记录拓扑、驱动、`nvcc`、MPI、CMake 缓存、输入及二进制 SHA-256。

## 冻结测试矩阵

| 项目 | 快速 | 完整 | 判据 |
| --- | --- | --- | --- |
| TGV 摘要构建 | 是 | 是 | 已有二进制哈希可核实；显式请求重建时 CMake 目标成功 |
| TGV 计时构建 | — | 是 | 独立计时二进制哈希及 500 步同步计时标记；显式请求重建时 CMake 目标成功 |
| 64³/128³ 在线精度 | 是 | 是 | 物理时间 0/32/64、P1 九项物理判据、P1 标量参考、23 分量有限且正性；FP64 严格判据 |
| 1/2/4 卡紧凑场一致 | 是 | 是 | 128³ 的 10 与 11 步；位置指纹一致，数值统计差不大于 `1e-9`，方向性 halo 有效 |
| P1 双精度完整对照 | — | 是 | 复用 `check_precision_no_fields.py`，对独立 P1 构建执行同一组检查点并比对全部 23 分量统计 |
| 536³ 单卡容量 | — | 是 | 10 步预检与独立的至少 100 步推进；>1.5 亿格点，记录峰值显存、arena、在线质量/动能/正性/有限性 |
| 1/2/4 卡强弱扩展 | — | 是 | 同一计时二进制，前 100 步预热、后 500 步计时，各配置三轮交错；末步质量、halo、退出和无全场输出完整 |
| 扩展效率 | — | 是 | 强 `T1/(N×TN)`、弱 `T1/TN`；双卡和四卡四项均**严格大于 85%** |
| 稳定性 | — | 是 | 单卡 256³ 持续至少 600 秒，在线检查质量、动能、正性和非有限值；时长可用 CLI 显式改变并记录 |

完整硬件验收适用于工作站的 4 张 V100 32 GB。缺少所需 GPU、二进制、P1 对照或 MPI 时相关项为 `not_run`；GPU 初始占用超过配置上限时也不启动。FP32 仅报告为单独的等价性探索，整轮不标记 FP64 严格验收通过。容量与扩展结果仅在目标硬件上给出正式判定。性能变化列引用 P1 冻结强扩展报告作历史背景；效率分母只取**本轮同一计时二进制**的单卡中位步时。

所有运行命令显式覆盖 `amr.plot_int=-1`、`amr.chk_int=-1`，并检查没有 plotfile、checkpoint、HDF5 或 ADIOS 全场文件。P1 历史写盘入口 `run_p1.py` 与 `run_stability.py` 不在本体系中调用。紧凑位置指纹可检出多数值差异，但不等同于保存整个流场后逐格逐位比较。
