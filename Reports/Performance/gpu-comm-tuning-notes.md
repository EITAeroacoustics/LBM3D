# CUDA-aware MPI 通信调参证据与试验次序

日期：2026-11-21。本文记录 AMReX 26.11、Open MPI 4.1.8 源码和 Nsight 的调参依据；后续实测及失效边界见[CUDA-aware MPI 结果](gpu-aware-mpi-results.md)。工作站 CUDA-aware 构建、拓扑与验收口径见 [GPU 通信路径](gpu-communication-path.md)、[独立 MPI 方案](gpu-aware-mpi-plan.md) 和 [扩展基线](scaling-overlap-assessment.md)。

## 已核实的实现

- AMReX `Src/Base/AMReX_FabArrayCommI.H:PrepareSendBuffers` 按远端 rank 汇总所有 halo `CopyComTag`，在一个通信 arena 块中划出各 peer 缓冲；`PostSnds` 对每个 peer 发一条 `Asend`。当前 D3Q19 有 19 个分量，低于 `Src/Base/AMReX_FabArrayBase.cpp` 的 `fabarray.maxcomp=25` 默认值，故没有逐分量发消息的问题。`fabarray.comm_tile_size` 在 GPU 构建默认各方向 1,024,000，大于当前 64³ 网格块，不会把每个 halo 面切成额外小 tile。
- 新 AMReX 与 Open MPI 的 CUDA-aware 查询通过后，`The_Comms_Arena()` 为设备 arena；旧系统 MPI 构建则为 mapped pinned host arena。通信 arena 的默认 release threshold 为最大整数，分配缓冲可在预热后复用。把 `amrex.the_comms_arena_init_size` 改大只影响预留，缺少能改善稳态通信的证据。
- `FillBoundary_nowait` 在发出远程收发后，已经执行本地 ghost copy，并在本地复制前后调用 `FillBoundary_test()`。应用额外的内区计算重叠试验在旧 MPI 栈上反而使强、弱扩展绝对耗时增加，见[实测](scaling-overlap-assessment.md)。因此不先假定单纯增加 nowait 区间会带来收益。
- 新 Open MPI `opal/mca/btl/smcuda/btl_smcuda_component.c` 把 `btl_smcuda_cuda_max_send_size` 默认设为 **131,072 B**；`ompi/mca/pml/ob1/pml_ob1_sendreq.c:986-987` 对 CUDA 缓冲以此上限减去片头作为长消息的片段大小。`pml_ob1_send_pipeline_depth=3`、`pml_ob1_recv_pipeline_depth=4` 是 `pml_ob1_component.c` 默认值。旧一层 halo 四卡 Nsight rank 0 的 `MPI_P2P_EVENTS` 出现 10,433,280 B 和 2,196,480 B 消息；第一种在 128 KiB 上限下需约 80 个片段。
- `smcuda` 的 `btl_smcuda_use_cuda_ipc` 默认 1。当前四卡跨 socket GPU 不支持 peer access；开启 IPC 的实际启动在第 1 步出现 `cuIpcOpenMemHandle` 错误并中止，设 `--mca btl_smcuda_use_cuda_ipc 0` 后 10 步完成。`btl_smcuda_component.c:739-751` 对两进程报告相同 CUDA device ordinal 时默认视为同卡；每 rank 的 `CUDA_VISIBLE_DEVICES` 都限定一张卡时，设备 ordinal 均为 0，因此不能依赖其默认同卡 IPC 判定。当前四卡试验应继续显式关闭 CUDA IPC。
- `smcuda` 初始化时曾报告一次 `cuMemHostRegister` 失败。`opal/mca/common/cuda/common_cuda.c:731-742` 明确将预分配 BTL 内存的注册失败视为**非致命**并继续；这是初始化警告，不证明每步复制失败。`--mca mpi_common_cuda_register_memory 0` 可禁止该注册尝试，但可能让共享内存缓冲保持 pageable，不应作为优先性能调参或仅为隐藏警告而默认启用。

## 小范围调参依据

先保持同一 CUDA-aware 二进制、`--mca pml ob1 --mca btl self,smcuda,tcp --mca btl_smcuda_use_cuda_ipc 0`、相同 GPU 映射和无全场输出，对比下面两个**单因素**选项。先做 2/4 卡强、弱扩展各一次；只有绝对 ms/步有明确收益才做三次交错复测、紧凑场对照与 90% 效率门槛检查。

1. `--mca btl_smcuda_cuda_max_send_size 524288`，再试 `1048576`。假设减少 10 MB 消息的片段数和 OB1 调度开销；更大片段也可能降低并行流水、增加暂存和延迟，实际方向须测。
2. 若片段调大仍显示 MPI 进展受限，单独测试 `--mca pml_ob1_send_pipeline_depth 8 --mca pml_ob1_recv_pipeline_depth 8`，并与默认 3/4 比较。更多在途片段可能隐藏拷贝延迟，也会增加暂存内存和竞争。先检查 Nsight MPI 等待与 CUDA copy 事件，再决定是否投入。

`fabarray.maxcomp`、`fabarray.comm_tile_size`、arena 初始大小以及 `mpi_common_cuda_register_memory` 不列为首轮速度候选，因为当前源码和消息规模未显示相应瓶颈。任何参数都不改变 LBM 的默认 `max_grid_size=64`、`blocking_factor=8` 或 MultiFab 布局。

## 只读复核

在工作站 `/home/hanbo/workspace/LBM` 执行：

```sh
ompi=/home/hanbo/workspace/LBM/deps/openmpi-4.1.8-cuda/bin/ompi_info
"$ompi" --param btl smcuda --level 9 | grep -E 'cuda_max_send_size|use_cuda_ipc'
"$ompi" --all | grep 'mpi_common_cuda_register_memory'
"$ompi" --param pml ob1 --level 9 | grep 'pipeline_depth'
grep -n -E 'MaxComp =|comm_tile_size|ParmParse pp\("fabarray"\)' deps/lbm3d-amrex-26.11/Src/Base/AMReX_FabArrayBase.cpp
grep -n -E 'PrepareSendBuffers|PostSnds|FillBoundary_test|FB_local_copy_gpu' deps/lbm3d-amrex-26.11/Src/Base/AMReX_FabArrayCommI.H
grep -n -E 'btl_cuda_max_send_size|send_pipeline_depth' deps/openmpi-4.1.8/ompi/mca/pml/ob1/pml_ob1_sendreq.c
```

现有消息大小来自：

```sh
python3 - <<'PY'
import sqlite3
db = sqlite3.connect('runs/multigpu-opt-20261121/profile-halo1-4gpu/rank_0.sqlite')
for row in db.execute('SELECT size, COUNT(*) FROM MPI_P2P_EVENTS '
                      'WHERE size > 0 GROUP BY size ORDER BY COUNT(*) DESC'):
    print(row)
PY
```
