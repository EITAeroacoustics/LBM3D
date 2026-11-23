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

示例只调用 `AmrCoreLBM` 构造/运行入口，并提供 `ProblemInit` 主机侧初始化函数。通用示例用 `Examples/Common/ProblemInit.cpp`；TGV 容量案例用 `Benchmarks/TGV3D/ProblemInit.cpp` 初始化四个基本宏观量，额外派生量按需计算。求解器库不包含示例头文件，也不为每个示例重新编译求解器源码。`AmrCoreLBM` 的 CUDA 辅助成员保留上游可见性，以满足现有 nvcc 扩展设备 lambda 限制。

AMReXAdapter 组织 LBM、边界和诊断代码；LBM 核函数不依赖算例或层级管理。诊断成员实现虽然放在独立目录，仍是同一 `AmrCoreLBM` 类的函数，当前只生成一个库目标，不形成目标级循环依赖。完整来源、许可和迁移改动见 `UPSTREAM.md`。

`AMReXAdapter/DirectionalHalo` 是三维单层 D3Q19 求解的固定通信路径，只交换 pull streaming 实际读取的单层分布函数 ghost 分量。几何相交、周期映射和 rank 归属来自 AMReX 的 FillBoundary 元数据；非周期物理边界仍由 FillPatch 和边界条件处理。方向性 halo 不因 IBM、周期性、MPI 传输方式或 AMReX team size 切换为普通 `FillBoundary`，也不提供运行时开关。`lbm3d.mass_check_interval` 默认每 100 步做一次全局质量检查，首步和末步始终检查；设为 1 可逐步检查。

推进每步从新分布函数计算并保存密度与速度，下一步碰撞直接读取旧宏观场的有效单元。P1 双缓冲路径向 `sfSborder` 写入碰撞结果，不复制分布函数有效区；当前第二阶段的周期单层 TGV 路径试验在 `f_old` 原位碰撞并继续使用方向性 halo，尚待完整精度与容量验收。非周期物理边界或未来粗细界面的旧时刻 ghost 仍须保持正确时间语义。IBM 所需的宏观 ghost 按需在原场填充；推进不创建宏观场暂存副本。

公开入口是 `AMReXAdapter/AmrCoreLBM.H` 的 `AmrCoreLBM` 和 `AMReXAdapter/ProblemInit.H` 的 `ProblemInit`。`Boundary/IBM/MarkerIBParams.H` 供库内网格适配和 IBM 实现共享；`LBM/`、`Boundary/BC/`、`Diagnostics/`、`Utils/` 的头文件保持库内使用。依赖顺序为示例 → `lbm3d` → AMReX；库内由 AMReXAdapter 调用 LBM、Boundary、Diagnostics。各示例仅编译 `Examples/Common/main.cpp` 与各自的 `ProblemInit.cpp`，核心库源码只编译一次。

三维 CUDA 构建：

```sh
cmake -S . -B build/lbm3d-3d -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc \
  -DCMAKE_PREFIX_PATH=/path/to/amrex-3d
cmake --build build/lbm3d-3d --parallel 4
```

物理示例的 `Prob.H` 和 `inputs` 位于 `Examples/`，TGV3D 基准位于 `Benchmarks/TGV3D/`；求解器库不读取上游子模块。示例来源见 `Examples/README.md`，TGV3D 基准见 `Benchmarks/TGV3D/README.md`。

连续运行验收可设置 `lbm3d.wall_time_limit_s=600`，求解器在达到墙钟时间后的首个完整步正常结束，并按 `amr.plot_int` 设置写出末步流场。不设置该参数时沿用 `max_step` 与 `stop_time` 的原始停止条件。
