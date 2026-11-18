# Agent 执行时间预测：文献候选图

这组新图展示**相关工作报告的条件执行成本预测误差**，不是 AegisKV 的新实测结果，也不证明开放式多轮 agent 的剩余墙钟时间已能准确预测。因此目前保留为 Figure 3(a) 候选，未覆盖正文中原来的 CC 诊断图和数据。

- `runtime-panel.{pdf,svg,png}`：2.24 × 1.85 inch，可放入 Figure 3 的三图并排布局。
- `runtime-single-column.{pdf,svg,png}`：3.34 × 2.30 inch，单栏版本。
- `figure3-candidate.{pdf,png}`：7 inch 宽的三图并排预览；(b)/(c) 使用现有 PDF 原样合成。
- `figure3-candidate-gray.png`：灰度审查。
- 数据：`../../../experiments/data/agent-runtime-relatedwork/reported-runtime.json`。
- 可编辑绘图代码：`../../../experiments/scripts/paper/render_agent_runtime_relatedwork.py`。

在仓库根目录重新生成：

```bash
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_agent_runtime_relatedwork.py
```

## 文献核对

| 工作 | 可借鉴的方法 | 已报告的证据与限制 |
| --- | --- | --- |
| [Pythia, v2](https://arxiv.org/html/2604.25899v2#S4.SS1) | 区分 workflow 类型、agent 角色；从历史执行提取工作流结构与角色画像 | Table 1 是角色输出长度的均值与 CV；Figure 12 是输出长度区间。不是整个多轮 agent 的耗时预测误差。 |
| [Maestro, v1](https://arxiv.org/html/2606.12950v1#S3.SS2) | 角色、工作流位置、调用序号、工具可用性与文本语义；先预测工具调用意图，再预测输出长度 | Table VI 衡量输出 token 数，不能把其中的 MAE 直接写成耗时误差；使用按组分层的时间留出测试。 |
| Maze，本地 `docs/related_works/2026/Maze.pdf` §III-B、§IV | 按任务类型，用前驱完成后可见的输入规模预测后继任务耗时；GBDT 在线更新 | 当前本地稿报告输入规模与任务耗时相关、删除预测模块后的系统性能变化；没有足以重建整个 agent 剩余时间误差分布的逐样本数据。公开文档与本地稿的调度器名称不同，不能混作完全相同版本。 |
| [Wang et al., v1](https://arxiv.org/html/2609.03335v1#S4.SS4) | 结合模型计算图、请求配置和设备特征估计执行成本 | Table 1 的 Runtime WAPE：Formula 15.29%、GBDT 11.05%、Predictor 7.25%。这是本图的唯一数值来源。论文 §3.3 的配置包含序列长度；不能据此证明未来输出长度和循环次数可准确预测。 |

图中的 Graph 是最后一篇论文的 Predictor，不是 AegisKV 模块。WAPE 为
`100 × Σ|预测时长 − 实测时长| / Σ实测时长`，既不是逐 agent MAPE，也不能解释为“92.75% 的预测准确”。保留了同一张表中的全部三个运行时间预测方法；没有捏造散点、置信区间或重复运行。

## 对 AegisKV 的具体启发

第一条 Insight 可以先限定为：**角色、执行阶段和输入规模为阶段耗时提供可预测结构，从而支持随进度更新完成时间估计。** 不应把它直接写成“所有 agent 的完整执行时间都能准确预测”。

若要支持更强的原始目标，应将剩余时间分解为可见的执行阶段，并为未知的循环次数、工具等待和服务排队单独建模：

1. 对已知角色／任务阶段，学习 `模型 + 输入规模 + 已完成轮次 + 工具状态 + 当前服务负载 → 下一阶段耗时`。训练标签可以使用事后结果，预测输入不能使用本次未来输出 token 数或最终轮次。
2. 结合当前已知计划，预测剩余阶段数量；动态分支只使用当前可见状态和历史转移统计。不能直接读取完整执行日志中的未来 DAG。
3. 每次请求／工具返回时更新整个 agent 的剩余墙钟时长，同时保留入口预测。单阶段成本误差、剩余阶段数量误差和最终剩余时间误差分别报告。

建议新实验先固定角色／任务模板和拆分规则，按完整 workflow 隔离训练、验证和测试；重复任务内容也应整组划分。调参只在验证集完成。测试集中保留失败、超时和长尾的处置记录，不因误差大小筛选样本。对各角色报告样本量、秒级 MAE、逐 agent 归一化误差的中位数/P90，以及全体覆盖率。

最终需要的 Figure 3(a) 宜画 **独立测试集的实际剩余时间与预测剩余时间**，带 `y=x` 和明确的误差带；或者画完整的误差 CDF。若存在多次在线更新，应按 agent 聚合或按固定的、在线可判定的事件取点，不能把同一个 agent 的几十次快照当作几十个独立样本。图外图注给出拆分方式、n 与角色定义。

## 当前数据的缺口

现有 `design-insights/agent-episodes.jsonl` 中全部角色是 `Subagent`。旧 CC 诊断仍保留，不能用更换图型消除其负面结果。检查到的 FanOutQA 实机 pilot 则用 `ignore_eos=true` 和固定生成长度，属于受控执行，不能冒充自然多轮 agent 的预测实验。旧的单 agent 准确预测案例也不能替代独立群体评估。

要补全证据，需要真实的角色／任务类型、模型与输入、计划和阶段状态的揭示时间、请求与工具起止时间，以及独立 workflow 标识。只有得到这些日志并验证后，才能用 AegisKV 自身的预测散点或误差分布替换本候选。
