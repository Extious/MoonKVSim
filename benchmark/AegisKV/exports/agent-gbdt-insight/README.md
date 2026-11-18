# Agent 剩余时间：GBDT Insight 候选与证据边界

当前结果还不能支持“GBDT 能准确预测 Agent 剩余执行时间”。已经完成真实 CC 轨迹上的离线拟合、按完整 Workflow 隔离的五折预测，以及可复算的误差 CDF。图保留为诊断候选。按用户随后确认的章节安排，预测方法与文献讨论移到 3.3，准确率和鲁棒性留到后续 Evaluation；Figure 3 只保留两项 KV Insight，原 Heddle 面板移入归档。

## 当前图回答什么

在一个 Agent 的第二次 LLM 请求到来、第一次已经完成时，预测**该 Agent 当前任务结束前还剩多少秒**，其中包括后续多轮请求和中间等待。一个 Agent 在主图只出现一次。它不是下一次请求耗时预测，也不是剩余 token 数预测。

![第二次请求到来时，整个 Agent 剩余时间的预测误差 CDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/exports/agent-gbdt-insight/agent-remaining-error.png)

- 横轴：`100 × |预测剩余秒数 − 实际剩余秒数| / 实际剩余秒数`。0–100% 为线性，100% 以上为对数，保留全部长尾；`1k` 表示 1000%。
- 纵轴：误差不超过横轴阈值的 Agent 比例；相同误差阈值下越高越好。
- `Median`：仅从训练折中取相同模型、相同请求序号的剩余时间中位数；少样本组按协议回退。
- `GBDT basic`：当前模型、已观察请求序号、经过时间、当前输入长度代理。
- `GBDT + history`：在 basic 上加入上下文增长、历史输出、API 耗时、请求间隔及其均值、波动与最近三次观测。

可嵌入版本：[单栏 PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/exports/agent-gbdt-insight/agent-remaining-error.pdf)（3.34 英寸宽）；[历史紧凑尺寸候选](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/exports/agent-gbdt-insight/agent-remaining-error-compact.pdf)（2.24 英寸宽）。均为矢量图，另存 SVG；字号原生 10.05 pt，不建议继续缩小。

## 当前结果

主图包括 **170 个 Workflow 的 1,443 个 Agent**；同一个 Workflow 的所有 Agent、所有时点始终在同一折。训练可使用训练 Workflow 中每个已完成先前请求的到达时点，合计 36,901 个快照；每个 Agent 的训练快照权重之和相同。测试 Workflow 的任何快照都不进入其对应模型的训练。

| 方法 | 中位相对误差 | P90 相对误差 | 误差 ≤20% 的比例 | 平均绝对误差 |
|---|---:|---:|---:|---:|
| Median | 76.23% | 763.62% | 11.30% | 438.58 s |
| GBDT basic | 67.10% | 277.84% | 15.73% | 406.68 s |
| GBDT + history | 69.28% | 373.55% | 11.71% | 407.07 s |

加入历史后，相对 Median 的 MAE 降低约 7.18%，但按 Workflow 配对重采样的 95% 描述性区间为 **−0.81% 到 19.98%**，包含零。此区间固定了已训练模型，不包含重新训练的不确定性。basic 比增加历史的版本略好，所以不能声称“历史越多就一定越准”。所有方法的秒级 Pearson 相关性和 R² 在本数据上也没有显示有用的拟合；完整数值在 `summary.json`，没有只保留有利指标。

这一结果说明：**本次结构化统计特征与固定配置没有建立足够准确的早期预测器**。它既不证明所有 Agent 剩余时间不可预测，也不证明加入语义信息后一定能达到某个准确率。

## 逐 step 检查

![不同请求序号的预测诊断](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/exports/agent-gbdt-insight/agent-remaining-by-step.png)

各点分别评估到达该请求序号且先前调用已完成的 Agent：

| 当前请求序号 | Agent 数 | Workflow 数 | GBDT + history 中位相对误差 | 误差 ≤20% 的比例 |
|---|---:|---:|---:|---:|
| 1 | 1,688 | 174 | 65.12% | 13.15% |
| 2 | 1,443 | 170 | 69.28% | 11.71% |
| 5 | 1,302 | 167 | 67.16% | 16.05% |
| 10 | 952 | 160 | 63.80% | 16.70% |
| 20 | 624 | 130 | 62.22% | 16.19% |

这些点的合格 Agent 集合不同，不能把跨点变化解释为同一批 Agent 的预测必然随执行改善。横轴没有使用事后才知道的“总执行进度百分比”。连线仅辅助比较预先指定的离散检查点。

## 数据与方法

来源：[SemiAnalysis CC Weka traces](https://huggingface.co/datasets/semianalysisai/cc-traces-weka-062126)。本地冻结源有 393 个 Workflow、1,697 个 subagent group；原提取排除 9 个请求时钟与报告结束时间不一致的 group，留下 174 个 Workflow 的 1,688 个完整 Agent。第二个请求到来时排除 242 个首两次调用重叠的 Agent 和 3 个单请求 Agent，覆盖上述 1,688 个 Agent 的 85.49%。训练阶段另外跳过先前调用尚未全部完成的快照，未按误差或剩余时间阈值筛样本。

所有角色字段均为 `Subagent`。当前数据没有任务文本、角色语义、工具名称/结果、测试通过数等进展信号，也没有显式的工具完成事件；**第二次请求到来只是可观测预测时点，不等同于已经记录了第一次工具返回**。`in` 是 64-token hash-block 数量换算的输入长度代理，不是精确 token 长度。标签是数据源报告的整个 Agent 完成时间减预测时点，并未修改为最后一个 LLM 请求结束。

模型使用 scikit-learn 1.5.1 的 [HistGradientBoostingRegressor](https://scikit-learn.org/1.5/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html)，属于 GBDT。200 轮、学习率 0.05、最多 15 叶、叶子至少 40 样本，直接拟合剩余秒数的 absolute-error 损失。每折独立拟合类别编码；没有随机混合快照做 early stopping；没有在测试误差上调参。记录的全部十次拟合合计约 8.59 秒（本机、4 CPU 线程），此数字不含特征提取、重采样与绘图，不代表完整部署耗时。

这是**已有观测轨迹上的新离线预测评估**，不是模拟成功曲线，不是线上服务实验。当前已有旧 CC 诊断，因此也不属于从未看过该数据的全新盲测。没有按真实日期做时间外验证；不同 Workflow 是否属于重复任务或同一用户，现有匿名信息不足以完全审计。

## 要用于论文 Insight，下一张图应如何做

保持 GBDT 路线，优先补齐输入信息和评估数据，而非先规定成功曲线。

1. **数据单位仍然是整个 Agent。** 每个已观测 step 保存快照，标签为该 Agent 当前任务最终结束时刻减当前时刻。Agent 内的多轮请求不拆成多个预测目标；显式完成、失败和超时需分别记录，不能把截断轨迹当作成功完成。
2. **输入分成三组，做可解释的增量对照。** 静态信息包括角色、模型、任务类型与输入任务内容；运行统计沿用本次特征；任务进展包括已发生的工具类型/结果、测试通过/失败、重试数和当时可见计划的状态。文本可用冻结编码器转成向量后交给 GBDT，或者先采用已有结构化字段；不要求微调一个大语言模型。特征必须有事件时间戳，不能拿最终总结反推早期进展。
3. **冻结划分再拟合。** 按完整 Workflow 隔离，进一步按任务重复/模板审计，条件允许时用较早时间训练、较晚时间测试。标准 GBDT 的超参数只能在训练侧验证集确定；测试折不能用来挑特征、挑最好的一轮或挑好看的 Agent。
4. **后续 Evaluation 优先用误差 CDF。** 在有显式事件的轨迹上，于第一次 LLM+工具交互完成之后比较 `Median`、`GBDT runtime statistics`、`GBDT + task/progress`。全部方法使用相同 Agent；报告覆盖率、MAE、P50/P90 相对误差、预先约定阈值内覆盖率。没有实测的第三条线当前不绘制。该图不再安排到 Design Insights。
5. **逐 step 的结果作为补充。** 报告第 2/5/10 次请求到来等可在线判断的时点；同时报告各点样本覆盖。若比较同一批 Agent，必须预先定义配对 cohort 并注明只适用于长轨迹，避免用不同人群证明越预测越准。
6. **Insight 与系统收益分开。** 剩余时间预测误差支持预测信号是否可用；把预测输入 CPM 后，仍需另外验证错误正 Slack、关键路径排序与保护决策损失。它不能单独证明故障后的 WCT 收益。

适合未来图的论点是：*Observable task context and execution progress provide signals for estimating an agent's remaining completion time.* 只有新数据的持出误差支持时，才能进一步写明准确程度与范围。当前图适合方法诊断，不适合配上“预测已经准确”的正文。

## 当前候选的英文图注

> Whole-agent remaining-time prediction at the second LLM request arrival, after the first request has completed. Each of 1,443 Agents from 170 Workflows contributes one held-out prediction; five-fold splits isolate whole Workflows. Basic GBDT uses model, observed request index, elapsed time, and current input-length proxy; history adds completed-call and context-growth statistics. The target includes all remaining requests and intervening delays. Relative error is normalized by actual remaining time. The x-axis is linear through 100% and logarithmic thereafter, retaining the full tail. This statistics-only diagnostic exhibits substantial error and does not establish accurate early runtime prediction.

## 复现与文件

从仓库根目录执行：

```bash
OPENBLAS_NUM_THREADS=4 OMP_NUM_THREADS=4 python3 benchmark/AegisKV/experiments/scripts/paper/analyze_agent_gbdt_steps.py
python3 benchmark/AegisKV/experiments/scripts/paper/render_agent_gbdt_insight.py
```

- [评估脚本](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/scripts/paper/analyze_agent_gbdt_steps.py)
- [绘图脚本](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/scripts/paper/render_agent_gbdt_insight.py)
- [协议与来源](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/agent-gbdt-steps/protocol.json)
- [全部逐时点预测](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/agent-gbdt-steps/predictions.csv)
- [主图每个 Agent 的原始预测](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/agent-gbdt-steps/primary-landmark.csv)
- [全部汇总指标](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/agent-gbdt-steps/summary.json)
- [导出与哈希](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/exports/agent-gbdt-insight/MANIFEST.json)

图、脚本和诊断数据均在 `paper/` 外，保持 Overleaf 目录清洁。
