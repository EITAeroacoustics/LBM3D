# 单层方向性 halo 回归

所有输入均为三维单层 D3Q19，运行 10 步，关闭 plotfile 与 checkpoint。方管输入使用 8×32×32 网格和 16 个 FAB；球体输入使用 80×48×48 网格、IBM 和 12 个 FAB。

| 输入 | 格子 | 周期轴 | 物理边界与 IBM |
| --- | --- | --- | --- |
| `inputs_square_duct_mixed` | D3Q19 | x | y/z 的 `user_2` |
| `inputs_square_duct_mixed_user1` | D3Q19 | x | y/z 的 `user_1` |
| `inputs_square_duct_nonperiodic` | D3Q19 | 无 | x/y/z 的 `user_2` |
| `inputs_sphere_d3q19_ibm` | D3Q19 | y/z | x 出入口、球体 IBM |

3D CUDA 构建方管的 `lbm3d_square_duct_summary` 和球体的 `lbm3d_sphere_summary`。二者都在内存中汇总最终密度、速度、分布函数及存在时的 Level Set 场，不写全场。旧版普通 halo 二进制作为基线，新版固定方向性 halo 二进制作为被测版本；两个构建使用相同测试目标源码和编译选项。比较脚本在 1/2/4 卡上逐项比对最终场摘要，并确认新版方向性路径实际启用及多卡跨 rank 发送。方管命令：

```sh
python3 Benchmarks/TGV3D/compare_field_summary.py \
  OLD_BUILD/lbm3d_square_duct_summary NEW_BUILD/lbm3d_square_duct_summary \
  Benchmarks/DirectionalHalo/inputs_square_duct_mixed RUN_DIR REPORT.json \
  --baseline-option lbm3d.directional_halo=0 \
  --require-directional-halo \
  --mpirun /path/to/mpirun \
  --rank-wrapper Benchmarks/TGV3D/rank_gpu.py
```

旧版基线可取提交 `861535f`，其中 `lbm3d.directional_halo=0` 选择普通 `FillBoundary`；新版无此运行开关。依次替换输入文件复跑另外两组方管。球体需在两版均以 `LBM_ENABLE_IBM=ON` 构建，并在旧版构建中加入同一 `lbm3d_sphere_summary` 测试目标；复用上面的命令，将目标改为 `lbm3d_sphere_summary`、输入改为 `inputs_sphere_d3q19_ibm`，再加 `--expected-fields 24 --numeric-atol 1e-12`。球体的 24 条摘要包含 19 个分布函数和 1 个 Level Set 分量。现有 IBM 力耦合在同一旧版二进制的重复运行中已有浮点位差异；该选项比较四种数值摘要并保留位置指纹供诊断。去掉这两个选项并加 `--common-option ibm.use_cylinder=0 --common-option ibm.method=0`，可对无 IBM 的相同边界设置做严格 23 分量对照。按 MPI 安装情况补充 `--mpi-options` 和所需环境变量。比较的是最终有效单元字段；物理边界及 IBM 模型本身另由算例验证。

本轮实测结果和环境边界见[固定 D3Q19 方向性 halo 回归](../../Reports/Performance/directional-halo-fixed-d3q19.md)。
