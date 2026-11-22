# 上游示例兼容集

本目录的八个 `Prob.H` 与初始 `inputs` 来自 iLBMReX 提交 `a8c7c89ccac0c90c84f3ebbf6ad59ce94a38df95` 的对应示例，原许可见 `../Source/UPSTREAM_LICENSE`。`Pitching_airfoil/inputs` 显式使用库内置的 `ibm.marker_geometry=pitching_airfoil`；旧的 `user_defined` 值仍可运行。原上游 `IBMUserDefinedGeometry.H` 的公式已移入 `Source/Boundary/IBM/PitchingAirfoilGeometry.H`。后续三维架构固定为单层 D3Q19，`Sphere_flow/inputs` 因此改为单层和 D3Q19；原始多层 D3Q27 配置仍可从上游提交追溯。

| 维度 | 示例目录 | 构建目标 |
|---|---|---|
| 2D | `Cavity_flow` | `lbm3d_cavity` |
| 2D | `Couette_flow` | `lbm3d_couette` |
| 2D | `Cylinder_flow` | `lbm3d_cylinder` |
| 2D | `ForceValidation` | `lbm3d_force_validation` |
| 2D | `Pitching_airfoil` | `lbm3d_pitching_airfoil` |
| 2D | `Taylor_Green_Vortex` | `lbm3d_taylor_green_2d` |
| 3D | `Sphere_flow` | `lbm3d_sphere` |
| 3D | `SquareDuct_flow` | `lbm3d_square_duct` |

2D 和 3D 各配置一次根目录 CMake。各目标共享 `lbm3d` 库，案例初场通过 `Common/ProblemInit.cpp` 从其 `Prob.H` 编译。`Taylor_Green_Vortex` 是原上游二维公式，仅作兼容检查；第一阶段的三维物理 benchmark 是 `Benchmarks/TGV3D`。

短程运行使用各目录的 `inputs`，命令行覆盖 `max_step=2 amr.plot_int=-1 amr.chk_int=-1`，在独立工作目录保存日志和载荷文件。完整算例输入保持上游参数，不把短程测试覆盖写回案例文件。

`run_regression.py` 是第一阶段迁移时的历史验收脚本，当时对 `Pitching_airfoil`、原始多层 `Sphere_flow` 的流场和 `force.dat` 做对照；球体 IBM 力散布含 GPU 原子累加，旧版重复运行已有浮点末位差异。该脚本会写出全场数据，不用于第一阶段之后的新测试。当前单层 D3Q19 的无全场回归入口见 [`Benchmarks/DirectionalHalo/README.md`](../Benchmarks/DirectionalHalo/README.md)。
