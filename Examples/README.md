# 上游示例兼容集

本目录的八个 `Prob.H` 与 `inputs` 来自 iLBMReX 提交 `a8c7c89ccac0c90c84f3ebbf6ad59ce94a38df95` 的对应示例，原许可见 `../Source/UPSTREAM_LICENSE`。唯一输入改动是 `Pitching_airfoil/inputs` 显式使用库内置的 `ibm.marker_geometry=pitching_airfoil`；旧的 `user_defined` 值仍可运行。原上游 `IBMUserDefinedGeometry.H` 的公式已移入 `Source/Boundary/IBM/PitchingAirfoilGeometry.H`，示例无须包含它。

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

`run_regression.py` 可一次运行八个示例，并在两个额外原始基线构建启用 `-DLBM_BASELINE_IBM=ON` 后，对 `Pitching_airfoil`、`Sphere_flow` 的步 0/1/2 多层流场和 `force.dat` 做对照。翼型要求场值与载荷逐位一致；球体的 IBM 力散布含 GPU 原子累加，原始版重复运行已出现约 `1e-15` 的场值末位差异，因此球体场值采用固定 `1e-14` 最大绝对误差阈值，同时保存逐位不一致格点数和原始版重复运行结果；载荷文件仍要求完全一致。命令行参数见 `python3 Examples/run_regression.py --help`；结果写入指定工作目录的 `examples-report.json`。
