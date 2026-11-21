# P1-13 固定版本传输包与洁净复跑

交付包为工作区 `Deliverables/LBM3D-P1-offline.tar.gz`，由入库的 `Packaging/make_offline_bundle.py` 可重复制作。压缩包按体积约定不纳入 Git，SHA-256：

```text
412366b219c7c25a2efeaf6f565f4b465be7ffa8b3732fbb0145cffd67ef1026
```

包内 `manifest.json` 固定项目提交 `995813161540d2a09e57a6571c73ada3fe121c03`、原始 iLBMReX 提交 `a8c7c89ccac0c90c84f3ebbf6ad59ce94a38df95`，包含独立 AMReX 26.11 源码、CMake 3.30.9、构建脚本与完整 benchmark。解包后 `sha256sum -c SHA256SUMS` 的六项均通过。工作站仅使用包内源码与 CMake、已有 CUDA/MPI/GCC/Python，不调用软件源或网络安装。

在 `/home/hanbo/workspace/LBM/runs/p1-13-offline-import/LBM3D-offline` 解包，从零构建包内 2D/3D AMReX 和 LBM3D 全部对应维度目标，均成功。`work/toolchain.txt` 记录 CUDA 12.2.140、Open MPI 4.1.2、GCC 11.4.0、Python 3.10.12、驱动 535.309.01 与四张 V100 32 GB。原始构建日志位于同目录 `work/*-config-*.log`、`work/*-build-*.log`。

核对实际 CUDA 目标编译命令：`baseline-timed-3d/CMakeFiles/ilbmrex_baseline.dir/flags.make` 与 `lbm3d-analysis-ON/CMakeFiles/lbm3d.dir/flags.make` 均包含 `--generate-code=arch=compute_70,code=[compute_70,sm_70]`，且其余 CUDA 标志相同。CMake 缓存中的自动探测值为 52，但 AMReX 目标辅助配置覆盖了最终目标架构；验收采用实际编译命令，而非仅看缓存值。

构建结束时包内短程命令默认选择 GPU0；它与当时正在运行的 P1-11 双卡稳定性测试争用 GPU0，AMReX 预留显存触发 OOM。随后使用已构建的同一 TGV3D 二进制在空闲 GPU3 完成两步并正常退出；`work/smoke-gpu3.log` 保留结果。六组长时测试全部结束、GPU0 释放后，重跑 `bash offline_build.sh`，六项清单校验、2D/3D 增量构建及默认 GPU0 上的 TGV3D 两步运行全部通过，日志为 `work/offline-build-final.log` 和 `work/smoke.log`。

从包内源码额外构建原始版和模块化版、计时版和非计时版四套 TGV3D 二进制。在空闲 GPU1 上用包内固定输入重跑原始版与模块化版 64³、128³ 单卡物理测试，两版各六个检查点，均通过九项冻结判据；六个检查点的平均密度和动能数值与先前 P1-05 报告逐项相同。见 [原始版 JSON](clean-baseline-physics.json) 与 [模块化版 JSON](clean-modular-physics.json)。原始 plotfile 和分析日志位于 `work/clean-physics-gpu1/`。分析器首次运行未继承 GPU1 映射，争用 GPU0 而中断；固定 `CUDA_VISIBLE_DEVICES=1` 后，仅重做分析并通过，原始版求解流场未重算。

首次自动汇总入口运行到模块化版四卡计时前，执行者曾把 CMake 缓存中的架构 52 误判为实际目标架构并主动中断。核实上段 `flags.make` 后，已在新的结果目录从头复跑；先前中断不计为求解器或脚本失败，旧日志仍保留于 `work/full-p1-clean-smoke.log`。

最终洁净轮次的两版物理与场值比较均通过，容量边界均为 328³/416³/528³；跨卡逐位比较 16 项均为零差异。1/2/4 卡强扩展中位数如下，单位 ms/步：

| GPU | 原始版 | 模块化版 | 顺序分组相对变化 |
|---:|---:|---:|---:|
| 1 | 67.405 | 71.020 | +5.36% |
| 2 | 173.487 | 149.707 | −13.71% |
| 4 | 206.970 | 229.174 | +10.73% |

各组是顺序测量，进程耗时在同一机器上随运行时段明显漂移；上述相对变化不能单独归因于模块重组。另用相同洁净编译二进制和固定输入补做 1/2/4 卡 AB/BA 交错顺序计时，各版两次中位数相对变化约为 0.00%/+0.01%/+0.86%，原始记录与测量局限见 [迁移报告](migration.md)。交错复核禁用全场输出。完整自动入口已完成，索引判定 `passed=true`，见 [洁净复跑索引](clean-replay/index.json) 和 [汇总](clean-replay/summary.md)。正式 600 秒稳定性结论见 [P1-11](stability.md)。当前没有第二位团队成员；此洁净导入由开发执行者完成，不能称为不同人员的独立复核。
