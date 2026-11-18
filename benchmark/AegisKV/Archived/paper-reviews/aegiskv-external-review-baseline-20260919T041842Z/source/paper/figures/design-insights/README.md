# System Design：三项前提与证据

**当前 Figure 3(a) 已改为已有研究的预测能力证据：** 使用
`../agent-time-literature/agent-predictability-panel.pdf`，当前三联图为
`../agent-time-literature/figure3-row.pdf`。采用 Heddle Figure 13 的真实
轨迹长度相关性；[完整来源与复现](../agent-time-literature/README.md)。
下文 early-agent / agent-time-audit 的 CC 结果仍完整保留，均为历史诊断。
更新 (b)/(c) 后运行 `render_agent_prediction_literature.py` 刷新当前三联图。

**2026-09-18 Figure 3(a) 更新：** 正文现使用
`../agent-time-early/agent-time-panel.pdf`，三联图预览在
`../agent-time-early/figure3-row.pdf`。新实验在第二次 LLM 请求到达、第一次
已完成时，每个 agent 取一个样本；1,443 agents / 170 workflows，误差除以
真实剩余时间，GBDT/历史中位数的中位误差为 75.9%/76.2%。详见
[新图说明](../agent-time-early/README.md)。下文 (a) 的 `agent-time-audit`
及 1,688-agent 结果保留为原诊断，统计口径不同，不再是正文 Figure 3(a)。
更新 (b)/(c) 后运行新说明中的 `--render-only` 命令刷新当前三联图。

当前正文：`../../sections/design_insights.tex` 与 `../../draft/system_design.md`。
Figure 3 使用三个 0.32 × textwidth 的 `subfigure`，放在一个 `figure*` 中；总宽 7 inch / 177.8 mm，每张原生尺寸 2.24 × 1.85 inch；当前图内采用与正文一致的 Linux Libertine，原生字号 10.05 pt。
2026-09-18 两轮紧凑版将面板高度从 2.65 inch 经 2.05 inch 调为 1.85 inch，较上一轮再降低约 10%，通过两行图例、较短轴名和留白重排实现；不对旧图非等比缩放，也不减小字号。图例中的 GBDT、Median、P90 分别对应下表的完整方法名；Block、Token、Compressed 表示稀疏分支的 top-k 选择单位。40% 预算和覆盖率的去重需求分母仍在图注及下文定义。
按 2026-09-18 用户纠正，图内不显示 `Workflow-disjoint test`、`Representative releases`、`Past 512 → next 64 queries` 这些额外说明；相应方法与条件仍在正文和图注中。预算敏感性图的相同页脚也已删除。
排布与叙述过渡参考 [RcLLM](https://arxiv.org/pdf/2605.07443) 的 §II-C / Figure 3，不复用其实验数据。

**第一项还没有得到正面验证。** 这组图是可审阅的证据初稿，不能作为“三项均已证实”的投稿结论。

| 面板 | 输入与统计单位 | 当前可支持的结论 |
|---|---|---|
| (a) `agent-time-audit` | CC/Weka 1,688 个已完成 agent，174 个 workflow；五折按 workflow 隔离 | 这次诊断的时间预测误差较大，不能证明准确预测；原角色标签全部是 `Subagent` |
| (b) `sparse-attention-survey` | 十个选定版本的官方发布公告 / 模型卡 / 仓库日期 | 长上下文模型已有稀疏机制采用实例，不是部署占比或增长率 |
| (c) `retry-kv-prediction` | NOSA-3B、MiniCPM4-8B、SeerAttention-Qwen3-8B，各三份 PG19 文档，各一次原生选块捕获 | 过去选块可改善留出尾部的去重 KV 覆盖，NOSA 改善大，MiniCPM4 与 Seer 改善小 |

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

按用户 2026-09-18 的确认，当前 §3.3 采用 GBDT 预测剩余时间，再用 CPM 计算 Slack（算法 1）。本图的 Median/P90 保留为原诊断基线，P90 使用整个训练折、全体同角色样本，其目标也不是最小 MAE。本轮算法整理未改变图的数据或重新训练模型：图中的 GBDT 结果不能验证新增执行段定义、完整 Tracker 或后续保护决策，五折结果也不是按时间推进的部署验证。

要得到用户所需的正面 Insight，需要带有明确角色/任务类型的重复执行记录，独立 workflow/时间段测试，报告预测区间覆盖与保护层级误判，并同时保留工具延迟与慢尾部。Pythia 的角色相关输出长度可以解释 profiling 动机，不能替代整个 agent 的执行时间证据。

## (b) 模型采用情况

Figure 3(b) 已用找回的 `../motivation-sparse-releases.{png,pdf,svg}` 重排替换。保留“发布时间—原生上下文”坐标、三种 marker 与最大上下文阶梯；原生宽从 7 inch 改为 2.24 inch，长模型名转为点编号并在图注中列出，重排时字体为 10.25 pt，后续字形调整见下文。旧原图仍保留。

逐条数据与原始来源见 `../../../experiments/data/design-insights/sparse-releases.json`，核对日期 2026-09-18。1–10 依次为 MiniCPM4、MiniCPM4.1、DeepSeek-V3.2-Exp、DeepSeek-V3.2、GLM-5、MiniCPM-SALA、DeepSeek-V4 preview、MiniMax-M3、GLM-5.2、LongCat-Flash-Lite-Sparse。

- MiniCPM4/4.1 使用原生 32K/64K，不以 RoPE 外推的 128K 代替。
- GLM-5 日期采用官方模型仓库的 2026-02-11，旧图为次日公告日期；GLM-5.2 与 LongCat 采用官方仓库日期。仓库初始记录不保证等于公开公告时刻，图注统一说明 release/model-card dates。
- SALA 为 25% InfLLMv2 与 75% 线性注意力；DeepSeek-V4 为 CSA + HCA。marker 仅代表其稀疏分支，不能读作所有层采用同一 top-k。
- 灰阶梯仅是这十个入选版本的上下文最大值；既不是完整模型普查，也不是市场采用率。
- K/M 使用来源的名义长度，K=1024，1M=1024K。模型采用实例不代表 AegisKV 已支持所有架构。

## (c) 因果的 retry KV 预测

分析脚本验证每个原生 NPZ 的 SHA-256 与捕获 `run.json` 一致。输入根目录：

- `experiments/native-sparse/20260915-nosa-3b`：NOSA-3B，32 层；
- `experiments/native-sparse/20260915`：MiniCPM4-8B，32 层；
- `experiments/native-sparse/20260918-seer-qwen3`：SeerAttention-Qwen3-8B，36 层；
- `experiments/native-sparse/20260914`：NOSA-1B，28 层；保留在 CSV/JSON 中，2026-09-18 起不再放入主图，以增加机制多样性。

每个模型均使用 PG19 10146、10321、10356 三份文本及各自 tokenizer，32,768-token 历史与一次 512-token 后续前向。选块信息来自训练模型真实前向的原生 selector，非人工 QK/top-k 数据。预测只看 1-based Query 32,257–32,768；验证只看 Query 32,769–32,832。预测与目标不重叠。

Seer 使用 Qwen/Qwen3-8B 加载 [jiwonsong 的实验性 SeerAttention Prefill gate](https://huggingface.co/jiwonsong/SeerAttention-Qwen3-8B-AttnGates)，采用发布者实现中的原始 block-sparse 后端。它不是官方 SeerAttention-R 的 Decode gate，也没有使用 CompactAttention 的 block-union 后端。保留 gate 配置的阈值 0.001 与 YaRN，关闭末尾两个 Query 块强制 dense 的可选规则，使截断 retry 不改变这条规则。采集的是实际传入原生 kernel 的 `[query head, 64-query block, 64-key block]` mask；频次计数按每个 Query 块包含 64 个 Query 展开，预测/目标边界均对齐 Query 块。基座、gate、代码的固定 revision 与完整加载校验见[采集说明](../../../experiments/native-sparse/20260918-seer-qwen3/README.md)。短前向的 observer 开/关 logits 最大差为 0；三份文本的全部 36 层及最终 logits 均为有限值。这些检查不验证模型回答质量。

预测对象为包含所有 KV heads 的 `(layer, 64-token block)`。目标分母为后 64 个 Query 的去重历史块并集；新重算出的尾部 KV 不进入历史 KV 分母。每层选择 `ceil(budget * 512)` 个历史块，预算包含模型所需的强制 sink 与局部窗口，两个策略使用相同强制集合；Seer 没有固定 sink/local 预留块。剩余槽分别用过去选中频次（同频时最近优先）或最近位置填充。40% 是各自模型的历史 KV 字节比例（每层 205/512 块），同模型内两个策略的字节预算相同；不同模型的绝对字节数与注意力密度没有被强行对齐。

每份文档先将所有层已覆盖块数相加，除以所有层所需块数之和；同一模型每块字节数相同，故等于需求字节覆盖率。再对三份文档等权平均。误差线仅为三份文档最小–最大值，不是置信区间。每个模型/文档仅一次完整捕获；预算点不是独立重复。

| 模型 | 历史频次，40% 预算 | 最近优先，40% 预算 | 改善 |
|---|---:|---:|---:|
| NOSA-3B | 77.82% | 59.73% | +18.09 pp |
| MiniCPM4-8B | 53.57% | 50.93% | +2.64 pp |
| SeerAttention-Qwen3-8B | 43.02% | 41.96% | +1.06 pp |

Seer 的跨 Query/head 去重需求覆盖平均 92.53% 的历史层/块对象，文档范围为 91.05%–94.18%。40% 预算下，其逐层 oracle 覆盖也只有 43.28%；频次排名接近这个上界，但相对最近优先的收益仅 1.06 个百分点。不能把这个结果表述成强稀疏需求或普遍的大幅收益。未根据结果调整阈值或筛选文档。归档 NOSA-1B 仍为 79.19% 对 59.72%，原有三个模型的所有逐文档/逐层分析值均未改变。

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

本次替换 (c) 使用 `render_design_insights.py --only-retry`，保留 (a)/(b) 文件。Seer 采集、独立复算、旧值不变检查与最终论文页复核见 `output/pdf/aegiskv-seer-insight-20260918/`。现存 `retry-kv-budget` 是原模型组合的归档图，不是本次主图的同步导出；重建时才会采用新的三模型组合。

第二轮紧凑排版同时补齐正文对三个子图的引用；检查十个发布编号、轴名及图例间隔，数据与字号未改。核对记录见 `output/pdf/aegiskv-design-followup-20260918/`。

## 图内字体调整（2026-09-18）

用户明确指出 Figure 3/5 的部分文字显得过大。本轮保持两图尺寸与数据，将 DejaVu Sans 的 10.25/10.5 pt 改为正文使用的 Linux Libertine、10.05 pt；Figure 5 仅面板字母加粗，策略名恢复常规字重。缩小的是字号与字面的视觉分量，未再次压低画布。共享配置在 `experiments/scripts/paper/design_plot_typography.py`，通过 `kpsewhich` 使用 LaTeX 安装内的 Libertine OTF；清单记录字体及配置哈希。最终尺寸的字体和实际论文页检查见 `output/pdf/aegiskv-design-typography-20260918/`。
