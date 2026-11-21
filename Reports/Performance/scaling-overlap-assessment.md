# 多 GPU 扩展与重叠试验（2026-11-21）

## 固定验收口径

工作站和 256³ 强扩展参数沿用[多 GPU 通信报告](multigpu-communication.md)。强扩展效率定义为同一构建的 `T1 / (N × TN)`；弱扩展每卡固定 256³ 格点、`max_grid_size=64`、`blocking_factor=8`，效率定义为同一构建的 `T1 / TN`。两者都以预热 100 步后的 500 步 MPI 最慢进程耗时计算，不写 plotfile/checkpoint。弱扩展的 1/2/4 卡全局格点为 256×256×256、256×256×512、256×512×512；`dx=0.25`。扩大物理域后 TGV 波长随轴长改变，所以这是计算弱扩展，不比较同一物理解。

当前已验证的优化版在 256³ 强扩展上的双卡、四卡效率为 **60.8% / 34.4%**（各两次中位数），见[汇总](strong-baseline-256.json)、[原始数据](multigpu-communication.json)和[反序复测](multigpu-communication-paired.json)。新增弱扩展基线各运行三次、交错顺序 1-2-4 / 4-2-1 / 1-2-4，得到双卡 **75.6%**、四卡 **50.5%**；[机器可读数据](weak-baseline-256-per-gpu.json)。`python3 Benchmarks/TGV3D/check_scaling.py Reports/Performance/strong-baseline-256.json Reports/Performance/weak-baseline-256-per-gpu.json` 已按同一二进制核验这四项均未达到 90%。

## `FillBoundary_nowait` 重叠试验

AMReX 26.11 在 GPU 打包完成并同步 stream 后才发起 MPI，`FillBoundary_nowait` 返回后到 `FillBoundary_finish` 前允许应用处理不依赖 ghost 的单元。试验版在单层、全周期、无力路径上先发起一层 halo 交换，再完成每个 FAB 缩小一格的内区 streaming 与宏观量计算，最后等待通信、处理边界；其他路径保留原顺序。它不与碰撞核重叠。试验在独立源码及构建目录 `runs/multigpu-opt-20261121/{source-overlap,build-overlap}` 完成，未覆盖基线。

| 测试 | GPU | 原版 ms/步 | 重叠版 ms/步 | 重叠版耗时变化 |
|---|---:|---:|---:|---:|
| 强扩展 256³ | 1 | 50.881 | 54.761 | +7.6% |
| 强扩展 256³ | 2 | 41.834 | 43.564 | +4.1% |
| 强扩展 256³ | 4 | 36.972 | 38.429 | +3.9% |
| 弱扩展 256³/GPU | 1 | 50.873 | 54.769 | +7.7% |
| 弱扩展 256³/GPU | 2 | 67.332 | 70.838 | +5.2% |
| 弱扩展 256³/GPU | 4 | 100.720 | 105.435 | +4.7% |

强扩展重叠版各三次、取中位数；弱扩展重叠版为一次筛选样本，原版各三次。原始命令、二进制/输入 SHA-256 和日志路径见[强扩展 JSON](overlap-strong-256.json)与[弱扩展 JSON](overlap-weak-256-per-gpu-r1.json)。128³ 的 1/2/4 卡 10 步最终场 23 个分量的求和、二范数与极值逐项相同，见[紧凑场对照](overlap-field-summary-128.json)。全部试验关闭全场输出。

该实现对所有配置的绝对耗时均有回退，已从工作树撤销。相对效率偶有上升只是单卡分母变慢造成的，不能视为扩展改进。

同一基线二进制、输入与 500 步计时下，双卡改为同插槽 GPU `0,1`、`--map-by ppr:2:numa --bind-to numa`，两次为 48.116、48.289 ms/步，反而慢于跨插槽 `0,2` 的 41.834 ms/步中位数。同插槽放置没有解决当前瓶颈；可能因两个进程共享同一 CPU/内存域而抵消了局部通信收益，但该原因尚未经分项剖析。原始日志位于工作站 `runs/multigpu-opt-20261121/topology-2gpu/0-1/r{1,2}/run.log`，SHA-256 分别为 `b6139d5a23a5484a35723b3be358cfe1ade3c21925a5074ff8d07f3dfcbfd4f5`、`8a7dd16a1adc9d3bfde7dd744a1f00512a93d9c2f0241d95e06e65b82de4da01`。

下一步检验独立 CUDA-aware MPI；当前通信路径的证据见[通信路径报告](gpu-communication-path.md)。

当前一层 halo 优化版的独立四卡 Nsight Systems 跟踪（固定 256³，20 步、无全场输出）显示 rank 0 的 GPU 操作时间中，发送打包核占 35.3%（223 ms）、接收解包核占 15.8%（100 ms）；`MPI_Waitall` 事件累计 574 ms。跟踪含初始化和进程退出，且 GPU 与 MPI 时间可重叠，这些累计值不能简单相加或当作稳定每步耗时。原始报告为工作站 `runs/multigpu-opt-20261121/profile-halo1-4gpu/rank_0.nsys-rep`，可用 `nsys stats --report cuda_gpu_sum --format csv` 复核；MPI 事件来自其 SQLite `MPI_START_WAIT_EVENTS` 表。通信相关操作在一层 halo 版中仍占明显比例，支持继续检验 MPI 缓冲路径。
