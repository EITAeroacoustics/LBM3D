# 三维专用构建的强弱扩展复测（2026-11-22）

## 结论

当前三维专用构建通过 1/2/4 卡 TGV3D 强弱扩展验收：双卡和四卡的四项效率均严格大于 90%，最小值为四卡强扩展 **90.53%**。但这次清理二维分支没有带来可确认的三维性能提升。同日同配置对照中，当前版四卡强扩展比旧版慢 **0.51%**，四卡弱扩展慢 **0.02%**；该顺序对照不足以把千分量级差异归因于代码改动。

## 条件与判据

- 工作站：4×Tesla V100-SXM2-32GB，驱动 535.309.01；AMReX 26.11 三维 CUDA、Open MPI 4.1.8 CUDA-aware、UCX 1.21.1。两版均使用 `sm_70`、Release `-O3 -DNDEBUG`、`LBM_TIMING=ON`、`LBM_ENABLE_IBM=OFF`，链接同一 AMReX 和 MPI 安装。
- 运行：`UCX_TLS=self,sm,cuda_copy`，UCX PML 选项 `--mca pml ucx --mca pml_ucx_tls any --mca btl ^uct`。1/2/4 卡分别映射 GPU `0` / `0,2` / `0,1,2,3`；多进程按 NUMA 绑定，由 `rank_gpu.py` 在 `MPI_Init` 前限定每进程可见 GPU。
- 强扩展固定全局 256³；弱扩展固定每卡 256³。均保持 `max_grid_size=64`、`blocking_factor=8`，前 100 步预热，后 500 步取最慢 MPI rank 的同步步时。每版、每档三次，顺序为 1→2→4、4→2→1、1→2→4；表中为中位数。质量检查间隔 100 步。
- 强效率为 `T1/(N×TN)`，弱效率为 `T1/TN`；双卡和四卡四项均须严格超过 90%。`run_strong.py`、`run_weak.py` 强制关闭 plotfile/checkpoint 并检查无全场文件。

当前二进制 SHA-256：`f293f7240ec8eabbe11a0f181fa1fae49a239735875609e84f88e093b8bd3f2b`。对照二进制 SHA-256：`040613166e43cc607e28aaec29e07e14d825c953b1599ce5f8fe66a5067aafae`，即[此前的方向性 halo 性能验收](directional-halo-results.md)使用的二进制。当前构建来自未提交工作树在工作站的隔离源码快照 `/home/hanbo/workspace/LBM/deps/lbm3d-3donly.gowx2N`；测试前核对了本地 `Source/`、`CMakeLists.txt` 和 TGV3D 输入与该快照一致。两版测试使用相同输入校验值，原始报告记录每次命令、二进制与日志校验值。

## 结果

| 测试 | GPU | 旧版 ms/步 | 当前 ms/步 | 当前相对旧版步时变化 |
| --- | ---: | ---: | ---: | ---: |
| 强扩展 | 1 | 42.019 | 42.015 | −0.01% |
| 强扩展 | 2 | 21.195 | 21.209 | +0.06% |
| 强扩展 | 4 | 11.543 | 11.602 | +0.51% |
| 弱扩展 | 1 | 42.014 | 42.019 | +0.01% |
| 弱扩展 | 2 | 42.173 | 42.168 | −0.01% |
| 弱扩展 | 4 | 43.287 | 43.297 | +0.02% |

| 效率 | 旧版 2 卡 | 当前 2 卡 | 旧版 4 卡 | 当前 4 卡 |
| --- | ---: | ---: | ---: | ---: |
| 强扩展 | 99.12% | **99.05%** | 91.01% | **90.53%** |
| 弱扩展 | 99.62% | **99.65%** | 97.06% | **97.05%** |

当前版的 [`check_scaling.py` 结果](retest-3donly-20261122/current/check_scaling.json)和旧版[同日对照结果](retest-3donly-20261122/control/check_scaling.json)均为 `passed=true`。36 次运行全部正常退出，末步质量分别等于强扩展的 16,777,216 和弱扩展的 16,777,216 / 33,554,432 / 67,108,864；每次日志均显示方向性 halo 已启用，无 plotfile/checkpoint。另以相同 UCX 栈执行 128³ TGV、10 步的[紧凑字段对照](retest-3donly-20261122/current/field-summary.json)：1/2/4 卡各 23 个分量的求和、二范数、极值和位置敏感指纹均与旧版完全一致，未写全场文件。原始性能数据：[当前强扩展](retest-3donly-20261122/current/strong.json)、[当前弱扩展](retest-3donly-20261122/current/weak.json)、[旧版强扩展](retest-3donly-20261122/control/strong.json)、[旧版弱扩展](retest-3donly-20261122/control/weak.json)。运行日志保存在上述工作站快照的 `runs/scaling-ucx-{current,control}-20261122/` 下。

较早的[正式三轮基线](directional-halo-results.md)四卡强扩展为 11.618 ms/步、效率 90.43%；当前版相对其快约 0.14%，但同日对照旧版为 11.543 ms/步。因而不能把与较早记录的微小差异解释为删减二维代码的收益。二维路径原本由编译期维度选择；三维 TGV 已走 D3Q19 方向性 halo 热路径。紧凑摘要可用于本轮回归检查，但不等同于读取全场做逐格证明。
