# 上游来源与迁移记录

- iLBMReX 来源：当前仓库子模块提交 `a8c7c89ccac0c90c84f3ebbf6ad59ce94a38df95`。
- `Source/LBM`、`AMReXAdapter`、`Boundary`、`Utils` 的求解器代码源自该提交的 `iLBMReX/Source`；`Examples/Common/main.cpp` 源自上游 `Source/main.cpp`。当前 LBM3D 只保留三维求解代码；上游许可正文见 `UPSTREAM_LICENSE`。
- 上游 `LICENSE` 文件写 MIT License，`README.md` 却写 BSD 3-Clause。两处表述不一致；本轮依照实际 `LICENSE` 保留原许可正文，后续对外分发前应向上游确认。
- AMReX 26.11 作为独立安装库链接，未复制或修改 AMReX 源码。

相对上游的 P1-07 结构改动：

1. 把 `Prob.H` 从库侧 `Kernels.H` 移除；`AmrCoreLBM` 接受 `ProblemInit` 主机回调，示例编译单元负责原有初始场 GPU 循环。
2. P1 曾为二维机翼迁入内置几何与输入别名；这部分已随三维专用路线从当前代码移除，历史实现可从 P1 验收提交追溯。
3. 将载荷计算/输出和 plotfile/checkpoint 成员实现按职责移至 `Diagnostics/`，不改计算式和调用顺序。
4. 将上游对有值 `AMREX_PARTICLES` 的预处理判断改为存在性判断，适配 AMReX 26.11 定义的空宏。
5. P1-11 增加可选 `lbm3d.wall_time_limit_s`，仅在完成当前整步后停止连续运行验收；未设置时不改变原有步数和物理时间停止逻辑。

P1 迁移时未改变碰撞、迁移、边界和力学数值公式，重组前后同条件验收见 P1-09 的历史报告。当前构建与测试只使用三维 D3Q19 案例。
