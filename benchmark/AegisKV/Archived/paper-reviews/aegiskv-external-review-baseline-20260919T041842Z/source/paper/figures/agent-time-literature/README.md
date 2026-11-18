# Figure 3(a): published agent-prediction evidence

当前 Insight 使用已有研究提供的预测能力作为设计依据。Heddle Figure 13
在三个 Agent 任务上报告了逐步预测剩余轨迹长度的效果。本图从原 PDF 矢量柱高
读取 Pearson 相关系数，用两个真实观测时点连接成线，不生成额外样本。

来源：[Heddle, arXiv:2603.28101v1](https://arxiv.org/pdf/2603.28101v1)，
PDF 第 10 页，Figure 13 / §7.2。Rollout 模型为 Qwen3-14B。

| Agent 任务 | 第一步后 | 第二步后 |
|---|---:|---:|
| Coding | ≈0.67 | ≈0.72 |
| Search | ≈0.72 | ≈0.88 |
| Math | ≈0.82 | ≈0.94 |

这是预测值与实际值的相关性，不是“72%/88%/94% 的预测准确率”，也不等同于
秒级执行时间的相对误差。图展示原作者的结果，并非本项目复现实验；按读取精度
只报告约两位小数。数据表保留原图的全部 3 个任务 × 3 个指标 × 4 个方法，
主图只选择与逐步预测直接对应的两个 Heddle 时点及 Pearson 指标。
未恢复逐轨迹样本数和置信区间；不能把三个领域当作三次独立实验。

图注明确文献归属；正文由已有预测能力引出 AegisKV 的 Slack 与 KV 保护。
旧 CC GBDT 诊断及完整负面结果保留在 `../agent-time-early/` 与
`../design-insights/`，它们没有复现 Heddle，不用于代表已有预测器的能力。

另核对了 AgentDecarbonizer Figure 15。它支持保守的任务级时长估计，但六类
组合工作负载中存在明显高估，因此本图不以该图声称低时长误差；其方法仅在正文
作为直接估计 Agent 时长、随进度更新的补充引用。

## 可复现文件

- `agent-predictability-panel.{pdf,svg,png}`：2.24 × 1.85 inch，正文 (a)。
- `agent-predictability-single-column.{pdf,svg,png}`：3.34 × 2.30 inch。
- `figure3-row.{pdf,png}`：与当前 (b)/(c) 的矢量合成。
- `../../../experiments/data/agent-time-literature/`：原 PDF、原图摘录、
  `heddle-figure13-values.csv` 和矢量读取来源记录。

```sh
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_agent_prediction_literature.py
sh benchmark/AegisKV/paper/build.sh
```

字体为 Linux Libertine 10.05 pt；SVG 保留文字。按原生单栏、三图并排及实际
论文 PDF 查看导出，核对记录在 `output/pdf/aegiskv-literature-insight-20260918/`。
