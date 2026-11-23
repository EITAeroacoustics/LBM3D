# P2 数值路线：PowerFLOW 公开资料对照（2026-11-23）

本报告只核对公开数值方法，为当前三维 TGV 精度与单卡容量决策提供依据；PowerFLOW 的版本和应用范围按各来源原文限定。

| 项目 | PowerFLOW 公开证据 | LBM3D 当前路线 |
| --- | --- | --- |
| 离散与推进 | 3DS 作者对 PowerFLOW 6-2019 写明 D3Q19、沿离散速度特征线的显式推进；NASA 的求解器对照表将 PowerFLOW 概括为 D3Q19、BGK、VLES。[3DS 论文](https://www.3ds.com/assets/invest/2024-05/pav-city.pdf)；[NASA Ames 报告](https://www.nas.nasa.gov/assets/nas/pdf/ams/2022/AMS_20220830_Wong.pdf) | 固定三维 D3Q19、二阶速度平衡态、BGK 单松弛时间、显式碰撞与格点流移，目标 Ma<0.3。相同的格子与 BGK 类别不表示逐项数值公式相同。 |
| 碰撞与湍流 | 同一 3DS 论文说明该版本使用**正则化的改进碰撞算子**；VLES 用 RNG k-ε 模型确定松弛时间及其他平衡态参数。[3DS 论文](https://www.3ds.com/assets/invest/2024-05/pav-city.pdf) | 当前 TGV 保持普通 BGK，不加入正则化或 VLES。将来 VLES 从有效松弛时间耦合，但须单独冻结模型并验收，不能称为 PowerFLOW VLES 复现。 |
| 运行精度 | PowerFLOW 与 NASA 作者指出：机体噪声计算**通常**用单精度，较安静的声学问题可能需要双精度；这描述的是应用经验，不能推出所有版本或 GPU 路径均用 FP32。[NASA/3DS 论文](https://ntrs.nasa.gov/api/citations/20210014178/downloads/GLBC_Part2_AviationPaper_final_revised.pdf?attachment=true) | 以 P1 双精度为严格数值基线；FP32 只作为需通过相同判据的容量实验。 |

**本项目实测。** [FP32 筛选](p2-tgv-fp32-precision-20261123.json)在 64³、128³ 的 P1 初场误差和质量严格判据上均失败，放宽到质量漂移 `1e-6` 仍未通过；不能据 PowerFLOW 的典型用法放行。本项目的 [FP64 对照](p2-tgv-fp64-precision-20261123.json)通过两档网格的九项 P1 严格物理检查。[AA 独立原型](../AA/aa-prototype-20261123.md)用一份 FP64、19 分量 `MultiFab` 完成 536³（153,990,656 格点）10 步探索性运行，峰值 30,863 MiB；这尚非集成求解器的 100 步容量验收。

**实现边界。** AA 奇偶步原位访问是 LBM3D 为减少双份分布函数显存而选择的存储与流移实现，须继续验证方向性 halo、奇偶步及集成后的 TGV。3DS [产品页](https://www.3ds.com/products/simulia/powerflow/)确认支持 GPU 加速；本次核对的资料没有给出其 GPU 分布函数布局、缓冲数、AA 使用与否或具体精度配置。因此不把本项目的 AA、AMReX `MultiFab` 或方向性 halo 写成 PowerFLOW 的实现。当前容量路线继续使用 FP64 AA；只有集成路径完成 536³ 的独立 10/100 步实测与多卡 TGV 回归，才判定 P2 容量及并行目标。
