# 原始 iLBMReX 外部 AMReX 基线

此目录只提供构建入口。`iLBMReX/Source` 中的数值计算代码不作修改；CMake 将它直接编入基线可执行文件，并链接独立安装的 AMReX。唯一兼容处理是把上游 IBM 文件中 `AMREX_PARTICLES` 的数值式预处理判断改为存在性判断，生成在构建目录的临时副本中。AMReX 26.11 将该宏定义为空值；此处理不改变求解公式。

需使用 CMake 3.25 及以上、CUDA 工具链和已安装的对应维度 AMReX。示例：

```sh
cmake -S Baseline -B build/baseline-3d \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc \
  -DCMAKE_PREFIX_PATH=/path/to/amrex-3d \
  -DLBM_DIM=3 -DLBM_CASE=TGV3D
cmake --build build/baseline-3d --parallel 4
```

2D 将 `LBM_DIM=2`、`LBM_CASE=Cavity_flow` 和 AMReX 安装前缀切换为 2D 配置。`LBM_CASE` 还可指定 `iLBMReX/Examples` 下具有 `Prob.H` 的其他示例。TGV3D 配置同时编译 `tgv3d_analyze`，用于读取基准 plotfile。

原始 TGV 性能基线保持默认 `LBM_BASELINE_IBM=OFF`。对 `Pitching_airfoil`、`Sphere_flow` 等 IBM 算例做重组前后回归时，须在独立构建目录显式使用 `-DLBM_BASELINE_IBM=ON`；否则原始求解器的推进阶段关闭 IBM 耦合，载荷对照无效。

强扩展测量单独配置 `-DLBM_BASELINE_TIMING=ON`。`make_timed_core.py` 将原始 `AmrCoreLBM.cpp` 复制到构建目录，仅在第 101 步开始前、第 600 步结束后添加 GPU 同步、MPI 计时归约与打印。数值计算路径和循环顺序不变。计时段包含原始求解器每步的质量归约和日志输出；强扩展输入关闭 plotfile/checkpoint，因此不含磁盘流场写出。`Benchmarks/TGV3D/run_strong.py` 保存三个重复测量及二进制、输入校验值。

工作站本轮固定的 AMReX 配置：26.11，CUDA，double，MPI，particles，`CMAKE_CUDA_ARCHITECTURES=70`，`AMReX_CUDA_FASTMATH=OFF`；2D/3D 分开安装。源码、二进制和运行结果各自独立存放。构建日志需随基线报告保存。
