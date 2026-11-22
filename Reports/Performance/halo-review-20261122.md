# D3Q19 方向性 halo 通信审查（2026-11-22）

## 结论

当前单层方向性 halo 的分量筛选、通信粒度和异步顺序基本合理；没有发现当前三维、单层、team size 1 路径的明确数值错误。四卡 TGV 强扩展为 90.53%、弱扩展为 97.05%，均满足现行大于 90% 的判据。现在不建议为了 halo 核或发送等待做立即重构。下一步若要提高四卡强扩展，应先量清接收等待有多少落在关键路径，再考虑把内部单元的流移与接收过程重叠。求解器的全场暂存复制是更大的数据搬运项，但属于推进算法优化，不应算成 halo 通信的直接收益。

上述第 1、2 项已完成[后续实测](halo-wait-and-staging-tests-20261122.md)：本地复制后暴露的接收窗口约 1 ms/步；仅去掉宏观场复制可保持四卡强弱效率大于 90%，去掉两次复制则使四卡绝对步时再降，但强效率低于现行门槛。具体建议以该测试报告为准。

## 审查范围与现状

- `Source/AMReXAdapter/DirectionalHalo.cpp` 用 AMReX `getFB(IntVect(1), periodicity)` 确定本地及跨 rank 交换区域，再按 D3Q19 pull streaming 的读取方向筛选分量：面 5 个、棱 1 个、角 0 个。跨 rank 对同一对端合并成一条消息。四卡 256³ TGV 的 rank 0 每步发送 662,528 个 `Real`，普通 19 分量 halo 对应 2,628,384 个，减少 74.79%；本地复制值数减少 74.09%。保留现有 AMReX `MultiFab` 布局。
- 接收请求先发出；GPU 打包完成后发出发送请求；随后执行本地 ghost 复制，再等待接收、发送并解包。GPU-aware MPI 路径使用 device buffer；非 GPU-aware 路径用 pinned-host 中转。
- 推进层 `Source/AMReXAdapter/AdvanceLBMAtLevel.cpp` 在碰撞后固定调用此 halo，未发现回退到普通 `FillBoundary` 的分支。现有 `m_directional_halo` 是单实例，适合当前单层；第二阶段多层局部加密时应按 level 缓存，并把几何周期性纳入匹配条件。

## 四卡实测证据

环境与输入沿用[三维专用构建的强弱扩展复测](three-d-only-scaling-retest.md)：4×V100-SXM2-32GB、AMReX 26.11、Open MPI 4.1.8 + UCX 1.21.1，`UCX_TLS=self,sm,cuda_copy`，`max_grid_size=64`、`blocking_factor=8`，不写 plotfile/checkpoint。当前计时二进制 SHA-256 为 `f293f7240ec8eabbe11a0f181fa1fae49a239735875609e84f88e093b8bd3f2b`。

一次完整 600 步、四 rank 的 Nsight Systems 跟踪在工作站 `runs/halo-review-nsys-full-4strong-20261122/`。rank 0 的观察值如下；GPU 核与复制持续时间受 profiler 扰动，不能直接相加作为无剖析步时，也不能把整个 MPI 等待时间都视为可消除的关键路径。

| 事件 | 600 步合计 | 每步约值 | 判断 |
| --- | ---: | ---: | --- |
| 方向性 halo GPU 核 | 1,800 次、229.6 ms | 3 次、0.383 ms | 发送打包、本地复制、接收解包各一次；当前没有逐段核启动 |
| 接收请求 `MPI_Wait` | 1,800 次、894.2 ms | 1.490 ms | 主要等待在接收侧；可能与本地 GPU 复制重叠 |
| 发送请求 `MPI_Wait` | 1,800 次、0.581 ms | 0.001 ms | 将发送等待移到解包之后收益上限很小 |
| halo tag 的 host→device 复制 | 1,800 次、12.4 ms | 0.021 ms | 每次 39,168 字节，单独缓存 tag 的可见收益有限 |
| AMReX `MultiFab::Copy` GPU 核 | 1,202 次、1,714.7 ms | 约 2 次、2.858 ms | 主要来自碰撞前的两个暂存场复制；属于推进阶段的数据搬运 |

`CUPTI_ACTIVITY_KIND_MEMCPY` 还记录 rank 0 双向各约 3.2 GB 的复制，主要由 512 KiB 的块组成，符合当前 UCX `cuda_copy` 传输路径。这个数据解释了为什么传输设置可能影响步时，但不表示所有复制时间都串行落在关键路径。

若将来把四卡强扩展目标提高到 95%，按当前单卡 42.015 ms/步计算，四卡步时需降至约 11.057 ms/步，比现值 11.602 ms/步少约 0.545 ms/步。剖析中的全部 halo GPU 核仅约 0.383 ms/步，单靠调整打包/解包核不足以可靠达到这一新目标；接收等待与推进阶段搬运更值得先量清。

用**同一二进制**只改 `amrex.use_gpu_aware_mpi` 做了四卡 A-B-B-A 顺序筛选，均预热 100 步、计时 500 步。GPU-aware device buffer 为 11.600、11.578 ms/步；pinned-host 中转为 13.064、13.138 ms/步。两组均正确结束、末步质量为 16,777,216，无全场输出。中位数分别为 **11.589** 和 **13.101 ms/步**；host 中转慢 **13.05%**，因此保持当前 GPU-aware 路径。[原始步时和命令](halo-review-transport-screen.json)。同一输入下，1/2/4 卡各 23 个最终场紧凑摘要与位置指纹均完全一致；两种路径均显示方向性 halo 已启用。[数值原始记录](halo-review-transport-field-summary.json)。

## 改进选项，按优先级

1. **保留现有通信路径。** 选择性分量、单层 ghost、每对端一条消息和发送期间的本地复制重叠均有实际价值；四卡强弱效率已过当前门槛。不要切换到 pinned-host 中转。
2. **若继续追求四卡强扩展，先定位接收等待的关键路径部分。** 在打包、发起通信、本地复制、接收完成、解包处加少量阶段计时或 NVTX，采用同一 TGV 输入和干净的端到端步时对照。随后才值得制作“接收期间计算内部单元流移”的小原型。此前普通 `FillBoundary_nowait` 的内区拆分试验变慢 3.9%–7.7%，方向性 halo 的重叠空间更小，原型必须以数值一致和实测步时决定是否保留。
3. **单独评估推进暂存场。** `sfSborder`、`smSborder` 每步创建并复制有效单元；持久化暂存 `MultiFab` 可以减少重复分配和 tag 指针更新，却不会消除有效单元复制。若目标是去掉复制，需要重新安排碰撞输入/输出和流移的数据流，须覆盖 TGV、物理边界及 IBM 数值回归；这是比 halo 微调更大的改动。
4. **第二阶段多层网格启用前，改为按 level 缓存 halo 元数据。** 当前只有一个 `m_directional_halo`；多层推进时会在 level 间反复构建。缓存键应包含 BoxArray、DistributionMapping 和周期性。这是将来多层场景的结构改进，不会提高当前单层 TGV 的效率。

不列入近期优化：逐段 GPU 核启动、调整发送等待顺序、仅缓存 39 KiB tag、在本工作站重试已知失败的 CUDA IPC 混合传输。上述选择缺少足够收益或已被对照否定。没有修改上游 AMReX/iLBMReX 代码。
