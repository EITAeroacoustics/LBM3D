# D3Q19 三维 Taylor–Green 基准

这是周期方盒 `[0,64]^3`、均匀网格、`amr.max_level=0`、无 IBM 的可复用案例。初始速度为

```text
ux =  U0 sin(kx x) cos(ky y) cos(kz z)
uy = -U0 cos(kx x) sin(ky y) cos(kz z)
uz =  0
```

其中 `kx=ky=kz=2π/64`、`U0=0.02`、`rho0=1`、`nu=0.06`。初始压力扰动是 `rho0 U0²/16 (cos(2kx x)+cos(2ky y))(cos(2kz z)+2)`，密度按 `rho=rho0+p/(1/3)` 设定。初始场在单元中心采样。无外力，D3Q19 权重和方向写在输入文件中。理论初始平均动能约为 `U0²/8=5e-5`，平均密度为 1。

`inputs_physics_64` 是入库的原始输入。用 `make_inputs.py` 可生成其他网格；入库的 `inputs_physics_128`、`inputs_strong_256`、`inputs_capacity_256`、`inputs_bitwise_128` 是对应的固定版本。物理检查的 64³、128³ 分别推进 64、128 步，因为原求解器使用 `dt=dx`；两个网格都在物理时间 0、32、64 写 plotfile。强扩展输入不写 plotfile，推进 600 步；前 100 步预热，后 500 步统计。容量输入只推进 10 步。逐位探测推进 10 步，写出步 0 和 10 的 plotfile。

构建参见 `Baseline/README.md`。每次运行在独立目录执行，例如：

```sh
mkdir -p runs/tgv-64-1gpu
cd runs/tgv-64-1gpu
CUDA_VISIBLE_DEVICES=0 /path/to/ilbmrex_baseline /path/to/inputs_physics_64 > run.log 2>&1
/path/to/tgv3d_analyze plt00000
/path/to/tgv3d_analyze plt00032
/path/to/tgv3d_analyze plt00064
```

多卡用一进程一 GPU。例：`CUDA_VISIBLE_DEVICES=0,1 mpirun -np 2 /path/to/ilbmrex_baseline /path/to/inputs_strong_256`；四卡将 GPU 列表和进程数改为 `0,1,2,3` 与 `4`。请固定 CPU/GPU 绑定并记录 `nvidia-smi topo -m`；本工作站 GPU 0/1 和 2/3 各在同一 NUMA 域，跨域经系统互连。输入和启动命令可变，C++ 无需重编译。

`tgv3d_analyze` 对全场检查 NaN/Inf，报告平均密度、平均动能和初始场相对独立三角函数计算的最大绝对误差。定量判据、记录格式和原始数据位置见 `protocol.md`。

`reference_physics.csv` 保存 2026-11-21 在 V100、AMReX 26.11、双精度原始核心上得到的六个小体积参考数值。它供后续回归对照；P1-05 的物理通过结论依据事前冻结的 `protocol.md`，参考数值不充当独立理论真值。

复现脚本：`check_physics.py` 汇总两档网格的六个 plotfile，执行冻结的九项检查并输出 JSON/CSV；`plot_physics.py` 用 Matplotlib 绘制动能曲线；`run_strong.py` 执行 1/2/4 卡各三次强扩展并输出 JSON；`run_capacity.py` 搜索 10 步容量。运行结果始终写入独立工作目录，避免覆盖既有数据。

工作站无需安装 Matplotlib 也可用 `plot_svg.py physics 报告.json 曲线.svg` 或 `plot_svg.py strong 报告.json 曲线.svg` 生成可复核的 SVG 曲线；`run_stability.py` 按容量报告选取约 80% 网格，执行六组连续 600 秒运行并记录显存与流场输出。

## P1 之后的测试输出

本目录中的物理、逐位与稳定性输入及脚本用于复现 P1 冻结验收，部分会写全场 plotfile。按后续测试约定，新发起的日常回归和测试智能体运行不得使用这些写盘配置，也不得写全场 checkpoint。强扩展输入 `inputs_strong_256` 已设置 `amr.plot_int = -1`、`amr.chk_int = -1`。后续测试体系将以求解时标量归约、紧凑逐位指纹或进程间比较和日志替代全场文件，并记录输出关闭状态。

单卡容量细化可用 `probe_single_gpu_capacity.py`。它从入库案例生成输入，强制关闭 plotfile 和 checkpoint，逐个独立进程测量完成步数、显存峰值及 AMReX arena 状态；`--max-grid-sizes`、`--blocking-factor`、`--start/--stop/--step` 和 `--steps` 控制网格与步数。已完成的 V100 结果见 [单卡容量报告](../../Reports/Capacity/single-gpu.md)。

项目默认保持 `max_grid_size=64`、`blocking_factor=8`。`inputs_capacity_single_gpu_352` 固定网格块 192、阻塞因子 8，供单卡容量专项复跑；`inputs_capacity_single_gpu_360` 用于无力临时场优化后的边界复核，均不改变默认配置。`compare_single_gpu.py` 以左右交替顺序测两个二进制或两份同网格输入，默认各运行两次，每次预热 100 步并计时 500 步。`inputs_strong_single_gpu_*` 是本轮使用的无全场输出计时输入，分项结果见 [优化复测报告](../../Reports/Capacity/force-field-optimization.md)。这些输入的前两行注释继承自 64³ 模板，实际网格、时间步及输出开关以输入参数为准。

多卡通信改动的无全场写盘回归使用 `lbm3d_tgv3d_summary` 和 `compare_field_summary.py`。给脚本传入原版、优化版二进制、`inputs_physics_128`、独立运行目录和报告 JSON 路径；脚本固定运行 10 步并覆盖 `amr.plot_int=-1`、`amr.chk_int=-1`，在 1/2/4 卡上比较最终密度、速度及 19 个分布函数分量的求和、二范数、极值，以及由全局坐标与浮点位模式组成的位置敏感整数指纹。CUDA-aware MPI 可传 `--mpirun`、`--mpi-options`、`--rank-wrapper`，仅优化版使用的输入开关可重复传 `--optimized-option`。脚本检查没有全场文件。派生涡量与压力在无输出运行中不刷新，故不纳入比较。紧凑统计与指纹一致可检测数值回归，但不等同于全场逐位证明；[本轮结果](../../Reports/Performance/multigpu-communication.md)保留命令、二进制与输入校验值。

计算弱扩展使用 `inputs_weak_{1,2,4}gpu` 和 `run_weak.py`：每卡固定 256³、网格块 64、阻塞因子 8，各方向 `dx=0.25`；全局网格依次为 256×256×256、256×256×512、256×512×512。运行 `python3 run_weak.py /path/to/lbm3d_tgv3d /path/to/runs /path/to/weak.json`，默认三轮交错测量，按预热 100 步后的 500 步最慢 MPI 进程耗时计算中位数和 `T1/TN`。`run_strong.py` 也按相同顺序交错运行。脚本记录命令、校验值并检查无 plotfile/checkpoint。配合同一二进制的 `run_strong.py` 报告，`check_scaling.py strong.json weak.json` 要求每档至少三轮、相同计算选项、无全场文件，再检查双卡和四卡的强、弱效率是否都严格超过 90%；单轮筛选可显式设 `--min-repeats 1`。扩大物理域后的 TGV 波长不同，弱扩展只用于计算效率比较；[基线与重叠试验](../../Reports/Performance/scaling-overlap-assessment.md)给出实际数据。

两种扩展脚本都接受 `--mpirun`、`--mpi-options`、`--rank-wrapper`、`--mass-check-interval` 和可重复的 `--input-option`；使用可能在 `MPI_Init` 初始化 CUDA 的 MPI 时，传 `rank_gpu.py` 使每个进程在进入求解器前只看到分配给自己的 GPU。求解器默认每 100 步做一次全局质量检查，且总在首步和末步检查；需要逐步诊断时设置 `lbm3d.mass_check_interval=1`。扩展测量建议显式传 `--mass-check-interval 100`，让报告记录这一条件。MPI 栈与拓扑参数应按工作站实际配置，见[CUDA-aware MPI 对照](../../Reports/Performance/gpu-aware-mpi-results.md)。

当前三维求解固定使用单层 D3Q19 方向性 halo；全周期 TGV、非周期方管和球体 IBM 的回归入口见[方向性 halo 回归](../DirectionalHalo/README.md)。[全周期 TGV 的三轮强弱扩展报告](../../Reports/Performance/directional-halo-results.md)记录的是先前版本及其二进制，不能直接当作当前提交的性能结果。

`run_p1.py` 是第一阶段的历史验收入口，接受原始版、模块化版及各自计时版的二进制路径，再依次运行物理、重组前后场值、强扩展、容量、初始化/写盘、逐位一致性和稳定性测试，生成 `index.json`、`summary.md` 与 SVG 图。该流程含全场输出，不用于第一阶段之后的新测试；后续通信回归使用上面的内存场摘要。上游示例与 IBM 的历史迁移对照脚本是 `Examples/run_regression.py`。
