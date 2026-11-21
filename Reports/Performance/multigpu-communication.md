# 多 GPU 通信路径优化（2026-11-21）

## 问题与改动

P1 的 256³ 强扩展在 1/2/4 张 V100 上出现负扩展。此前 Nsight Systems 跟踪显示，多卡时 `FillPatch`/`FillBoundary` 的 GPU 缓冲打包、解包及 MPI 等待占用大量时间；工作站的 Open MPI 4.1.2 构建未启用 CUDA 支持，见 [P1 性能报告](../P1/performance.md)。这说明重复交换大面积 ghost 数据值得优先削减，但剖析事件与本轮两个代码改动不能拆分为单项收益。

本轮在 `AdvancePhiAtLevel` 做两处调整：

1. 单层、全周期、无 IBM 几何时，碰撞前只把分布函数和宏观量的有效单元复制到临时 `MultiFab`。碰撞核只读有效单元；流动所需的跨块数据在碰撞后交换。AMR/IBM 或非周期路径继续使用原有 `FillPatch`。
2. 碰撞后的分布函数 `FillBoundary` 仅交换一层 ghost。D2Q9、D3Q19、D3Q27 的 pull streaming 至多读取邻近一层；原有三层 FAB 存储及其他路径保持原样。

默认 `max_grid_size=64`、`blocking_factor=8`，分布函数仍使用 AMReX `MultiFab` 布局。

## 256³ 强扩展

同一工作站的 4 张 Tesla V100-SXM2-32GB，AMReX 26.11、CUDA 12.2、Open MPI 4.1.2，双精度 Release `sm_70 -O3 -DNDEBUG`。固定 D3Q19 周期 Taylor–Green 涡、无 IBM 几何、网格 256³、块 64/8；每个 MPI 进程使用一张 GPU。2 卡使用 GPU `0,2` 且每个 NUMA 域一个进程；4 卡使用 `0,1,2,3` 且每域两个进程。每次独立运行 600 步，先预热 100 步，再同步 GPU 并按最慢进程计时 500 步。plotfile 与 checkpoint 均关闭。

每个配置运行两次：首轮原版先于优化版，复轮以相反顺序运行。表内是两次中位数；括号为观测范围。

| GPU | 原版 ms/步 | 优化版 ms/步 | 耗时降低 | 优化版相对其单卡加速 |
|---:|---:|---:|---:|---:|
| 1 | 63.835（63.830–63.841） | 50.881（50.879–50.883） | 20.3% | 1.00× |
| 2 | 143.920（143.568–144.273） | 41.834（41.822–41.845） | 70.9% | 1.22× |
| 4 | 180.779（180.258–181.299） | 36.972（36.924–37.021） | 79.5% | 1.38× |

此 256³ 案例的负扩展已消除：优化版双卡、四卡均快于优化版单卡，四卡约为原版四卡的 4.89 倍。四卡相对优化版单卡只有 1.38 倍，说明扩展效率仍有限；本次数据不能区分剩余的 MPI 主机中转、拓扑和其他同步开销。两轮重复足以确认本机这个案例的数倍收益，不足以外推到其他集群、网格和边界条件。

[首轮原始数据](multigpu-communication.json)与[反序复轮数据](multigpu-communication-paired.json)包含二进制/输入或日志 SHA-256、GPU 映射和工作站日志路径。原版与优化版二进制及输入分别固定为首轮 JSON 中的校验值；复轮复用同一批二进制与输入。工作站目录为 `/home/hanbo/workspace/LBM/runs/multigpu-opt-20261121`。例如从该目录复跑四卡优化版：

```sh
CUDA_VISIBLE_DEVICES=0,1,2,3 mpirun --map-by ppr:2:numa --bind-to numa -np 4 \
  build-validcopy/lbm3d_tgv3d \
  source-baseline-summary/Benchmarks/TGV3D/inputs_strong_256
```

## 数值与输出检查

- 使用 `lbm3d_tgv3d_summary` 对 128³ 案例运行 10 步，分别在 1/2/4 卡比较原版与优化版的最终密度、三个速度和 19 个分布函数分量。每个分量的求和、二范数、最小值、最大值的打印值逐项相同，共 23 个分量；[机器可读结果](field-summary-128.json)。这是紧凑统计比较，不是全场逐位相等的证明。
- 3D 球形 IBM 案例运行 2 步，原版与优化版的完整日志及 `force.dat` 各自字节一致；日志 SHA-256 为 `a1f43b4d439e16144f144a16fe026ee04fda0801a567d9daadf0b0b112293ee3`，力文件为 `344c0410784e4643437d2fd713ab8c5bfbdc32910b83adfd577fe3709b0c1da3`。
- 2D 指定体力案例运行 50 步，两版完整日志字节一致，SHA-256 为 `84d449ebc635a32473e08cb3783f973493c9d5b7bf2be8fb3a752a378d2dcf9b`。两维和三维构建均通过。
- 3D 非周期方管壁面案例运行 10 步，两版完整日志字节一致，SHA-256 为 `72eec8cd34f6d9bf38575fb3bb8055b09a024eff70e682ae9518300df561064e`。
- 所有本轮运行均关闭 plotfile/checkpoint；检查运行目录未发现 `plt*` 或 `chk*` 目录。统计程序只在内存中整理最终场，未写全场文件。

可重复使用的紧凑场统计工具见 [`field_summary.cpp`](../../Benchmarks/TGV3D/field_summary.cpp) 与 [`compare_field_summary.py`](../../Benchmarks/TGV3D/compare_field_summary.py)。
