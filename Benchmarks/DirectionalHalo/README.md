# 非周期方向性 halo 回归

三个输入均使用 D3Q19、单层 8×32×32 网格和 16 个 FAB，运行 10 步；plotfile 与 checkpoint 均关闭。

| 输入 | 周期轴 | 物理壁面 |
| --- | --- | --- |
| `inputs_square_duct_mixed` | x | y/z 的 `user_2` |
| `inputs_square_duct_mixed_user1` | x | y/z 的 `user_1` |
| `inputs_square_duct_nonperiodic` | 无 | x/y/z 的 `user_2` |

用 3D CUDA 构建 `lbm3d_square_duct_summary`。它在内存中汇总最终密度、速度和 19 个分布函数，不写全场。比较脚本在 1/2/4 卡上用同一二进制分别运行普通和方向性 halo，并检查优化路径实际启用及多卡跨 rank 发送：

```sh
python3 Benchmarks/TGV3D/compare_field_summary.py \
  BUILD/lbm3d_square_duct_summary BUILD/lbm3d_square_duct_summary \
  Benchmarks/DirectionalHalo/inputs_square_duct_mixed RUN_DIR REPORT.json \
  --baseline-option lbm3d.directional_halo=0 \
  --optimized-option lbm3d.directional_halo=1 \
  --require-directional-halo \
  --mpirun /path/to/mpirun \
  --rank-wrapper Benchmarks/TGV3D/rank_gpu.py
```

按 MPI 安装情况补充 `--mpi-options` 和 GPU-aware MPI 环境变量。依次替换输入文件重复运行。比较的是最终有效单元字段；物理壁面模型本身另由算例验证。
