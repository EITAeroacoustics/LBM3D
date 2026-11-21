# 上游来源与迁移记录

- iLBMReX 来源：当前仓库子模块提交 `a8c7c89ccac0c90c84f3ebbf6ad59ce94a38df95`。
- `Source/LBM`、`AMReXAdapter`、`Boundary`、`Utils` 的求解器代码来自该提交的 `iLBMReX/Source`；`Boundary/IBM/PitchingAirfoilGeometry.H` 来自 `iLBMReX/Examples/Pitching_airfoil/IBMUserDefinedGeometry.H`；`Examples/Common/main.cpp` 来自上游 `Source/main.cpp`。保留的上游许可正文见 `UPSTREAM_LICENSE`。
- 上游 `LICENSE` 文件写 MIT License，`README.md` 却写 BSD 3-Clause。两处表述不一致；本轮依照实际 `LICENSE` 保留原许可正文，后续对外分发前应向上游确认。
- AMReX 26.11 作为独立安装库链接，未复制或修改 AMReX 源码。

相对上游的 P1-07 结构改动：

1. 把 `Prob.H` 从库侧 `Kernels.H` 移除；`AmrCoreLBM` 接受 `ProblemInit` 主机回调，示例编译单元负责原有初始场 GPU 循环。
2. 把现有 pitching airfoil 的 `refinement_region`、`build_markers`、`marker_state` 原公式移入 IBM 模块。`pitching_airfoil` 是新的显式输入值；`user_defined`、`custom` 暂保留为同一内置模型的兼容别名，以运行现有示例输入。
3. 将载荷计算/输出和 plotfile/checkpoint 成员实现按职责移至 `Diagnostics/`，不改计算式和调用顺序。
4. 将上游对有值 `AMREX_PARTICLES` 的预处理判断改为存在性判断，适配 AMReX 26.11 定义的空宏。

本次迁移未改变碰撞、迁移、边界和力学数值公式。重组前后同条件数值与性能正式验收属于 P1-09；本阶段先验证 2D 普通算例、2D pitching airfoil 与 3D TGV 可链接同一求解器库并短程运行。
