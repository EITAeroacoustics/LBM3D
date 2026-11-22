# LBM3D 求解器模块

本目录构建为一个仅支持三维 CUDA 的 `lbm3d` 静态库，按职责分布源码并链接独立安装的三维 AMReX。

| 目录 | 职责 |
|---|---|
| `LBM/` | D3Q19 格子、平衡态、碰撞、迁移、宏观量及强迫项核函数 |
| `AMReXAdapter/` | `AmrCoreLBM`、层级场、FillPatch、时间推进、网格标记和 MPI/GPU 调度 |
| `Boundary/BC/` | 宏观量与分布函数边界填充 |
| `Boundary/IBM/` | 三维标记点 IBM、力场和静止球体几何 |
| `Boundary/LevelSet/` | Level Set 场与几何处理 |
| `Diagnostics/` | 载荷诊断、plotfile、checkpoint 相关成员实现 |
| `Utils/` | 上游调试辅助函数 |

示例只调用 `AmrCoreLBM` 构造/运行入口，并提供 `ProblemInit` 主机侧初始化函数。`Examples/Common/ProblemInit.cpp` 在各示例目标中编译并包含对应 `Prob.H`，在该编译单元启动原有 GPU 初始化核函数。求解器库不包含示例头文件，也不为每个示例重新编译求解器源码。`AmrCoreLBM` 的 CUDA 辅助成员保留上游可见性，以满足现有 nvcc 扩展设备 lambda 限制。

AMReXAdapter 组织 LBM、边界和诊断代码；LBM 核函数不依赖算例或层级管理。诊断成员实现虽然放在独立目录，仍是同一 `AmrCoreLBM` 类的函数，当前只生成一个库目标，不形成目标级循环依赖。完整来源、许可和迁移改动见 `UPSTREAM.md`。

`AMReXAdapter/DirectionalHalo` 是三维单层 D3Q19 求解的固定通信路径，只交换 pull streaming 实际读取的单层分布函数 ghost 分量。几何相交、周期映射和 rank 归属来自 AMReX 的 FillBoundary 元数据；非周期物理边界仍由 FillPatch 和边界条件处理。方向性 halo 不因 IBM、周期性、MPI 传输方式或 AMReX team size 切换为普通 `FillBoundary`，也不提供运行时开关。`lbm3d.mass_check_interval` 默认每 100 步做一次全局质量检查，首步和末步始终检查；设为 1 可逐步检查。

推进每步从新分布函数计算并保存宏观量，下一步碰撞直接读取 `macro_old` 的有效单元。IBM 在需要速度插值时原位填充 `macro_old` 的宏观 ghost；推进不创建宏观场暂存副本。碰撞从 `f_old` 的有效单元读取并向 `sfSborder` 写入，不复制分布函数有效区。非周期物理边界或未来粗细界面的旧时刻分布函数 ghost 在 `f_old` 原位填充，再只复制流移所需的单层 ghost；碰撞后的同层 ghost 仍由方向性 halo 交换。

公开入口是 `AMReXAdapter/AmrCoreLBM.H` 的 `AmrCoreLBM` 和 `AMReXAdapter/ProblemInit.H` 的 `ProblemInit`。`Boundary/IBM/MarkerIBParams.H` 供库内网格适配和 IBM 实现共享；`LBM/`、`Boundary/BC/`、`Diagnostics/`、`Utils/` 的头文件保持库内使用。依赖顺序为示例 → `lbm3d` → AMReX；库内由 AMReXAdapter 调用 LBM、Boundary、Diagnostics。各示例仅编译 `Examples/Common/main.cpp` 与各自的 `ProblemInit.cpp`，核心库源码只编译一次。

三维 CUDA 构建：

```sh
cmake -S . -B build/lbm3d-3d -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc \
  -DCMAKE_PREFIX_PATH=/path/to/amrex-3d
cmake --build build/lbm3d-3d --parallel 4
```

两个三维示例的 `Prob.H` 和 `inputs` 位于 `Examples/`；求解器库不读取上游子模块。示例来源见 `Examples/README.md`，TGV3D 基准见 `Benchmarks/TGV3D/README.md`。

连续运行验收可设置 `lbm3d.wall_time_limit_s=600`，求解器在达到墙钟时间后的首个完整步正常结束，并按 `amr.plot_int` 设置写出末步流场。不设置该参数时沿用 `max_step` 与 `stop_time` 的原始停止条件。
