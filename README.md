# LBM3D

本项目以 iLBMReX 和 AMReX 为技术起点，开发面向 Ma<0.3 的三维 CUDA 格子玻尔兹曼求解器。LBM3D 固定采用 D3Q19，不再提供二维求解、案例或构建路径。

第一阶段三维 TGV 基线已验收；后续开发聚焦测试体系、三维 IBM、静态局部加密、局部时间推进和 VLES。旋翼算例在求解器开发完成后启动。

项目定位与验收口径见[项目目标](项目目标.md)，待办和依赖见[实施任务](LBM3D实施任务.md)，当前模块与构建方法见[求解器说明](Source/README.md)。

## 上游版本

- iLBMReX `a8c7c89ccac0c90c84f3ebbf6ad59ce94a38df95`
- AMReX 26.11，作为独立的三维 CUDA 安装库链接

使用 `git clone --recurse-submodules https://github.com/EITAeroacoustics/LBM3D.git` 获取源码；项目自有求解器由根目录 CMake 构建并链接三维 AMReX。上游来源与许可记录见[迁移记录](Source/UPSTREAM.md)。P1 离线传输包仅保留为历史验收证据。
