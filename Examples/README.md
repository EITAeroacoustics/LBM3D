# 三维示例

`Sphere_flow` 和 `SquareDuct_flow` 的初始场与输入源自 iLBMReX 提交 `a8c7c89ccac0c90c84f3ebbf6ad59ce94a38df95` 的对应示例，原许可见 `../Source/UPSTREAM_LICENSE`。当前输入统一使用三维 D3Q19；三维 TGV benchmark 位于 `../Benchmarks/TGV3D/`。

| 示例目录 | 构建目标 |
|---|---|
| `Sphere_flow` | `lbm3d_sphere` |
| `SquareDuct_flow` | `lbm3d_square_duct` |

两个目标共享根目录 CMake 构建的 `lbm3d` 库，案例初场通过 `Common/ProblemInit.cpp` 从各自 `Prob.H` 编译。

短程运行使用各目录的 `inputs`，命令行覆盖 `max_step=2 amr.plot_int=-1 amr.chk_int=-1`，在独立工作目录保存日志和载荷文件；短程参数不写回仓库案例文件。

`run_regression.py` 对两个三维示例执行无全场输出的短程回归；方向性 halo 的数值对照见 [`Benchmarks/DirectionalHalo/README.md`](../Benchmarks/DirectionalHalo/README.md)。P1 当时的示例迁移与二维兼容结果保存在 [`Reports/P1/examples.md`](../Reports/P1/examples.md) 对应的验收提交中，不列入当前回归。
