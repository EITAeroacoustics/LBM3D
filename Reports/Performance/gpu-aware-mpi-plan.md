# CUDA-aware MPI 隔离试验计划

日期：2026-11-21。本文件记录可复现的独立构建方案与验收门槛。官方 Open MPI 4.1.8 源包已按下述 SHA-256 校验并安装在用户目录；新 `ompi_info` 显示 CUDA 支持与 `smcuda`，1/2 进程运行时探针均返回 `MPIX_Query_cuda_support()=1`。求解器性能仍须待 AMReX/LBM3D 重建与数值对照后测量。

## 现状与假设

工作站系统 Open MPI 4.1.2 的 CUDA support 为 `false`；UCX 1.12.1 的 `ucx_info -v/-d` 没有 CUDA 配置或 transport，系统 Open MPI 也没有 `smcuda` BTL。已核实的 LBM3D 通信路径见 [GPU 通信路径报告](gpu-communication-path.md)。CUDA 12.2 toolkit 位于 `/usr/local/cuda`，含 `cuda.h` 和 `lib64/stubs/libcuda.so`。工作站可以访问 Open MPI 官方 4.1.8 归档 URL（`wget --spider` 返回 0）。

AMReX 26.11 的 `ParallelDescriptor::Initialize()` 只有在编译期检测到 Open MPI CUDA 扩展、且运行时 `MPIX_Query_cuda_support()` 为真时才默认启用 GPU-aware MPI；`The_Comms_Arena()` 随之从 mapped pinned host 改为 device arena。因此不能只替换 `mpirun`，也不能用当前系统 MPI 强制设置 `amrex.use_gpu_aware_mpi=1`。试验必须用新 MPI **重新构建 AMReX 和 LBM3D**，并独立保留原基线。

## 独立构建步骤

优先试 Open MPI 4.1.8，同属当前 4.1 系列，减少版本变化因素。[官方发布页](https://www.open-mpi.org/software/ompi/v4.1/)列出的 `openmpi-4.1.8.tar.gz` SHA-256 为 `fb41086bbed9300baa2f3d7572491facfe5257412fa524ec5a396aa9101d5c62`。[官方 CUDA 文档](https://docs.open-mpi.org/en/main/tuning-apps/accelerators/cuda.html)说明 `--with-cuda`、`--with-cuda-libdir`、`smcuda` 和 `MPIX_Query_cuda_support()` 的用途。以下均在用户目录执行，不覆盖 `/usr/bin/mpirun` 或现有 AMReX：

```sh
set -eu
deps=/home/hanbo/workspace/LBM/deps
mpi_prefix="$deps/openmpi-4.1.8-cuda"
wget -O "$deps/openmpi-4.1.8.tar.gz" \
  https://download.open-mpi.org/release/open-mpi/v4.1/openmpi-4.1.8.tar.gz
printf '%s  %s\n' \
  fb41086bbed9300baa2f3d7572491facfe5257412fa524ec5a396aa9101d5c62 \
  "$deps/openmpi-4.1.8.tar.gz" | sha256sum -c -
tar -xzf "$deps/openmpi-4.1.8.tar.gz" -C "$deps"
mkdir -p "$deps/openmpi-4.1.8-build-cuda"
cd "$deps/openmpi-4.1.8-build-cuda"
../openmpi-4.1.8/configure --prefix="$mpi_prefix" \
  --with-cuda=/usr/local/cuda \
  --with-cuda-libdir=/usr/local/cuda/lib64/stubs \
  --without-ucx
make -j 8
make install
"$mpi_prefix/bin/ompi_info" --parsable --all | \
  grep 'mpi_built_with_cuda_support:value:true'
"$mpi_prefix/bin/ompi_info" --param btl smcuda
```

系统 UCX 不含 CUDA，所以首轮使用 Open MPI 内部 `smcuda` 路径并禁用该 UCX。只有上面两个能力检查通过，才配置新的 AMReX 3D CUDA 构建（与当前 26.11 基线相同选项）：

```sh
deps=/home/hanbo/workspace/LBM/deps
mpi_prefix="$deps/openmpi-4.1.8-cuda"
cmake3=/home/hanbo/workspace/LBM/deps/cmake-3.30.9-linux-x86_64/bin/cmake
"$cmake3" -S "$deps/lbm3d-amrex-26.11" \
  -B "$deps/amrex-26.11-build-3d-mpi-cuda" \
  -DCMAKE_INSTALL_PREFIX="$deps/amrex-26.11-install-3d-mpi-cuda" \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_FLAGS_RELEASE='-O3 -DNDEBUG' \
  -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc \
  -DCMAKE_CUDA_ARCHITECTURES=70 \
  -DMPI_CXX_COMPILER="$mpi_prefix/bin/mpicxx" \
  -DAMReX_SPACEDIM=3 -DAMReX_GPU_BACKEND=CUDA -DAMReX_MPI=ON \
  -DAMReX_PARTICLES=ON -DAMReX_PRECISION=DOUBLE \
  -DAMReX_FORTRAN=OFF -DAMReX_CUDA_FASTMATH=OFF
"$cmake3" --build "$deps/amrex-26.11-build-3d-mpi-cuda" -j 8
"$cmake3" --install "$deps/amrex-26.11-build-3d-mpi-cuda"
```

然后用新 `AMReX_DIR` 和 `MPI_CXX_COMPILER` 在**独立构建目录**配置 LBM3D，保持 `LBM_TIMING=ON`、Release、`sm_70`、`-O3 -DNDEBUG`：

```sh
deps=/home/hanbo/workspace/LBM/deps
mpi_prefix="$deps/openmpi-4.1.8-cuda"
cmake3="$deps/cmake-3.30.9-linux-x86_64/bin/cmake"
trial=/home/hanbo/workspace/LBM/runs/multigpu-mpi-cuda
"$cmake3" -S /home/hanbo/workspace/LBM/runs/multigpu-opt-20261121/source-validcopy \
  -B "$trial/build" \
  -DAMReX_DIR="$deps/amrex-26.11-install-3d-mpi-cuda/lib/cmake/AMReX" \
  -DMPI_CXX_COMPILER="$mpi_prefix/bin/mpicxx" \
  -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_ARCHITECTURES=70 \
  -DCMAKE_CUDA_FLAGS_RELEASE='-O3 -DNDEBUG' \
  -DLBM_DIM=3 -DLBM_ENABLE_IBM=OFF -DLBM_TIMING=ON
"$cmake3" --build "$trial/build" --target lbm3d_tgv3d lbm3d_tgv3d_summary -j 8
```

构建后检查 `ldd "$trial/build/lbm3d_tgv3d"` 中的 `libmpi.so` 来自用户前缀，同时验证 `MPIX_Query_cuda_support()==1`；缺一项则不能将该构建称作 CUDA-aware 对照。建议用新 `mpicc` 编译以下最小探针：

```c
#include <mpi.h>
#include <mpi-ext.h>
#include <stdio.h>
int main(int argc, char **argv) {
    MPI_Init(&argc, &argv);
    printf("CUDA-aware MPI: %d\n", MPIX_Query_cuda_support());
    MPI_Finalize();
    return 0;
}
```

应显式使用 `"$mpi_prefix/bin/mpirun"`，并使运行时 `LD_LIBRARY_PATH` 指向用户前缀的 `lib`；不得把 CUDA `stubs` 目录放入 `LD_LIBRARY_PATH`。[Open MPI 官方文档](https://docs.open-mpi.org/en/main/tuning-apps/accelerators/cuda.html)提示 `smcuda` BTL 需显式选择，例如 `--mca pml ob1 --mca btl self,smcuda,tcp`；可加 `--mca btl_smcuda_cuda_ipc_verbose 100` 观察 IPC 选择。它还提示该 BTL 可能在 `MPI_Init` 分配 CUDA 资源，因此应在启动每个 MPI 进程前就用各自的 `CUDA_VISIBLE_DEVICES` 限定单张 GPU，而不是让所有进程共享同一可见设备列表。这需要一个读取 `OMPI_COMM_WORLD_LOCAL_RANK`、将其映射到物理 GPU 并 `exec` 求解器的短启动脚本；AMReX 在每进程只见一张 GPU 时选择设备 0。建议在本轮基线计时结束后编译，避免 CPU 编译负载污染计时。

## 验证与性能门槛

先用 1/2/4 GPU 的 10 步 TGV 输入做无 plotfile/checkpoint 的正确性和启动检查，再跑紧凑最终场统计；确认与原二进制的密度、速度、19 个分布函数分量统计一致。对新 MPI 构建单独完成 1/2/4 GPU 强扩展和每卡 256³ 弱扩展，各配置至少 3 次独立运行、100 步预热和 500 步同步计时、反序交错，保存命令、拓扑、二进制/输入/日志 SHA-256。每轮检查无全场文件。

强扩展效率定义为 `T1/(N*T_N)`（全局 256³），弱扩展效率定义为 `T1/T_N`（每 GPU 256³）。按**同一新构建**的 1 卡中位数计算，2 卡与 4 卡两种效率均需严格大于 90%，并通过数值检查；不能拿旧 MPI 的单卡时间当新 MPI 的分母。未达标时继续定位传输、GPU kernel 和同步开销，不把能力检查通过当作性能目标达成。

`nvidia-smi topo -p2p r/w` 显示 GPU 0↔1 和 2↔3 可 peer access，但跨 CPU socket 的组合为 `TNS`；`-p2p n` 全部为 `NS`（无 NVLink）。既有双卡映射 `0,2` 恰好不能 P2P。可先对照同 socket `0,1` 与跨 socket `0,2`，再测四卡；四卡必有跨 socket 消息，CUDA-aware MPI 可能对这些消息回退到主机路径。因此这个试验是识别收益，不预设会满足 90% 门槛。若内部 `smcuda` 不足，再评估独立构建带 CUDA 的 UCX；不能复用当前无 CUDA transport 的系统 UCX。
