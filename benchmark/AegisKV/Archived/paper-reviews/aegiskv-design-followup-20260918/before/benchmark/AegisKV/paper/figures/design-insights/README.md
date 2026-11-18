# System Design：三项前提与证据

当前正文：`../../sections/design_insights.tex` 与 `../../draft/system_design.md`。
Figure 3 使用三个 0.32 × textwidth 的 `subfigure`，放在一个 `figure*` 中；总宽 7 inch / 177.8 mm，每张原生尺寸 2.24 × 2.05 inch，字体 10.25 pt。
2026-09-18 紧凑版将面板高度从 2.65 inch 降低约 23%，通过两行图例、较短轴名和留白重排实现；不对旧图非等比缩放，也不减小字号。图例中的 GBDT、Median、P90 分别对应下表的完整方法名；Block、Token、Compressed 表示稀疏分支的 top-k 选择单位。40% 预算和覆盖率的去重需求分母仍在图注及下文定义。
按 2026-09-18 用户纠正，图内不显示 `Workflow-disjoint test`、`Representative releases`、`Past 512 → next 64 queries` 这些额外说明；相应方法与条件仍在正文和图注中。预算敏感性图的相同页脚也已删除。
排布与叙述过渡参考 [RcLLM](https://arxiv.org/pdf/2605.07443) 的 §II-C / Figure 3，不复用其实验数据。

**第一项还没有得到正面验证。** 这组图是可审阅的证据初稿，不能作为“三项均已证实”的投稿结论。

| 面板 | 输入与统计单位 | 当前可支持的结论 |
|---|---|---|
| (a) `agent-time-audit` | CC/Weka 1,688 个已完成 agent，174 个 workflow；五折按 workflow 隔离 | 这次诊断的时间预测误差较大，不能证明准确预测；原角色标签全部是 `Subagent` |
| (b) `sparse-attention-survey` | 十个选定版本的官方发布公告 / 模型卡 / 仓库日期 | 长上下文模型已有稀疏机制采用实例，不是部署占比或增长率 |
| (c) `retry-kv-prediction` | 三种真实权重模型，各三份 PG19 文档，各一次原生选块捕获 | 过去选块可改善留出尾部的去重 KV 覆盖，NOSA 改善大，MiniCPM4 改善小 |

`retry-kv-budget` 是原 Figure 5，沿用 (c) 的同一输入扩展预算曲线；2026-09-18 压缩设计章后移出正文，保留为后续 Evaluation 素材。当前 Figure 5 是恢复流水线。旧的集中度与覆盖图均保留；旧覆盖图按层等权平均且未明确强制块预算约束，不能与本次按需求块数加权的覆盖值直接混用。

## (a) 时间预测核对

原始 CC 源与 SHA-256 见 `../../../experiments/data/design-insights/agent-extraction.json`。
从 393 条 workflow、1,697 个已完成 subagent 中排除 9 个 episode/request 时钟不一致的记录，其余全部保留；无基于持续时间、预测误差、成功预测程度的筛选。
只用请求到达时已知的 elapsed、输入长度、已完成请求的输出/耗时以及已到达请求计数。未来请求数量、未来输出与 agent 完成时刻不作为特征。按 workflow ID 的固定哈希分五折，整条 workflow 不跨训练/测试。

固定 GBDT 参数：80 棵树、学习率 0.06、深度 3、叶子至少 32 个样本、32 bins；未对测试结果调参。模型训练以请求快照为行，较长 agent 提供更多训练行；CDF 的统计单位则是 agent。此差异属于当前诊断限制。训练使用同一原始角色标签，结果仅说明本次配置/特征的表现，不能证明所有预测器都不可行。

对 agent a：`NMAE(a) = mean_t(abs(predicted_remaining(a,t) - actual_remaining(a,t))) / total_duration(a)`；t 是该 agent 的请求到达时刻。共 41,854 个快照，但只形成 1,688 个 CDF 样本；这些 agent 仍嵌套在 174 个 workflow 内，并非全部独立实验。

| 估计方法 | 每 agent NMAE 的中位数 | P90 |
|---|---:|---:|
| Progress GBDT | 51.8% | 456.6% |
| 训练折持续时间中位数减已运行时间 | 49.3% | 393.7% |
| 训练折 P90 减已运行时间 | 424.3% | 2,258.8% |

P90 的目标是保守估计而非最小 MAE，三条曲线不是“当前 P90 算法输给 GBDT”的结论。这里的 P90 使用整个训练折、全体同角色样本，不等于线上最近 200 次/1 小时的实现。当前算法保持角色 P90 不变。五折结果也不是按时间推进的部署验证。

要得到用户所需的正面 Insight，需要带有明确角色/任务类型的重复执行记录，独立 workflow/时间段测试，报告预测区间覆盖与保护层级误判，并同时保留工具延迟与慢尾部。Pythia 的角色相关输出长度可以解释 profiling 动机，不能替代整个 agent 的执行时间证据。

## (b) 模型采用情况

Figure 3(b) 已用找回的 `../motivation-sparse-releases.{png,pdf,svg}` 重排替换。保留“发布时间—原生上下文”坐标、三种 marker 与最大上下文阶梯；原生宽从 7 inch 改为 2.24 inch，长模型名转为点编号并在图注中列出，字体维持 10.25 pt。旧原图仍保留。

逐条数据与原始来源见 `../../../experiments/data/design-insights/sparse-releases.json`，核对日期 2026-09-18。1–10 依次为 MiniCPM4、MiniCPM4.1、DeepSeek-V3.2-Exp、DeepSeek-V3.2、GLM-5、MiniCPM-SALA、DeepSeek-V4 preview、MiniMax-M3、GLM-5.2、LongCat-Flash-Lite-Sparse。

- MiniCPM4/4.1 使用原生 32K/64K，不以 RoPE 外推的 128K 代替。
- GLM-5 日期采用官方模型仓库的 2026-02-11，旧图为次日公告日期；GLM-5.2 与 LongCat 采用官方仓库日期。仓库初始记录不保证等于公开公告时刻，图注统一说明 release/model-card dates。
- SALA 为 25% InfLLMv2 与 75% 线性注意力；DeepSeek-V4 为 CSA + HCA。marker 仅代表其稀疏分支，不能读作所有层采用同一 top-k。
- 灰阶梯仅是这十个入选版本的上下文最大值；既不是完整模型普查，也不是市场采用率。
- K/M 使用来源的名义长度，K=1024，1M=1024K。模型采用实例不代表 AegisKV 已支持所有架构。

## (c) 因果的 retry KV 预测

分析脚本验证每个原生 NPZ 的 SHA-256 与捕获 `run.json` 一致。输入根目录：

- `experiments/native-sparse/20260914`：NOSA-1B，28 层；
- `experiments/native-sparse/20260915-nosa-3b`：NOSA-3B，32 层；
- `experiments/native-sparse/20260915`：MiniCPM4-8B，32 层。

每个模型均使用 PG19 10146、10321、10356 三份文本，32,768-token 历史与一次 512-token 后续因果前向。索引是训练模型真实前向的原生 selector 输出，非人工 QK/top-k 数据。预测只看 1-based Query 32,257–32,768；验证只看 Query 32,769–32,832。预测与目标不重叠。

预测对象为包含所有 KV heads 的 `(layer, 64-token block)`。目标分母为后 64 个 Query 的去重历史块并集；新重算出的尾部 KV 不进入历史 KV 分母。每层选择 `ceil(budget * 512)` 个历史块，预算包含强制 sink 与局部窗口，两个策略使用相同强制集合。剩余槽分别用过去选中频次（同频时最近优先）或最近位置填充。

每份文档先将所有层已覆盖块数相加，除以所有层所需块数之和；同一模型每块字节数相同，故等于需求字节覆盖率。再对三份文档等权平均。误差线仅为三份文档最小–最大值，不是置信区间。每个模型/文档仅一次完整捕获；预算点不是独立重复。

| 模型 | 历史频次，40% 预算 | 最近优先，40% 预算 | 改善 |
|---|---:|---:|---:|
| NOSA-1B | 79.19% | 59.72% | +19.47 pp |
| NOSA-3B | 77.82% | 59.73% | +18.09 pp |
| MiniCPM4-8B | 53.57% | 50.93% | +2.64 pp |

这只是等预算、单个留出窗口的排名评估，没有模拟完整准入/两窗口滞回。64 tokens 是保守的未提交重放后缀，可包含已密封但未提交块，不能把它精确叫作“未密封尾部长度”。已知 token ID、因果前缀和恢复后的 selector 状态相同时，捕获后缀的需求可作为 retry 的代理；当前没有执行故障注入或恢复一致性实验。PG19 也不能代替 agentic 代码与工具历史。旧层流水线图的校准参数未用本次固定预算排名诊断重新拟合。

## 复现

从仓库根目录：

```sh
# 时间分析较慢；冻结的原始源字节必须匹配 extraction 中的 SHA。
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/analyze_agent_duration_insight.py --extract
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/analyze_retry_kv_insight.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_design_insights.py
sh benchmark/AegisKV/paper/build.sh
```

图形有 PDF/SVG/PNG；SVG 的文本保持可编辑，数值必须通过 CSV 与绘图脚本修改后重新导出。`MANIFEST.json` 记录输入与生成器哈希。复核材料在 `output/pdf/aegiskv-design-insights/`，含修改前快照、分析日志、最终尺寸检查和论文实际页面。

默认绘图命令只更新正文三联图；需要重建已移出正文的 `retry-kv-budget` 时添加 `--include-budget`。紧凑布局的前后快照、最终尺寸复核及论文页见 `output/pdf/aegiskv-compact-figures-20260918/`。
