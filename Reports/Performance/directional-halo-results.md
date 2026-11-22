# D3Q19 方向性 halo：四卡强弱扩展验收（2026-11-22）

后续已固定三维单层 D3Q19 方向性 halo 路径，见[新版回归](directional-halo-fixed-d3q19.md)。本文的二进制校验值和性能数据保留为修改前全周期 TGV 验收记录；中间版本的[非周期边界回归](directional-halo-nonperiodic.md)亦保留。

## 实现与适用范围

`Source/AMReXAdapter/DirectionalHalo.H/.cpp` 使用 AMReX `getFB(IntVect(1), periodicity)` 的本地、发送、接收标签确定几何相交、周期映射和 rank 归属。D3Q19 pull streaming 在每个面只读取 5 个方向分量，在棱只读取 1 个，在角不读取分量；模块保持现有 `MultiFab` 19 分量布局，每个远端 rank 合并为一条消息。发送 pack 完成后先发出 MPI 请求，再执行同 rank ghost 复制，等待通信后解包；本地复制与 UCX 传输由此重叠。

本报告验收时，该路径在**单层、全周期、D3Q19、CUDA-aware MPI、AMReX team size 为 1** 时默认启用，其余情况继续用 AMReX `MultiFab::FillBoundary`。可用 `lbm3d.directional_halo=0` 关闭。`lbm3d.mass_check_interval` 默认 100，首步和末步仍检查质量。代码没有更改分布函数的数据布局或默认 `max_grid_size=64`、`blocking_factor=8`。本机采用 AMReX 26.11、4×V100-SXM2-32GB、CUDA-aware Open MPI 4.1.8 + UCX 1.21.1；`UCX_TLS=self,sm,cuda_copy`，UCX PML，双卡 GPU 0/2，四卡 0/1/2/3，按 NUMA 绑核。`rank_gpu.py` 在 `MPI_Init` 前限定每进程可见 GPU。先前检出的混合 `cuda_ipc` 质量错误配置没有使用。

四卡 128³ 的一次性启动日志报告 `LBM_DIRECTIONAL_HALO active=1`，rank 0 的远端发送/接收分量值均为 **165,376 / 652,080**（方向筛选 / 通用 FillBoundary），本地复制为 **81,920 / 311,296**。因此这次通信的分量值数约减少四分之三；这不是逐步传输字节计量，实际加速以计时为准。

## 数值检查

1/2/4 卡的 128³、10 步测试，将最终密度、三个速度和 19 个分布函数的求和、二范数、极值，以及由全局位置与浮点位模式混合的两个整数指纹逐项比较，均与普通 FillBoundary 完全一致；见[默认启用版本的原始结果](directional-halo-fingerprint-default-128.json)。指纹是紧凑、位置敏感的回归证据，不宣称数学上的无碰撞证明或覆盖所有物理算例。脚本强制关闭 plotfile/checkpoint，并检查没有全场文件。

最终二进制 SHA-256 为 `040613166e43cc607e28aaec29e07e14d825c953b1599ce5f8fe66a5067aafae`。用于构建的六个关键源码/CMake 文件与本地工作树的 SHA-256 一致。2D CUDA + IBM 构建通过，非周期 cavity 两步运行通过；3D 非周期 square duct 两步运行通过且没有启用方向性 halo。两次短运行均关闭全场输出。

## 三轮交错扩展结果

输入固定 100 步预热、500 步计时，取最慢 MPI rank 的步时；1/2/4、4/2/1、1/2/4 交错运行，每档取三轮中位数。强扩展固定 256³，弱扩展每卡 256³。**下表使用同一个最终二进制，命令不传 `directional_halo` 启用开关。**

| 测试 | 1 卡 ms/步 | 2 卡 ms/步 | 4 卡 ms/步 | 2 卡效率 | 4 卡效率 |
| --- | ---: | ---: | ---: | ---: | ---: |
| [强扩展](directional-halo-strong-default-final-3r.json) | 42.022 | 21.230 | 11.618 | 98.97% | **90.43%** |
| [弱扩展](directional-halo-weak-default-final-3r.json) | 42.027 | 42.173 | 43.337 | 99.65% | **96.98%** |

`check_scaling.py` 对同一二进制的这两份 JSON 给出 `passed=true`。18 次 600 步运行的末步质量均为期望值：强扩展 16,777,216；弱扩展 1/2/4 卡分别为 16,777,216 / 33,554,432 / 67,108,864。每次运行均检查没有 plotfile/checkpoint，原始 JSON 保留输入、二进制和日志校验值。四卡强效率高于 90% 的幅度约 **0.43 个百分点**，其他机器、问题规模或 MPI 实现需要重新测量。

为单独确认通信模块的收益，用**同一最终二进制**按关→开→开→关顺序配对运行四卡强算例，步时依次为 **15.567、11.613、11.646、15.425 ms/步**。两组中位数约为 15.496 与 11.630 ms/步，开启后快约 **25.0%**；四次末步质量均为 16,777,216 且未写全场。[配对原始记录](directional-halo-paired-final.json)保存日志路径和校验值。

复跑需在该工作站使用上述 UCX/Open MPI 与 AMReX 安装，并运行 `Benchmarks/TGV3D/run_strong.py`、`run_weak.py`；传 `--mass-check-interval 100`、`--mpirun`、`--mpi-options="--mca pml ucx --mca pml_ucx_tls any --mca btl ^uct"`、`--rank-wrapper rank_gpu.py`，同时设置上文 UCX 环境。若运行环境没有 CUDA-aware MPI，代码会回退到普通 FillBoundary，不能套用本报告的多卡效率。
