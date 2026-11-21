# CUDA-aware MPI 与强弱扩展试验（2026-11-21）

## 构建和通信路径

官方 Open MPI 4.1.8 源码 SHA-256 `fb41086bbed9300baa2f3d7572491facfe5257412fa524ec5a396aa9101d5c62`，已独立安装于工作站用户目录 `deps/openmpi-4.1.8-cuda`；`ompi_info` 显示 CUDA 支持和 `smcuda`，1/2 进程 `MPIX_Query_cuda_support()` 均返回 1。AMReX 26.11 使用新 `mpicxx` 独立重建，LBM3D 求解器 `ldd` 指向该前缀的 `libmpi.so.40`。构建步骤见[独立 MPI 方案](gpu-aware-mpi-plan.md)。求解器二进制 SHA-256 为 `8577b6a5f97e2d28c95b3121fe74af91041a3e827f4449b3b031831ce488a3e2`。

四卡跨 CPU socket 的 GPU 不支持 peer access。`smcuda` 默认 CUDA IPC 在第 1 步因 `cuIpcOpenMemHandle` 失败而中止；以下有效试验均设 `--mca pml ob1 --mca btl self,smcuda,tcp --mca btl_smcuda_use_cuda_ipc 0`。`rank_gpu.py` 在每个进程的 `MPI_Init` 前设单 GPU 可见。MPI 初始化的 `cuMemHostRegister` 警告非致命，见[通信调参证据](gpu-comm-tuning-notes.md)。128³、10 步的 1/2/4 卡最终场各 23 个分量的求和、二范数、极值均与原构建打印值相同，见[数值对照](gpu-aware-field-summary-128.json)。所有运行关闭 plotfile/checkpoint。

## 单轮筛选

固定 256³ 强扩展和每卡 256³ 弱扩展、64/8 分块；预热 100 步，按最慢 MPI 进程计时 500 步。表中每项仅一次，适合筛选参数，**不构成最终三轮性能验收**。前四列均为 ms/步。

| MPI / CUDA 片段 | 强 1 卡 | 强 2 卡 | 强 4 卡 | 弱 2 卡 | 弱 4 卡 |
|---|---:|---:|---:|---:|---:|
| 原系统 MPI、一层 halo（既有中位数） | 50.881 | 41.834 | 36.972 | 67.332 | 100.720 |
| CUDA-aware，默认 128 KiB | 50.886 | 37.893 | 31.174 | 61.024 | 85.336 |
| CUDA-aware，512 KiB | 50.899 | 34.566 | 27.949 | 未测 | 未测 |
| CUDA-aware，1 MiB | 50.900 | 34.084 | 27.397 | 56.509 | 77.782 |
| CUDA-aware，2 MiB | 50.887 | 31.918 | 24.907 | 54.467 | 73.924 |

2 MiB 试验的弱扩展 1 卡为 50.891 ms/步。按各自同一构建的单卡时间计算，其双/四卡强扩展效率为 **79.7% / 51.1%**，弱扩展为 **93.4% / 68.8%**。只有双卡弱扩展在单轮中超过 90%，需要重复确认；其余三项仍未达标。原始命令、二进制/输入和日志校验值见 [默认强](gpu-aware-strong-r1.json)、[默认弱](gpu-aware-weak-r1.json)、[512 KiB 强](gpu-aware-strong-frag512-r1.json)、[1 MiB 强](gpu-aware-strong-frag1024-r1.json)、[1 MiB 弱](gpu-aware-weak-frag1024-r1.json)、[2 MiB 强](gpu-aware-strong-frag2048-r1.json) 和 [2 MiB 弱](gpu-aware-weak-frag2048-r1.json)。

进一步增至 4 MiB 时，双卡一次为 30.886 ms/步，但四卡在 600 步试验中 CPU 满载自旋、GPU 空闲、无时间步输出；该进程已终止，不能作为有效配置。2 MiB 下把 OB1 发送/接收 pipeline depth 从 3/4 增至 8/8，双卡 31.975、四卡 27.535 ms/步，四卡回退，见[流水深度数据](gpu-aware-strong-frag2048-depth8-r1.json)。

在 2 MiB 和新 MPI 上重试 `FillBoundary_nowait` 内区计算，1/2/4 卡分别为 54.797/36.553/27.215 ms/步，均慢于同步版 50.887/31.918/24.907；[原始数据](gpu-aware-overlap-strong-frag2048-r1.json)。128³ 数值统计一致，但性能不保留重叠改动。AMReX 的 `FillBoundary_nowait` 已在远程收发期间执行本地 ghost copy；新增内区/边界拆分开销抵消了可隐藏的等待。

## 剩余瓶颈

四卡 20 步 Nsight Systems 跟踪中，rank 0 的 GPU 发送打包与接收解包核合计仅占 GPU 操作时间约 **0.9%**（1.90/2.60 ms）；旧系统 MPI 的一层 halo 跟踪中两者合计约 **51.1%**（223/100 ms）。两份跟踪都含初始化及进程退出，不能直接相除得稳态加速。新路径的 GPU 求解核、暂存复制、本地 ghost 复制仍占主要 GPU 工作，MPI 等待仍明显；原始跟踪在工作站 `runs/multigpu-mpi-cuda/profile-frag2048-4gpu/rank_0.nsys-rep`。2 MiB 强扩展四卡距 >90% 所需的约 14.1 ms/步仍差约 10.8 ms/步。下一轮将单独验证带 CUDA transport 的 UCX，并保持相同输入与效率门槛；不能把通信能力或单轮收益当作目标完成。
