# 方向性 halo 的非周期边界回归（2026-11-22）

## 改动与依据

从碰撞后方向性 halo 的启用条件中移除了 `geom[lev].isAllPeriodic()`。碰撞前仍沿用原条件：非周期算例通过 `FillPatchMesoscopic` 和 `FillPatchMacro` 填充物理边界。方向性 halo 仍使用 AMReX 的 `getFB(IntVect(1), geom.periodicity())` 标签；非周期轴上，只有可从有效网格单元取得数据的 FAB ghost 会进入标签，物理域外没有来源的 ghost 保留给边界条件处理。D3Q19 的方向筛选只取 pull streaming 实际读取的分量。

其他启用条件保持原样：单层、D3Q19、无圆柱 IBM、CUDA-aware MPI、AMReX team size 为 1，且标签重叠检查通过。此改动不改变 `MultiFab` 布局和默认 `max_grid_size=64`、`blocking_factor=8`。

## 数值回归

在 4×V100 工作站上，使用 AMReX 26.11、CUDA-aware Open MPI 4.1.8 和 UCX 1.21.1。新增 `lbm3d_square_duct_summary` 目标复用方管初始化和最终场内存摘要；三个输入均为单层 D3Q19、8×32×32、`max_grid_size=8`，产生 16 个 FAB，运行 10 步。`max_grid_size=8` 只用于此小规模通信回归，不修改项目默认值。

同一个二进制分别传 `lbm3d.directional_halo=0/1`，在 1/2/4 卡逐项比较最终密度、三个速度和 19 个分布函数的求和、二范数、极值及位置敏感整数指纹。脚本还要求启用运行打印 `active=1`，多卡 rank 0 实际发送值大于零，并检查运行目录无 plotfile/checkpoint。

| 输入和物理边界 | 1 卡 | 2 卡 | 4 卡 | rank 0 发送值（2/4 卡） |
| --- | --- | --- | --- | ---: |
| [x 周期、y/z `user_2`](directional-halo-nonperiodic-mixed-user2.json) | 23/23 相同 | 23/23 相同 | 23/23 相同 | 1392 / 1384 |
| [x 周期、y/z `user_1`](directional-halo-nonperiodic-mixed-user1.json) | 23/23 相同 | 23/23 相同 | 23/23 相同 | 1392 / 1384 |
| [三轴全非周期、`user_2`](directional-halo-nonperiodic-all-user2.json) | 23/23 相同 | 23/23 相同 | 23/23 相同 | 1328 / 1320 |

三组运行均无全场输出。二进制 SHA-256：`3343ca6cdafa41a6c847d62865f265b8b8d200a3dde0ae387095ed2eb2a638c6`。原始 JSON 保存命令、输入及二进制校验值、每次日志路径与校验值、各分量摘要和通信路径检查结果。复跑入口和输入说明见 [`Benchmarks/DirectionalHalo/README.md`](../../Benchmarks/DirectionalHalo/README.md)。

本回归证明这三组算例的方向性 halo 与普通 `FillBoundary` 最终场一致，不单独验证物理壁面模型，也未测量非周期算例的加速比。此前全周期 TGV 的扩展性能记录仍见 [原报告](directional-halo-results.md)。
