# LBM3D

本项目面向大规模格子玻尔兹曼模拟。首版验证聚焦二维低马赫数流动、静态分层加密、浸没边界与 MPI + CUDA。当前提交固定未修改的 iLBMReX 复现基线。

## 上游版本

- iLBMReX `a8c7c89ccac0c90c84f3ebbf6ad59ce94a38df95`
- AMReX `5da47374715c495d1dcadd531edec1e2cd532da5`

在可联网机器上使用 `git clone --recurse-submodules https://github.com/EITAeroacoustics/LBM3D.git` 获取源码。向离线工作站传输已展开的 iLBMReX 和 AMReX 源码，然后在工作站编译。上游许可文件随子模块保留。

## CUDA 圆柱复现

已验证环境为 V100、CUDA 12.2 和 Open MPI 4.1.2。将 CUDA 工具链加入 `PATH` 后，在 `iLBMReX/Examples/Cylinder_flow` 构建：

```sh
make -j12 USE_CUDA=TRUE USE_OMP=FALSE CUDA_ARCH=70
```

在单独的结果目录下运行。将 `case_dir` 设为上述算例目录的绝对路径，按可用 GPU 设置 `CUDA_VISIBLE_DEVICES`。

```sh
mpirun -np 4 "$case_dir/main2d.gnu.MPI.CUDA.ex" "$case_dir/inputs" \
  amr.regrid_int=-1 amrex.the_arena_init_size=268435456
python3 "$case_dir/analyze_force.py" --force force.dat
```

2 rank 和 4 rank 分别使用两张和四张 GPU。两组均完成 20,000 步，`force.dat` 逐字节一致，平均阻力系数为 1.564621。升力波动低于上游脚本的周期判据，涡脱落频率尚未验证。关闭运行期重网格可绕开原始算例在第 21 步首次重网格时的崩溃。256 MiB 是默认 GPU 内存池的初始分配量。

流场以 AMReX 多层 plotfile 写入 `out_cylinder/`，载荷时序写入 `force.dat`。
