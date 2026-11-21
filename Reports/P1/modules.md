# P1-07 自有求解器库与模块验收

记录日期：2026-11-21。原始构建日志与运行结果位于工作站 `/home/hanbo/workspace/LBM`；本仓库保存构建入口、源码和小体积验收记录。上游来源、许可与迁移改动见 `Source/UPSTREAM.md`，模块职责、公开入口与依赖方向见 `Source/README.md`。

## 构建与依赖

根目录 `CMakeLists.txt` 只构建一个 `lbm3d` 静态求解器库；各示例目标仅编译公共入口与本示例的初始化单元，再链接同一库。2D 和 3D 分别配置，均使用 Release、CUDA `/usr/local/cuda/bin/nvcc`、对应维度的独立 AMReX 26.11 安装库；未编译或修改 AMReX 源码。

| 维度 | AMReX 路径 | 目标与结果 |
|---|---|---|
| 2D | `deps/amrex-26.11-install-2d` | `lbm3d`、`lbm3d_cavity`、`lbm3d_pitching_airfoil` 构建成功 |
| 3D | `deps/amrex-26.11-install-3d` | `lbm3d`、`lbm3d_tgv3d` 构建成功 |

构建目录是 `deps/lbm3d-build-{2,3}d`，日志是 `logs/lbm3d-build-{2,3}d.log`；2D 最后一次日志为 `logs/lbm3d-build-2d-final.log`。`Source/` 中没有对示例 `Prob.H` 或 `IBMUserDefinedGeometry.H` 的编译期包含。`Pitching_airfoil` 的原公式在 IBM 模块作为内置几何，输入可显式指定 `ibm.marker_geometry=pitching_airfoil`；现有 `user_defined` 输入值仍可运行。

## 短程运行

| 目标 | 条件 | 结果及工作站证据 |
|---|---|---|
| `lbm3d_cavity` | 2D，单进程单 GPU，2 步 | 正常结束；`logs/lbm3d-cavity-2d-after-split.log` |
| `lbm3d_pitching_airfoil` | 2D，单进程单 GPU，2 步 | 两层标记点 IBM 初始化，载荷文件含表头和两步数据；`logs/lbm3d-pitching-2d-after-split.log` |
| `lbm3d_pitching_airfoil` | 2D，显式指定 `ibm.marker_geometry=pitching_airfoil`，2 步 | 日志确认选择该内置几何，`force.dat` 含表头和两步数据；`logs/lbm3d-pitching-explicit-final.log` |
| `lbm3d_tgv3d` | 3D，单进程单 GPU，2 步 | 正常结束；`logs/lbm3d-tgv3d-after-split.log` |
| `lbm3d_tgv3d` | 3D，64³，单进程单 GPU，64 步 | 步 0、32、64 写出 plotfile，正常结束；`runs/lbm3d-tgv3d-physics-64`、`logs/lbm3d-tgv3d-physics-64.log` |

对 64³ TGV，使用 `deps/baseline-build-3d/tgv3d_compare` 逐单元对照 P1-05 原始核心的 `runs/tgv-physics-64` 与新库运行结果。步 0、32、64 的 `rho`、`ux`、`uy`、`uz` 共 12 项比较，所有不一致单元数均为 **0**。这证明本算例迁移后的输出场逐位一致；全部示例迁移及更广泛的物理、性能对照仍属于 P1-08、P1-09。

本次库化只调整源码组织、主机侧初场入口、现有翼型几何位置及 AMReX 宏兼容写法；碰撞、迁移、边界与力学数值公式保持原样。旋翼案例按用户约定在求解器开发完成后启动。
