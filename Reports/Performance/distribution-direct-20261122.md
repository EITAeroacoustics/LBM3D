# 分布函数异地碰撞与省整场复制（2026-11-22）

碰撞现从 `f_old` 有效单元读取、向 `sfSborder` 有效单元写入，不再复制 D3Q19 分布函数有效区。全周期单层路径直接碰撞，然后进行单层方向性 halo。非周期或细层路径先在 `f_old` 原位 FillPatch 旧时刻 ghost，仅把第一层 ghost 复制到 `sfSborder`；碰撞后同层方向性 halo 与已有物理边界处理继续执行。`sfSborder` 作为碰撞后场仍需保留。

## 数值回归

在 4×V100 工作站冻结已采用宏观场直读的源码作为基线，两版均以 AMReX 26.11、Release、CUDA `sm_70`、`LBM_ENABLE_IBM=ON`、Open MPI 4.1.8 + UCX 构建；二进制均链接相同的 UCX 版 `libmpi.so.40`。每种输入运行 10 步，禁用 plotfile 和 checkpoint，比较 1/2/4 卡的末场紧凑摘要及有限值。

| 案例 | 对照结果 |
| --- | --- |
| [TGV 128³](distribution-direct-tgv-20261122.json) | 23 项摘要在 1/2/4 卡逐项一致 |
| [混合周期方管](distribution-direct-duct-mixed-20261122.json) | 23 项摘要在 1/2/4 卡逐项一致 |
| [`user_1` 壁面方管](distribution-direct-duct-user1-20261122.json) | 23 项摘要在 1/2/4 卡逐项一致 |
| [球体 marker IBM](distribution-direct-sphere-20261122.json) | 24 项摘要在 1/2/4 卡均通过 `1e-12` 容差；最大绝对差分别为 `6.25e-17`、`1.87e-16`、`1.81e-16` |

球体 IBM 的指纹未逐项相同；该案例的[基线自身重复运行](macro-direct-sphere-repeat-20261122.json)也有同量级浮点差。所有运行正常完成，未写全场数据。这次方管与球体的对照均实际执行了新的 ghost-only 路径。

## TVG 单轮性能复测

固定 `max_grid_size=64`、`blocking_factor=8`，预热 100 步、计时 500 步，强扩展固定全局 256³，弱扩展固定每卡 256³。相同绑定和输入下，基线与改动版各测一轮；所有测试关闭全场输出。

| 测试 | 基线 1/2/4 卡 ms/步 | 改动版 1/2/4 卡 ms/步 | 四卡效率 |
| --- | --- | --- | --- |
| [强扩展基线](distribution-direct-strong-baseline-20261122.json) / [改动版](distribution-direct-strong-optimized-20261122.json) | 39.313 / 19.833 / 10.894 | 31.569 / 15.948 / 8.946 | 88.22% |
| [弱扩展基线](distribution-direct-weak-baseline-20261122.json) / [改动版](distribution-direct-weak-optimized-20261122.json) | 39.317 / 39.482 / 40.607 | 31.565 / 31.692 / 32.774 | 96.31% |

相对本轮宏观场直读基线，改动版四卡强扩展步时降低 17.88%，四卡弱扩展步时降低 19.29%。四卡强扩展效率低于项目的 90% 门槛；该单轮测量只用于确认实施效果，正式性能验收仍按三轮方案执行。[此前 B 原型的三轮测试](halo-wait-and-staging-tests-20261122.md)同样显示约 18% 的额外四卡步时收益及约 89% 的强扩展效率。

当前求解器限制 `amr.max_level=0`。细层的原位 FillPatch 与粗细界面 ghost 重建保留在代码中，启用局部加密后仍须做专门数值与性能验收。
