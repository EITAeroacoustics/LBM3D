# 第一阶段证据索引

阶段结论与放行状态见 [验收记录](acceptance.md)。下表记录 P1 验收提交 `995813161540d2a09e57a6571c73ada3fe121c03` 当时的交付与工作站路径；其中二维构建和示例是历史证据，当前 LBM3D 已收敛为仅支持三维 CUDA。

| 任务 | 本仓库或工作区交付物 | 工作站原始证据 |
|---|---|---|
| P1-01 盘点与协议 | `inventory.md`、`Benchmarks/TGV3D/protocol.md` | `logs/` 中的构建与运行日志 |
| R-01 旋翼资料 | 按用户约定后置到求解器开发完成后 | 暂不启动旋翼算例工作；`inventory.md` 仅记录当前资料可用性 |
| P1-02 AMReX 升级 | `inventory.md` | `deps/lbm3d-amrex-26.11`、2D/3D 安装及 `logs/amrex-26.11-*` |
| P1-03 外部构建 | `Baseline/` | `deps/baseline-build-2d`、`deps/baseline-build-3d`、对应日志 |
| P1-04 benchmark | `Benchmarks/TGV3D/` | 两档物理运行目录 |
| P1-12 复现框架启动 | 案例目录内的生成、分析、测量和绘图脚本 | `reports/` 中的机器可读报告 |
| P1-05 单卡物理 | `physics.md`、`tgv-physics.json`、`tgv-physics.csv`、`tgv-physics.png` | `runs/tgv-physics-{64,128}` 及对应日志 |
| P1-06 原始核心基线 | `performance.md`、强扩展/容量/逐位/I/O JSON 和曲线 | `runs/tgv-strong-256`、容量、逐位、I/O 与剖析目录 |
| P1-07 自有库与模块 | `modules.md`、`Source/`、根目录 `CMakeLists.txt` | `deps/lbm3d-build-{2,3}d`、`runs/lbm3d-tgv3d-physics-64` 及对应日志 |
| P1-08 全部示例兼容 | `examples.md`、`examples-report.json`、`Examples/` | `runs/p1-08-regression-with-motion/`、IBM 原始版构建及日志 |
| P1-09 重组对照 | `migration.md`、`tgv-modular-*` JSON/CSV/SVG、`paired-check-*.json` | `runs/p1-09-*`、`logs/p1-09-*`、`runs/p1-13-offline-import/LBM3D-offline/work/paired-check*/` |
| P1-10 跨卡逐位一致 | `determinism.md`、`tgv-final-bitwise-128.json` | `runs/p1-10-final-bitwise-128/` |
| P1-11 连续运行 | `stability.md`、`tgv-stability.json` | `runs/p1-11-stability/`、`reports/p1-11-stability.json` |
| P1-12 自动报告 | `automation.md`、`Benchmarks/TGV3D/run_p1.py`、`clean-replay/index.json`、`clean-replay/summary.md` 及图表 | `run_p1.py` 产出的日志和 plotfile |
| P1-13 离线包 | `Packaging/`、`offline.md`、`Deliverables/LBM3D-P1-offline.tar.gz`；洁净复跑通过 | `runs/p1-13-offline-import/` |

工作站根目录为 `/home/hanbo/workspace/LBM`。所有报告都以 `Benchmarks/TGV3D` 中入库输入为基准。仓库不包含数百 MiB 至 GiB 的原始 plotfile；通过上述固定路径和 JSON 中的输入、二进制校验值复核测量。
