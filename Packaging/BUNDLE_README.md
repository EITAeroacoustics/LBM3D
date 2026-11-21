# LBM3D 离线传输包

本包包含固定提交的 LBM3D 项目、原始 iLBMReX 源码、AMReX 26.11 源码，以及 CMake 3.30.9 Linux x86-64 工具。`manifest.json` 记录版本、大小和每个文件的 SHA-256。

在 Linux 工作站上解包后进入 `LBM3D-offline`，先执行：

```sh
sha256sum -c SHA256SUMS
```

然后运行 `bash offline_build.sh`。脚本只使用本包内源码和 CMake，以及工作站现有的 CUDA、MPI、C++ 编译器和 Python。它在本目录下解包、编译并运行 3D TGV 两步短程检查；构建路径和原始日志都保留在 `work/`。独立复跑完整物理、1/2/4 卡基准及自动报告的命令见项目内 `Benchmarks/TGV3D/README.md` 和 `Reports/P1/README.md`。

如需从干净导入直接重跑完整 P1 TGV 测试，执行 `bash offline_build.sh --full`。它另外构建原始与模块化计时版，运行两档物理、重组前后场值、1/2/4 卡强扩展与容量、初始化/写盘、逐位一致性和六组各 600 秒稳定性测试。完整测试耗时较长，大体积 plotfile 与日志保留在 `work/full-p1/`；`work/full-p1/index.json` 是报告索引，`work/toolchain.txt` 记录工具链。

该包用于工作站导入与编译验收；LBM3D 测试体系在 P1 完成后另行建设，无需离线部署。
