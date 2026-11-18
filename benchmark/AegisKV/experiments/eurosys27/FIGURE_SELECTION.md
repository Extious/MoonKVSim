# Evaluation 正文图像选择

当前 `paper/evaluation.tex` 独立维护 Evaluation。正文选择 **6 张已有证据图**，另保留 **1 张补充图**；完整当前系统实验矩阵与已获得局部证据分开。尚无当前 fixed-L/K/Z、exclusive 三层与 lazy lower-tier credit 完整控制器的端到端实测。

## 当前正文

| 图像 | 科学作用与边界 |
|---|---|
| `eval-placement-pairs` | 历史放置解析模型：展示同配置配对差值与19个零收益；不能作为当前端到端主结论。 |
| `eval-recovery-paths` | 物理worker微基准：确定重建/复用成本量级，保留真实后端、单一输入流和计时范围。 |
| `eval-rental-diagnostic` | 历史rent负结果与修复：揭示成本/控制工作权衡，不能替代当前lazy lower-tier credit评估。 |
| `eval-tracker-errors` | 真实记录上的held-out预测误差：展示全部长尾，明确whole-Agent和当前segment-Slack的差距。 |
| `eval-sparse-demand` | 原生选择器历史窗口到未来需求的离线覆盖：等物理预算、三文档和oracle上限，保留弱效应。 |
| `eval-trace-tails` | 历史trace-driven队列模型：平均收益与p95/p99回归同时可见，不能充当真实服务恢复。 |

## 补充与历史证据

- `eval-sparse-horizon`：补充预测范围：固定K与排名，展示64到512个future Queries的频率增益衰减。
- 旧 34 个绘图入口、原 8 张正文/26 张补充选择完整保存在 [legacy-main-figures.json](legacy-main-figures.json)；旧数据、解析假设和负结果均保留。
- `plot_expanded.py` 与 `check_expanded.py` 使用历史清单。它们不恢复旧 17 小节或覆盖当前选图，也不证明当前控制器有效。
- 历史 renderer 的 `--publish` 仅保留其旧目录行为；当前正文的 `figures/evaluation/` 由本轮发布步骤管理。

## 源码、统计和复现

- [图像与数据来源清单](../../exports/evaluation-rework-20260922T170350Z/figure-manifest.json)、[导出审查](../../exports/evaluation-rework-20260922T170350Z/FIGURE_REVIEW.json)、[字号审查](../../exports/evaluation-rework-20260922T170350Z/font-review.json)。
- 当前 renderer：`python3 benchmark/AegisKV/experiments/scripts/eurosys27/render_evaluation.py`。首次在新输出目录运行增加 `--verify-native-sources`；当前400个native来源核验已缓存。
- 当前 checker：`python3 benchmark/AegisKV/experiments/scripts/eurosys27/check_evaluation.py`，在发布并编译后检查；`--artifact-only` 只检查数据和独立产物。
- 固定3.33465英寸单栏画布，Libertine 10.3 pt。物理误差线仅真实重复的min–max；native文档范围不是CI；确定性模型不制造独立运行。
- 6张是本轮选择，后续真实系统收益、正常开销、机制验证和正确性完成后，应按证据重新选择。

完整设计见 [EXPERIMENT_MATRIX.md](EXPERIMENT_MATRIX.md)，所有当前和历史预览见 [FIGURE_CATALOG.md](FIGURE_CATALOG.md)。
