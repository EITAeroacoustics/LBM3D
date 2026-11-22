# 宏观场直读与原位 ghost 填充（2026-11-22）

推进中仍在每步流移后计算并保存 `rho, u, v, w`，供下一步 BGK 碰撞使用。碰撞只遍历有效单元，现直接读取 `macro_old`；删除推进函数中的 `smSborder` 分配、有效区复制和整场 FillPatch。仅在 marker IBM 实际执行时，对 `macro_old` 的前四个分量原位调用 `FillPatchMacro`，为速度插值提供当前 ghost。分布函数的 `sfSborder` 和方向性 halo 保持原有路径。

## 验证

在 4×V100 工作站用相同源码和编译选项分别构造修改前后两个隔离构建；唯一的代码差异是上述宏观场路径。两版均为 AMReX 26.11、Release、CUDA `sm_70`、`LBM_ENABLE_IBM=ON`、Open MPI 4.1.8 + UCX。CMake MPI 头路径和二进制 `ldd libmpi.so.40` 都指向 `/home/hanbo/workspace/LBM/deps/openmpi-4.1.8-ucx-cuda`。各输入运行 10 步，1/2/4 卡，禁用 plotfile 和 checkpoint，检查末步紧凑场摘要及有限值。

| 案例 | 末场摘要对照 |
| --- | --- |
| [TGV 128³](macro-direct-tgv-20261122.json) | 1/2/4 卡的 23 项摘要逐项一致 |
| [混合周期方管](macro-direct-duct-mixed-20261122.json) | 1/2/4 卡的 23 项摘要逐项一致 |
| [`user_1` 壁面方管](macro-direct-duct-user1-20261122.json) | 1/2/4 卡的 23 项摘要逐项一致 |
| [球体 marker IBM](macro-direct-sphere-20261122.json) | 1/2/4 卡的 24 项摘要均通过 `1e-12` 容差；最大绝对差分别为 `2.20e-17`、`2.20e-16`、`9.53e-17` |

球体的摘要指纹并非逐项相同；[基线二进制自身重复运行](macro-direct-sphere-repeat-20261122.json)也有浮点差，1/2/4 卡最大绝对差分别为 `4.62e-17`、`1.06e-16`、`8.81e-17`。所有运行正常完成，未写入全场数据。

这次改动省去一个含 `nmac=6` 分量及 ghost 的整场暂存 `MultiFab`；仍保留 `macro_old/new` 的每步宏观量计算和存储。此前单层全周期 TGV 的独立原型已测得约 6% 的四卡步时收益，见[暂存复制实验](halo-wait-and-staging-tests-20261122.md)；本次未重测性能。当前求解器仍限制 `amr.max_level=0`，将来启用分层局部加密后，需单独验证原位宏观 ghost 填充与粗细界面时间插值。
