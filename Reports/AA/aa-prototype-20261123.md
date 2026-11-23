# 单缓冲 AA TGV 原型验证（2026-11-23）

隔离分支 `codex/lbm3d-aa-experiment`，提交 `0879859190f10fcc248a93e4a022aec19a51b38c`。这是一个独立的 TGV 验证程序；主求解器的默认推进路径仍是 P1 双缓冲实现。原型使用双精度、D3Q19、原二阶平衡态和 BGK 公式、一份 19 分量 `MultiFab`（一层 ghost）及一份 4 分量宏观场（无 ghost）。AMReX 26.11、CUDA 12.2、V100-SXM2-32GB；无 plotfile 或 checkpoint。AA 奇偶访问与单数组并行安全性的依据见 [Kummerländer 等，2023](https://onlinelibrary.wiley.com/doi/full/10.1002/cpe.7509)和 [Latt 等，2021](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0250306)。

## 固定构建与记录

远端目录 `/home/hanbo/workspace/LBM/deps/lbm3d-aa-experiment-20261123`，以下用 `$R` 表示。构建以 `AMReX_DIR=$R/../amrex-26.11-install-3d-ucx-cuda/lib/cmake/AMReX`、`CMAKE_CUDA_ARCHITECTURES=70`、Release、`LBM_ENABLE_IBM=OFF` 配置。两个可执行文件的 SHA-256：

| 可执行文件 | SHA-256 |
|---|---|
| `$R/build/lbm3d_aa_tgv3d` | `b2955a7746ed4cd7d50d2db92dc0d840057b1af3e239b08db88468718096e58a` |
| `$R/build/lbm3d_tgv3d_summary`（P1 默认推进对照） | `2598b152c3d8b979cbdaf6be734d5db23d4b8d2c7e0ce275a23ec55d78d2319f` |

`inputs_physics_64` 与 `inputs_physics_128` 的 SHA-256 分别为 `cb92599365b352bc5daf02d2b1d4320048b0da1069a80224c169312a3b34b1f6`、`0ab865aae8bd14c569d7fdeda4187529aa8e4cfb048ff4a554229572aa5ffd75`。所有运行均显式传 `amr.plot_int=-1 amr.chk_int=-1`；检查 `$R/runs` 下无 `plt*`、`chk*`。

## 无全场文件的 TGV 物理检查

运行示例：

```sh
R=/home/hanbo/workspace/LBM/deps/lbm3d-aa-experiment-20261123
CUDA_VISIBLE_DEVICES=0 "$R/build/lbm3d_aa_tgv3d" \
  "$R/source/Benchmarks/TGV3D/inputs_physics_64" \
  amr.plot_int=-1 amr.chk_int=-1 aa.final_summary=0 \
  'aa.diagnostic_steps=0 1 32 64'
```

128³ 的相同运行改用 `inputs_physics_128` 和 `aa.diagnostic_steps=0 1 64 128`。`TGV_METRICS` 在指定步完成后立即从驻留场归约，包含分布函数最小值和非有限值计数。

| 网格 | 物理时间 | 步数 | 平均密度 | 平均动能 | 初场最大误差 | 非有限值 |
|---:|---:|---:|---:|---:|---:|---:|
| 64³ | 0 | 0 | 1 | 5.0000000000000009e-5 | 1.11e-16 | 0 |
| 64³ | 32 | 32 | 0.99999999999999734 | 4.4547710229518649e-5 | — | 0 |
| 64³ | 64 | 64 | 0.99999999999999467 | 3.9853942028932507e-5 | — | 0 |
| 128³ | 0 | 0 | 1 | 5.0000000000000009e-5 | 2.22e-16 | 0 |
| 128³ | 32 | 64 | 0.99999999999999578 | 4.4718464865765112e-5 | — | 0 |
| 128³ | 64 | 128 | 0.9999999999999919 | 4.0014810964245742e-5 | — | 0 |

两档均满足 P1 的初场误差、相对质量漂移 `1e-8`、动能严格衰减、两网格动能差 `5%` 和有限值条件；每个检查点 `min_rho>0`、`min_f>0`。t=32、64 的动能与 [P1 冻结记录](../P1/physics.md)在约 `1e-18` 至 `1e-17` 内一致。日志：`$R/runs/aa-physics-{64,128}/run.log`，SHA-256 分别为 `3458e783bf242837d709bc6550e47d15ef2d4ff1a812190de894f83eb603ce2d`、`24dcda7d4e9b16077f9d14bc6ed5f6a6f6c9e4e5468bdd7fd6f76ef81f40214a`。

## 定点比较与双卡方向性 halo

在 `aa.print_probes=1` 下，AA 与 P1 对照各输出 8 个预定全局坐标处的 4 个宏观量和 19 个物理分布函数，共 184 个值。坐标覆盖周期角点、盒内点和 FAB 分界前后；AA 在翻转奇偶步按逻辑分布函数读取。比较最大绝对差：

| 配置 | 步数 | 最大绝对差 | 逐位相同探针 |
|---|---:|---:|---:|
| 64³，单卡，1 FAB | 2 | 2.22e-16 | 156/184 |
| 128³，单卡，8 FAB | 10 | 2.22e-16 | 71/184 |
| 64³，双卡，`max_grid_size=32`、8 FAB | 10 | 2.22e-16 | 23/184 |

双卡采用 GPU 0、2，一进程一 GPU，Open MPI 4.1.8 + UCX 1.21.1，`UCX_TLS=self,sm,cuda_copy`，`mpirun --mca pml ucx --mca pml_ucx_tls any --mca btl ^uct --map-by ppr:1:numa --bind-to numa -np 2`，通过 `rank_gpu.py` 在 `MPI_Init` 前选卡。AA rank 0 单层方向性 halo 的 send/recv 各 40,960 个值；两版进程均正常退出，UCX 日志无 `failed` 或 `unrecoverable`。相应日志位于 `$R/runs/{aa,base}64-2-probes/`、`$R/runs/{aa,base}128-10-probes/`、`$R/runs/{aa,base}64-10-mpi2-ucx-probes/`。双卡两份日志 SHA-256 分别为 `290b66bd0843513aee4a52495a754d25e788ae0558724e511dab3c63d9713cbd`、`5bd843acf520babf1f1b0bc45c504100411166ccfd1554c75b2811bb64b7b8fc`。

初始 23 个场的位指纹与 P1 完全一致；第一步静止分量 `q=0` 出现约一 ULP 的舍入差，其余 18 个分布分量逐位相同。后续碰撞将舍入差传播，因此全场指纹不再相同。定点比较与摘要支持当前数值精度结论，但不构成全场逐点误差上界。

## 536³ 探索性容量试跑

只对独立原型运行 10 步，尚未作为集成求解器的容量验收。命令附加 `amr.n_cell='536 536 536' max_step=10 amr.max_grid_size=64 aa.final_summary=0 'aa.diagnostic_steps=0 1 10'`；输入及二进制哈希同上。153,990,656 有效格点，729 个 FAB，10 步正常退出，用时 4.99 s。`nvidia-smi` 0.1 s 采样峰值 30,863 MiB；AMReX arena 最大已用 29,386 MiB、已分配 30,518 MiB，结束时设备余量 1,637 MiB。初始/第 1/第 10 步 `TGV_METRICS` 均为有限正值，末步平均密度 `0.99999999999999967`、平均动能 `4.9820968280261927e-5`、`min_rho=0.99955005247683071`、`min_f=0.026146687753369188`。日志 `$R/runs/aa536-10-exploratory/run.log`，SHA-256 `861bc4c8517740a91cb273ac1e0f863d5feb6b760b26acaf9244e0ef7f33311d`。

容量算式：`536³=153,990,656` 个有效单元；九块/轴、一层 ghost 的分布场分配 `(536+18)³ × 19 × 8 = 24,647.5 MiB`，4 分量有效宏观场 `536³ × 4 × 8 = 4,699.4 MiB`，数值场合计 `29,346.9 MiB`。本机 arena 实际已用比该算式多约 39 MiB，设备峰值还包括 arena 预留和运行时开销。

集成到 `AmrCoreLBM` 后仍需独立进程跑满 100 步，并在第 1、50、100 步检查在线标量、GPU 峰值、arena 和无全场文件。当前原型只覆盖单层全周期无外力 TGV；IBM、非周期边界、AMR 和 checkpoint 未验证。
