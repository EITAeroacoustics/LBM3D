# P1-08 全部示例迁移与 IBM 回归

工作站使用 AMReX 26.11、Release、CUDA、单 MPI 进程与单张 V100。八个上游示例的初场和标准输入位于 `Examples/`，分别链接同一维度的 `lbm3d` 库；2D 六个、3D 两个目标均构建成功，并各自完成两步且正常退出。原始日志与流场保存在 `/home/hanbo/workspace/LBM/runs/p1-08-regression-with-motion/`，汇总见 [机器可读报告](examples-report.json)。

| 2D 示例 | 3D 示例 | 结果 |
|---|---|---|
| Cavity_flow、Couette_flow、Cylinder_flow、ForceValidation、Pitching_airfoil、Taylor_Green_Vortex | Sphere_flow、SquareDuct_flow | 8/8 构建与两步短程运行通过 |

IBM 专项对照使用单独构建的原始 iLBMReX，显式设置 `LBM_BASELINE_IBM=ON`；模块化版保持 IBM 开启。两边使用各自入库标准输入，运行时统一覆盖 `max_step=2`、`amr.plot_int=1`、`amr.regrid_int=-1`，比较步 0、1、2 全部 AMR 层的 `rho/ux/uy/uz` 和原有 `force.dat`。

| 算例 | 场值结果 | 载荷结果 |
|---|---|---|
| Pitching_airfoil | 3 个检查点、4 个场均逐位一致 | `force.dat` 字节一致 |
| Sphere_flow | 初场逐位一致；步 1 最大绝对差 `5.55e-16`，步 2 为 `8.88e-16`，均小于固定 `1e-14` 阈值 | `force.dat` 字节一致 |

球体原始二进制独立重复运行，步 1、2 的最大场值差分别为 `4.44e-16`、`8.88e-16`，与重组前后差异同量级。IBM 力散布使用 GPU 原子累加；因累加顺序可能变化，此处保存逐位不一致格点数，并对球体采用明确的最大绝对误差判据，不宣称球体流场逐位一致。翼型几何源码除头文件保护名外与上游相同；另外对两个标记点在时间 0、1、2 的六组位置和速度执行原始版与模块化版数值探针，输出完全相同，记录于 `examples-report.json` 的 `marker_motion`。

最初使用默认 `LBM_BASELINE_IBM=OFF` 的原始 TGV 基线构建做 IBM 对照时，载荷为零；该对照配置无效，未用于以上结论。有效的 IBM 原始版构建和日志位于工作站 `deps/p1-08-baseline-{pitching,sphere}`、`logs/p1-08-baseline-*-ibm-*`。重跑入口为 `Examples/run_regression.py`。
