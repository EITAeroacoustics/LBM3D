# P1-12 自动复现与报告入口

`Benchmarks/TGV3D/run_p1.py` 以入库 TGV3D 案例为唯一输入来源，按顺序运行两版 64³/128³ 物理检查、六个检查点的四场逐位对照、两版 256³ 强扩展与容量、初始化/写盘、模块化版跨卡逐位一致性及六组稳定性。它生成 `index.json`、`summary.md`、物理和强扩展 SVG、各项机器可读 JSON，并保留每次命令与日志路径。上游八个示例及 IBM 专项回归由 `Examples/run_regression.py` 提供入口。

在固定源码提交 `995813161540d2a09e57a6571c73ada3fe121c03` 的传输包洁净导入目录中，使用 `run_p1.py --stability-seconds 1` 执行整套编排链路；六组各 600 秒的正式长时运行已单独实测并保存在 [P1-11](stability.md)。这一短时参数只缩短编排自检的求解墙钟，不把 1 秒结果代替 600 秒验收。

自动入口已完整退出并生成 [索引](clean-replay/index.json) 和 [汇总](clean-replay/summary.md)，索引的 `passed` 为 `true`。两版物理、24 项重组前后场值对照、两版 1/2/4 卡各三次强扩展、容量、初始化/写盘、16 项跨卡逐位比较及六组短程稳定性编排均按对应判据执行。小体积原始 JSON、CSV、SVG 见 [洁净复跑目录](clean-replay/)；工作站日志和 plotfile 位于 `/home/hanbo/workspace/LBM/runs/p1-13-offline-import/LBM3D-offline/work/full-p1-clean-final/`。

顺序分组测得的强扩展中位数见 [离线复跑记录](offline.md)。同机不同时段的时间波动明显，因此该轮顺序分组的相对变化不单独充当代码性能回归结论；1/2/4 卡交替顺序复核及解释见 [迁移报告](migration.md)。P1-09 的初始同条件测量与完整原始日志仍保留。
