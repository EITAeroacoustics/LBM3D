# 三维单层 D3Q19 固定方向性 halo 回归（2026-11-22）

## 当前实现

三维推进在碰撞后固定调用 `DirectionalHalo::Fill`，不再按周期性、IBM、GPU-aware MPI、team size 或运行开关选择普通 `FillBoundary`。输入边界明确要求 `amr.max_level=0` 和 `lbm3d.ndir=19`；给入多层或 D3Q27 配置会在推进前报错。碰撞前用于非周期物理边界和 IBM 的 `FillPatch` 逻辑保留。二维兼容构建继续使用其原通信路径。

方向性模块仍用 AMReX `getFB(IntVect(1), periodicity)` 标签确定几何与 rank，只交换 D3Q19 pull streaming 读取的分量。无 GPU-aware MPI 时在模块内用 pinned host buffer 暂存；team 本地标签按目标 FAB 所有者处理；重叠标签按段顺序执行。所有这些情况均不在三维推进层回退到普通 `FillBoundary`。

## 数值检查

旧版普通 halo 使用固定路径改动前的独立二进制并传 `lbm3d.directional_halo=0`；方管和球体基线来自提交 `861535f`，TGV 基线为此前全周期验收二进制。各次完整二进制校验值见原始 JSON。每个输入运行 10 步，脚本比较最终有效单元的内存摘要，检查新版日志 `active=1`、多卡 rank 0 实际发送值大于零，并确认无 plotfile/checkpoint。全部运行未写全场数据。

| 算例 | 1/2/4 卡结果 | 原始记录 |
| --- | --- | --- |
| 128³ 全周期 TGV | 23 分量均精确一致 | [JSON](directional-halo-fixed-tgv-periodic.json) |
| 混合周期方管，`user_2` 壁面 | 23 分量均精确一致 | [JSON](directional-halo-fixed-mixed-user2.json) |
| 混合周期方管，`user_1` 壁面 | 23 分量均精确一致 | [JSON](directional-halo-fixed-mixed-user1.json) |
| 三轴全非周期方管，`user_2` 壁面 | 23 分量均精确一致 | [JSON](directional-halo-fixed-all-nonperiodic.json) |
| 球体输入关闭 IBM | 23 分量均精确一致 | [JSON](directional-halo-fixed-sphere-no-ibm.json) |
| 单层 D3Q19 球体 IBM | 24 分量数值摘要最大绝对差分别为 `4.72e-17`、`2.66e-16`、`2.26e-16`，均小于约定的 `1e-12` | [JSON](directional-halo-fixed-sphere-ibm.json) |
| 普通 MPI（无 GPU-aware），混合周期方管 | 23 分量均精确一致 | [JSON](directional-halo-fixed-nonaware-mixed-user2.json) |

IBM 使用 GPU 原子力散布；同一旧版二进制重复运行时已有 23/24 个分量的位置指纹不同，四类数值摘要的最大绝对差为 `2.88e-17`。因此 IBM 行按数值摘要容差验收，保留指纹作为诊断，不宣称逐位一致。关闭 IBM 后，同一球体边界输入的两版结果重新达到精确一致。

使用 `amr.max_level=1` 和 `lbm3d.ndir=27` 的启动检查均在推进前得到明确错误，且没有全场输出。二维 CUDA＋IBM 配置的 `lbm3d_cavity` 构建通过，两步短程运行成功，未写全场。当前 AMReX 安装的 team size 为 1；team size 大于 1 和重叠标签的模块内处理已做代码审查，尚无专项运行结果。本轮仅验证通信与短程数值一致性，未重新测量强弱扩展性能。复跑输入和命令见 [`Benchmarks/DirectionalHalo/README.md`](../../Benchmarks/DirectionalHalo/README.md)。
