# 四卡通信路径与质量诊断调优（2026-11-22）

## 测试条件

工作站为 4×Tesla V100-SXM2-32GB（GPU 0/1 在 NUMA 0、2/3 在 NUMA 1，无 NVLink），AMReX 26.11，CUDA-aware Open MPI 4.1.8 + UCX 1.21.1。每进程一张卡，双卡用 0/2 且每 NUMA 一个进程，四卡用 0/1/2/3 且每 NUMA 两个进程。`UCX_TLS=self,sm,cuda_copy`，`OMPI_MCA_pml=ucx`，`OMPI_MCA_pml_ucx_tls=any`；启动参数为 `--mca pml ucx --mca pml_ucx_tls any --mca btl ^uct`。`rank_gpu.py` 在 `MPI_Init` 前为各进程限定可见 GPU。

强扩展固定 256³，弱扩展每卡 256³；两者均为 `max_grid_size=64`、`blocking_factor=8`，100 步预热加 500 步计时，关闭 plotfile/checkpoint。下表是**单轮筛选值**，效率以每轮对应单卡步时计算，尚非三轮正式结论。二进制、输入、命令和日志校验值保存在各 JSON 中。

| 路径 / 改动 | 1/2/4 卡强扩展 (ms/步) | 双/四卡强效率 | 1/2/4 卡弱扩展 (ms/步) | 双/四卡弱效率 |
| --- | ---: | ---: | ---: | ---: |
| [UCX 默认](ucx-strong-r1.json)、[弱扩展](ucx-weak-r1.json) | 46.85 / 23.98 / 16.75 | 97.7% / 69.9% | 46.85 / 47.23 / 55.27 | 99.2% / 84.8% |
| [UCX 主机分片 2 MiB](ucx-strong-hostfrag2m-r1.json) | 46.85 / 23.93 / 17.28 | 97.9% / 67.8% | 未测 | 未测 |
| [UCX GET pipeline](ucx-strong-getppln-r1.json) | 46.85 / 67.09 / 61.62 | 34.9% / 19.0% | 未测 | 未测 |
| [质量检查每 100 步](ucx-strong-mass100-r1.json)、[弱扩展](ucx-weak-mass100-r1.json) | 48.42 / 24.69 / 15.95 | 98.1% / 75.9% | 48.34 / 48.69 / 52.61 | 99.3% / 91.9% |

UCX 默认路径已在 1/2/4 卡通过 128³、10 步的 23 分量紧凑场统计，见[结果](ucx-field-summary-128.json)。其四卡 Nsight 跟踪在每步看到约 19.2 MiB 的设备到主机和同量反向拷贝，主机暂存以 512 KiB 分片进行；`MPI_Allreduce` 每步约 1.2 ms（剖析环境估计值）。把 `UCX_RNDV_FRAG_SIZE` 的 host 片段从默认 512 KiB 提至 2 MiB 未改善四卡强扩展。单独将 `UCX_RNDV_SCHEME` 设为 `get_ppln` 保持短算例质量守恒，但强扩展大幅回退，因此不采用。

尝试启用 `cuda_ipc` 与 `cuda_copy` 混合的短算例时，四卡 `Sum(Rho)` 为 16,720,808.3，而正确值为 16,777,216；该配置已排除。当前验证过的路径仅使用 `self,sm,cuda_copy`，不能把有质量错误的混合 IPC 结果作为加速依据。

`AmrCoreLBM::Evolve()` 原本每步执行 `macro_new[0].sum(0)`，产生 GPU 全场规约及 MPI 全局同步。现在 `lbm3d.mass_check_interval` 默认为 100，仍在首步、各间隔、末步以及力验证时检查；设为 1 可恢复逐步检查。四卡强算例用**同一个新二进制**按 1→100→100→1 的顺序配对复测，步时依次为 17.454、16.123、15.967、17.665 ms；两组中位数为 17.560 与 16.045 ms，间隔 100 节省约 **1.51 ms/步（8.6%）**。600 步运行的质量日志分别有 600 和 7 条；间隔 100 的末步 `Sum(Rho)=16,777,216`。四次均未生成全场文件。日志位于工作站 `/home/hanbo/workspace/LBM/runs/multigpu-ucx-cuda/massinterval/paired-4gpu-mass-*`。

四卡弱扩展的单轮效率已超过 90%，但四卡强扩展仍约 76%，因此 1/2/4 卡四项效率全部超过 90% 的目标**尚未完成**。方向选择性 D3Q19 halo 原型的静态审查见 `/private/tmp/lbm3d-selective-halo/REVIEW.md`；它仍需编译、数值对照和三轮计时，不能视为已启用的优化。
