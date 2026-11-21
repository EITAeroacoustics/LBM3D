# 单张 V100 的 TGV3D 计算规模上限

后续已执行网格块调整和无力临时场优化，分项收益见 [优化复测报告](force-field-optimization.md)。项目默认保持 `max_grid_size=64`、`blocking_factor=8`；下文保留优化前的容量基线，其他划分仅作专项容量实验。

测试日期：2026-11-21。使用 P1 洁净导入的模块化 TGV3D 二进制（SHA-256 `729b8f8957a0b31d08a77fcf5d6fe76680e21777a70c46f81da020a5bbc45e6e`）、AMReX 26.11、CUDA 12.2、双精度和一张 Tesla V100-SXM2-32GB。项目源码为 P1 固定提交 `995813161540d2a09e57a6571c73ada3fe121c03`。周期 D3Q19 Taylor–Green 涡，IBM 关闭。每次使用独立进程；默认成功判据是完成 10 步并正常退出。所有输入均设 `amr.plot_int=-1`、`amr.chk_int=-1`，工作目录只有输入、日志和小体积 JSON，没有全场流场文件。

## 实测边界

| `max_grid_size` | `blocking_factor` | 最大成功网格 | 首个失败网格 | 成功时显存峰值 |
|---:|---:|---:|---:|---:|
| 64（P1 原配置） | 8 | 328³ | 336³ | 31,095 MiB |
| 128 | 8 | 352³ | 360³ | 32,169 MiB |
| 192、256 | 8 | 352³ | 360³ | 30,665 MiB |
| 512 | 8 | 352³ | 360³ | 31,343 MiB |
| 192 | 4 | 356³ | 360³ | 31,857 MiB |
| 192 | 1 | **358³** | **359³** | **32,301 MiB** |

标准案例的边长粒度为 8；只调整 `max_grid_size`，可把单卡上限从 **328³＝35,287,552 格点**提高到 **352³＝43,614,208 格点**，增加 **23.6%**。放宽 `blocking_factor` 后测得的实验极限为 **358³＝45,882,712 格点**，比 P1 原配置增加 **30.0%**。358³/359³ 的成功/失败各重复两次，结果一致；[原始 JSON](single-gpu-ceiling-bf1.json) 与 [重复 JSON](single-gpu-ceiling-bf1-repeat.json) 保留每次输入、命令、显存和日志路径。

352³（`max_grid_size=192`、`blocking_factor=8`）和 358³（`max_grid_size=192`、`blocking_factor=1`）都额外连续运行 **100 步**并正常退出，见 [352³ 报告](single-gpu-ceiling-100steps.json) 与 [358³ 报告](single-gpu-ceiling-358-100steps.json)。这验证了短程计算，不能代替更长时间的稳定性结论。358³ 结束时 AMReX 报告仅余 **199 MB** GPU 内存；359³ 第 2 步申请约 **180 MiB** 时失败，当时仅余 **85 MB**。因此 358³ 是空闲 V100 上的实验性边界，不宜作为日常运行默认尺寸。

完整扫测见 [原始网格尺寸报告](single-gpu-ceiling.json)、[192 网格块报告](single-gpu-ceiling-grid192.json)、[512 网格块报告](single-gpu-ceiling-largebox.json)、[阻塞因子 4 报告](single-gpu-ceiling-bf4.json)。工作站原始日志位于 `/home/hanbo/workspace/LBM/runs/p1-13-offline-import/LBM3D-offline/work/single-gpu-ceiling*/`。AMReX 的 359³ 错误为 GPU `cudaMalloc` 内存不足，属于显存容量边界；并非磁盘写盘或物理判据失败。

## 为什么调整网格块有效

同为 328³，`max_grid_size=64` 的显存峰值为 **31,095 MiB**，改为 256 后为 **24,959 MiB**，减少 **6,136 MiB**。源码将 `nghost` 固定为 3；较小网格块带来更多带 ghost 的 FAB 和分配开销，这是该差异的主要解释，具体占比仍需逐对象内存剖析。352³ 时 `max_grid_size=128` 和 192/256 的峰值分别为 32,169 与 30,665 MiB。单块上限 512 未进一步提高容量，360³ 还遇到约 7.45 GB 的单次大块分配失败。192 或 256 可用于容量专项复测，不作为默认配置。

目前 `AmrCoreLBM` 同时保存 `f_old/f_new` 两套 19 分量分布函数、`macro_old/macro_new` 两套 6 分量宏观场。每步 `AdvancePhiAtLevel` 还分配 19 分量 `sfSborder`、6 分量 `smSborder`，以及 3 个单分量力场；TGV 未启用 IBM 或规定外力，这 3 个力场仍无条件分配。按有效格点估算，峰值阶段最多涉及约 78 个双精度标量/格点，另有 ghost、AMReX arena 和 CUDA 开销。源码位置见 `Source/AMReXAdapter/AmrCoreLBM.H`、`Source/AMReXAdapter/AmrCoreLBM.cpp` 和 `Source/AMReXAdapter/AdvanceLBMAtLevel.cpp`。

## 突破限制的实施顺序

1. **容量专项：调网格划分。** 默认继续使用 `max_grid_size=64`、`blocking_factor=8`。需要复核单卡上限时，可选 `max_grid_size=192`、`blocking_factor=8`；352³ 已完成 100 步，结束时约有 1,835 MB GPU 内存余量。已测的 `max_grid_size=256`、344³ 组合峰值为 28,855 MiB。这些结果不构成修改默认配置的建议。
2. **优先代码改进：去掉无外力路径的临时力场。** 目前三张单分量 `MultiFab` 在无 IBM、无规定外力时仍分配并清零。将零力直接传入核函数或分出简洁的无外力路径，可避免约 `3 × 8 × N³` 字节的有效区暂存，具体节省以实测为准。
3. **主要容量改进：减少整场 staging。** 19 分量 `sfSborder` 是最明显的单项临时占用；研究在单层周期网格上直接使用已有 population、完成碰撞后同步 halo 再迁移，避免额外整场复制。须保持 AMR/IBM 路径和时间层语义清晰，并重跑 P1 物理、场值、逐位、性能及容量回归。
4. **随后检查 ghost 与宏观场生命周期。** D3Q19 局部迁移与 IBM 对 ghost 的需求不同；可评估无 IBM 路径的较小 ghost 宽度，以及派生宏观量是否都需要保留两套整场。先做逐对象显存剖析，再决定实现，避免为了 TGV 容量破坏通用求解器模块边界。

混合精度和主机内存换页会改变数值精度或吞吐特性，不作为首选容量修复。若目标网格明显超过单卡可用显存，现有 2/4 GPU 分解已分别测到 416³/528³ 的 P1 容量边界；这属于扩大总资源，不改变上述单卡上限。
