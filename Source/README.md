# LBM3D 求解器模块

本目录构建为一个 `lbm3d` 静态库，按职责分布源码；2D 和 3D CUDA 分别配置、链接相应维度的独立 AMReX 安装。AMReX 仍是独立上游依赖。

| 目录 | 职责 |
|---|---|
| `LBM/` | D2Q9/D3Q19 等格子、平衡态、碰撞、迁移、宏观量及强迫项核函数 |
| `AMReXAdapter/` | `AmrCoreLBM`、层级场、FillPatch、时间推进、网格标记和 MPI/GPU 调度 |
| `Boundary/BC/` | 宏观量与分布函数边界填充 |
| `Boundary/IBM/` | 标记点 IBM、力场、运动几何；现有 pitching airfoil 公式在此作为内置实现 |
| `Boundary/LevelSet/` | Level Set 场与几何处理 |
| `Diagnostics/` | 载荷诊断、plotfile、checkpoint 相关成员实现 |
| `Utils/` | 上游调试辅助函数 |

示例只调用 `AmrCoreLBM` 构造/运行入口，并提供 `ProblemInit` 主机侧初始化函数。`Examples/Common/ProblemInit.cpp` 在各示例目标中编译并包含对应 `Prob.H`，在该编译单元启动原有 GPU 初始化核函数。求解器库不包含示例头文件，也不为每个示例重新编译求解器源码。`AmrCoreLBM` 的 CUDA 辅助成员保留上游可见性，以满足现有 nvcc 扩展设备 lambda 限制。

AMReXAdapter 组织 LBM、边界和诊断代码；LBM 核函数不依赖算例或层级管理。诊断成员实现虽然放在独立目录，仍是同一 `AmrCoreLBM` 类的函数，当前只生成一个库目标，不形成目标级循环依赖。完整来源、许可和迁移改动见 `UPSTREAM.md`。

公开入口是 `AMReXAdapter/AmrCoreLBM.H` 的 `AmrCoreLBM` 和 `AMReXAdapter/ProblemInit.H` 的 `ProblemInit`。`Boundary/IBM/MarkerIBParams.H` 供库内网格适配和 IBM 实现共享；`LBM/`、`Boundary/BC/`、`Diagnostics/`、`Utils/` 的头文件保持库内使用。依赖顺序为示例 → `lbm3d` → AMReX；库内由 AMReXAdapter 调用 LBM、Boundary、Diagnostics。各示例仅编译 `Examples/Common/main.cpp` 与各自的 `ProblemInit.cpp`，核心库源码只编译一次。

示例构建（使用对应维度的 AMReX 安装路径）：

```sh
cmake -S . -B build/lbm3d-3d -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc \
  -DCMAKE_PREFIX_PATH=/path/to/amrex-3d -DLBM_DIM=3
cmake --build build/lbm3d-3d --parallel 4
```

2D 配置另选 `-DLBM_DIM=2` 与 2D AMReX 安装路径。八个上游示例的 `Prob.H` 和 `inputs` 已复制到 `Examples/`；求解器库不读取上游子模块。示例来源见 `Examples/README.md`。

连续运行验收可设置 `lbm3d.wall_time_limit_s=600`，求解器在达到墙钟时间后的首个完整步正常结束，并按 `amr.plot_int` 设置写出末步流场。不设置该参数时沿用 `max_step` 与 `stop_time` 的原始停止条件。
