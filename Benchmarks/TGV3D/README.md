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

`run_p1.py` 是完整 TGV3D 验收入口，接受原始版、模块化版及各自计时版的二进制路径，再依次运行物理、重组前后场值、强扩展、容量、初始化/写盘、逐位一致性和稳定性测试，生成 `index.json`、`summary.md` 与 SVG 图。构建好对应目标后，用 `python3 Benchmarks/TGV3D/run_p1.py --help` 查看参数；完整运行包含六次至少 600 秒的连续测试。上游示例与 IBM 对照使用 `Examples/run_regression.py`。
