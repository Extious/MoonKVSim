# Agent 时间预测的 CDF 版本

本轮按用户要求恢复误差分布曲线。数据是原 CC 实验的 1,688 个 agent、174 个 workflow，三条曲线为 GBDT、训练集时长中位数先验、P90 先验；不是上一张文献柱状图的 Formula/GBDT/Graph。不重新训练、不删异常值、不平滑。

每个 agent 贡献一个数：所有在线预测时点的剩余时间绝对误差取平均，再除以该 agent 的总时长。横轴为该误差百分比，纵轴为误差不超过横轴阈值的 agent 比例。对称对数轴保留完整误差范围。此数据仍不能支持“已准确预测整个 agent”的正面结论。

- `agent-time-cdf-single-column.{pdf,svg,png}`：3.34 × 2.30 inch 单栏图。
- `agent-time-cdf-panel.{pdf,svg,png}`：2.24 × 1.85 inch，适配三图并排。
- `figure3-cdf-preview.{pdf,png}`：7 inch 并排预览，(b)/(c) 复用现有 PDF。
- 数据：`../../../experiments/data/design-insights/agent-errors.csv`，完整统计定义见该目录 `agent-summary.json` 及 `../design-insights/README.md`。
- 生成脚本：`../../../experiments/scripts/paper/render_agent_time_cdf.py`。

```bash
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_agent_time_cdf.py
```

仅显示 GBDT 曲线的版本位于 `gbdt-only/`，同样提供单栏、三图并排及 PDF/SVG/PNG：

```bash
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_agent_time_cdf.py --gbdt-only
```

该选项只移除 Median/P90 对照曲线，读取相同的逐 agent 误差，不重新训练。GBDT 的中位 NMAE 为 51.78%，P90 为 456.64%；保留全部 1,688 个 agent。这是当前 CC 实验中的 GBDT，不是文献中 Runtime WAPE 为 11.05% 的另一个实验。单独绘制不改变它目前不足以证明准确预测整个 agent 剩余时间的事实。

Graph 文献目前只有每个方法一个 WAPE 汇总值；这三个数不能还原逐样本误差的 CDF。2026-09-18 核对 [原论文](https://arxiv.org/html/2609.03335v1) 仍注明代码和数据将在录用后公开，本轮未找到公开的逐样本预测文件。取得原始预测值和实测值后，才能绘制该文献方法的真实曲线，不能由 WAPE 人工生成误差分布。

当前主稿本来就使用原 CC CDF，上一轮文献柱状图仅为候选；本次导出提供用户要求的曲线格式预览，不把文献数值与 CC 曲线混用。
