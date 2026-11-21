# GPU 间通信路径核实（2026-11-21）

本记录针对当前 4 张 Tesla V100-SXM2-32GB 工作站、AMReX 26.11、Open MPI 4.1.2，以及 `multigpu-communication.md` 所用的 CUDA 构建和 256³ TGV 输入。调查只读取构建、源码、拓扑及已有 Nsight 结果；另运行了仅调用 `MPI_Init`/`MPI_Finalize` 的 CPU 探针，未启动新的 GPU 性能任务。

## 已核实的路径

`ompi_info --parsable --all` 报告 `opal_built_with_cuda_support=false`，其别名 `mpi_built_with_cuda_support=false`。AMReX `Src/Base/AMReX_ParallelDescriptor.cpp` 的 `Initialize()` 仅在 MPI CUDA 支持查询成功时把 `use_gpu_aware_mpi` 默认设为真；当前 TGV 输入未覆盖 `amrex.use_gpu_aware_mpi`。安装的 `AMReX_Config_3D.H` 同时启用 MPI 和 CUDA。

在 `use_gpu_aware_mpi=false` 时，AMReX `Src/Base/AMReX_Arena.cpp` 把 `The_Comms_Arena()` 指向 pinned host arena。该 arena 用 `cudaHostAllocMapped` 分配内存。`Src/Base/AMReX_FabArrayCommI.H` 的 `PrepareSendBuffers()` 和 `PostRcvs()` 均从这个 arena 分配缓冲，`PostSnds()` 将其指针传给 MPI。`Src/Base/AMReX_FBI.H` 的 GPU pack/unpack kernel 直接读写这块映射的主机内存；pack 后有 `Gpu::streamSynchronize()`，MPI 发送随后开始。

所以本构建的跨 MPI GPU 数据路径为：**GPU kernel ↔ 映射的 pinned host 缓冲 ↔ 普通 MPI ↔ 映射的 pinned host 缓冲 ↔ GPU kernel**。它不使用 GPU Direct，也不是每步由显式 `cudaMemcpy` 完成的 GPU↔host 拷贝。AMReX 的 `FillBoundary_nowait()` 发出 MPI 请求后可让应用处理内部单元，再调用 `FillBoundary_finish()` 等待、解包；同步 `FillBoundary()` 没有这段应用侧重叠窗口。

已有的优化前 2 卡 Nsight 数据库 `runs/tgv-profile-2gpu/rank_0.sqlite` 中，CUPTI memcpy 只有 432 次 HtoD（共 21,478,720 B）和 4 次微小 HtoD，未记录每步大量 DtoH 或 peer copy。这与 mapped host kernel 访问相符，但该追踪不是优化版数据，也不能仅凭 memcpy 表反推传输带宽或实际 MPI 等待时间。

## 拓扑与 MPI 探针

`nvidia-smi topo -m` 显示 GPU 0/1 位于 NUMA 0、GPU 2/3 位于 NUMA 1；同 NUMA GPU 之间为 `PHB`，跨 NUMA 为 `SYS`，没有 NVLink。此前双卡测试选 `0,2`，因此跨 CPU socket；四卡测试跨两个 NUMA 域。

CPU-only 小探针在同一 Open MPI 上执行 `MPI_Init`，`--mca pml_base_verbose 20` 显示两个进程都选中 `pml ob1`；`--mca btl_base_verbose 10` 显示 `vader`、`tcp`、`self` 组件初始化。该探针只证明此启动环境的 PML 选择及候选 BTL 初始化，不能单独证明每一条 GPU 求解器消息实际采用哪个 BTL 或量化跨 NUMA 传输。由于 MPI 不接受 GPU 缓冲，此区别不改变上面的 pinned host 结论。

## 复核命令

以下命令在工作站 `/home/hanbo/workspace/LBM` 执行；AMReX 源码位于 `deps/lbm3d-amrex-26.11`，安装头位于 `runs/p1-13-offline-import/LBM3D-offline/work/amrex-install-3d/include`：

```sh
ompi_info --parsable --all | grep -E 'opal_built_with_cuda_support:value|mpi_built_with_cuda_support:value'
nvidia-smi topo -m
grep -E 'AMREX_USE_MPI|AMREX_USE_CUDA' runs/p1-13-offline-import/LBM3D-offline/work/amrex-install-3d/include/AMReX_Config_3D.H
grep -n 'use_gpu_aware_mpi' deps/lbm3d-amrex-26.11/Src/Base/AMReX_ParallelDescriptor.cpp
grep -n -E 'The_Comms_Arena|cudaHostAllocMapped' deps/lbm3d-amrex-26.11/Src/Base/AMReX_Arena.cpp
grep -n -E 'PrepareSendBuffers|PostRcvs|PostSnds' deps/lbm3d-amrex-26.11/Src/Base/AMReX_FabArrayCommI.H
grep -n -E 'pack_send_buffer_gpu|streamSynchronize' deps/lbm3d-amrex-26.11/Src/Base/AMReX_FBI.H
```

CPU-only PML 探针：

```sh
cat >/tmp/lbm3d_mpi_probe.c <<'EOF'
#include <mpi.h>
int main(int argc, char** argv) { MPI_Init(&argc, &argv); MPI_Finalize(); return 0; }
EOF
mpicc /tmp/lbm3d_mpi_probe.c -o /tmp/lbm3d_mpi_probe
mpirun --mca pml_base_verbose 20 --mca btl_base_verbose 10 -np 2 /tmp/lbm3d_mpi_probe
```

已有 Nsight 数据的 memcpy 方向汇总：

```sh
python3 - <<'PY'
import sqlite3
db = sqlite3.connect('runs/tgv-profile-2gpu/rank_0.sqlite')
query = '''SELECT copyKind, srcKind, dstKind, COUNT(*), SUM(bytes)
           FROM CUPTI_ACTIVITY_KIND_MEMCPY
           GROUP BY copyKind, srcKind, dstKind ORDER BY SUM(bytes) DESC'''
print(*db.execute(query).fetchall(), sep='\n')
PY
```

在该数据库的 `ENUM_CUDA_MEMCPY_OPER` 中，`copyKind=1` 为 HtoD；`ENUM_CUDA_MEM_KIND` 的 `srcKind=1` 为 pinned host、`dstKind=2` 为 device。
