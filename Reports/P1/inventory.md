# P1-01 上游、工作站与测试协议盘点

记录日期：2026-11-21。原始数据与构建目录位于工作站 `/home/hanbo/workspace/LBM`；本仓库只保留脚本、输入、协议和小体积报告。

## 上游与依赖

| 项目 | 冻结值 | 说明 |
|---|---|---|
| iLBMReX 子模块 | `a8c7c89ccac0c90c84f3ebbf6ad59ce94a38df95` | 原始求解器算法基线；远端源码为此提交的源码包 |
| 原嵌套 AMReX | `5da47374715c495d1dcadd531edec1e2cd532da5` | 约 25.03+6；本轮不作为新基线的链接库 |
| 新 AMReX | `26.11`，`72d668eb80d1737e4550a5abf2fca5fcbc8ba637` | 官方发布版，独立安装 2D/3D CUDA；发布页：<https://github.com/AMReX-Codes/amrex/releases/tag/26.11> |
| iLBMReX 许可 | 仓库 `LICENSE` 为 MIT，`README.md` 写 BSD 3-Clause | 两处冲突；后续 P1-07 复制自有代码前需要确认上游许可声明 |
| AMReX 许可 | BSD 3-Clause 风格 | 保留独立上游版权和许可文件 |

求解器源码包含 `Core`（层级数据与推进）、`LBM`（碰撞、流动、宏观量核函数）、`BC`（边界）、`IBM`（浸没边界与力）、`LevelSet`、`Utils`、入口 `Source/main.cpp`。现有带 Makefile 的示例为 `Cavity_flow`、`Couette_flow`、`Cylinder_flow`、`ForceValidation`、`Pitching_airfoil`、`Sphere_flow`、`SquareDuct_flow`、`Taylor_Green_Vortex`；`Parameter_choice` 是辅助目录。原 `Taylor_Green_Vortex` 的初场是二维公式，故使用本轮新增的 `Benchmarks/TGV3D`。

## 工作站

| 项目 | 检测值 |
|---|---|
| GPU | 4 × Tesla V100-SXM2-32GB，计算能力 7.0，每卡 32768 MiB |
| 驱动 / CUDA | 535.309.01 / CUDA 12.2，`nvcc` 位于 `/usr/local/cuda/bin/nvcc` |
| MPI / C++ / Python | Open MPI 4.1.2 / GCC 11.4.0 / Python 3.10.12 |
| CMake | 系统 3.22.1 不满足 AMReX 26.11 最低 3.25；已校验并安装独立 CMake 3.30.9 于 `deps/` |
| 拓扑 | GPU0/1 在 NUMA0，GPU2/3 在 NUMA1；同域 GPU 间为 PHB，跨域为 SYS |

AMReX 构建使用 Release、double、MPI=ON、particles=ON、CUDA 架构 70、`AMReX_CUDA_FASTMATH=OFF`、Fortran=OFF；2D 与 3D 的构建及安装目录分开。源码压缩包 SHA-256 为 `c270730e16d8a2bc718879db80caba33c81c7fe5470bf761ec0be26099a13b1c`。CMake 3.30.9 Linux 包 SHA-256 为 `9114e33358a9efc93d6ea658805280fc3201b882b944a4d946edd9472fd1eec7`。工作站日志位于 `logs/amrex-26.11-*`、`logs/baseline-*`。

2D/3D AMReX 均已构建并安装。`Baseline/CMakeLists.txt` 使用外部安装库编译原始求解器；2D Cavity 2 步、3D TGV 64/128 网格短程运行均正常退出。IBM 预处理宏兼容副本仅在构建目录生成，原始上游源码无改动。2D 与 3D 基线编译日志均显示成功。

## 冻结测试口径

物理、性能、容量、逐位探测的固定参数和判据见 `Benchmarks/TGV3D/protocol.md`，输入与分析程序见该案例目录。该协议在正式物理测试前写定。每轮保存输入 SHA-256、二进制 SHA-256、AMReX 配置、命令、日志与结果目录；大流场留在工作站。

## 旋翼资料可用性初查（R-01 后置）

本仓库与工作站 LBM 工作目录未发现两副旋翼 STL，也未发现 90 RPS 推力、扭矩、功率原始实验记录。仓库中唯一 STL 是 AMReX 教程的 `airfoil.stl`，不是旋翼数据。这仅是开发过程中的资料可用性初查。按用户 2026-11-21 约定，R-01 与旋翼算例安排在 LBM3D 求解器开发完成后再启动；届时核对 STL 来源、单位、许可、几何坐标系、实验量纲、功率定义和不确定度。
