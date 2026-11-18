# 复杂 workflow DAG：局部汇合、共享前驱与跨层依赖

状态：2026-10-04 构造的两种文档应用方案，尚未实现或实测。按用户最新要求，图仅展示 Agent 节点与协作依赖，已移除内部调用、KV 条带、输入块和图例。每个节点表示完整 Agent 任务，箭头表示前驱任务完成后提供材料；同一 Agent 连续多轮的要求保留在应用约束中。图的排版位置不表示执行时间。

来源核查支持论文审阅、新闻信息综合的应用类别及部分常见协作模式；7/8 个 Agent 的具体角色和全部依赖边均由本项目设计，不是引用来源的原图。当前可以声称“实例化常见协作模式”，具体 DAG 与运行特征的典型性尚未建立，详见[典型性 claim 与依据](CLAIM_EVIDENCE.md)。原来的[简单并行 DAG](../two-workflow-scenarios-20261004/README.md)保留作结构基线；没有更改当前论文。

## W1：论文审阅报告，7 个 Agent

输入是完整论文和审阅要求，输出是有来源支持的审阅报告。每个角色基于自己开始时收到的材料连续多轮生成、核查和必要修订。

| Agent | 工作 | 必须完成的前驱及其提供的材料 |
| --- | --- | --- |
| A 方法与主张分析 | 提取方法、假设和作者主张，核查原文定位 | 无；使用准备好的论文 |
| B 实验与证据分析 | 提取实验设置、比较、结果与证据，核查遗漏 | 无；使用准备好的论文 |
| C 适用条件分析 | 整理研究对象、适用条件及任务边界，核查条件表述 | 无；使用准备好的论文 |
| D 主张与证据匹配 | 检查每个方法主张由哪些实验支持，形成支持/缺口记录 | A 的主张与 B 的实验证据 |
| E 证据边界审查 | 检查实验支持在给定条件下的可靠性与外推边界 | B 的实验与 C 的适用条件 |
| F 论证草稿 | 根据支持/缺口记录组织审阅论证并明确适用条件 | D 的匹配记录与 C 的条件；不等待 E |
| G 评审与修订 | 用独立证据边界审查校核草稿，生成并修订最终报告 | F 的草稿与 E 的审查 |

依赖边：`A→D, B→D, B→E, C→E, D→F, C→F, F→G, E→G`。

这里 B 的结果被 D/E 共同使用，C 的条件同时供 E/F 使用；C→F 和 E→G 跨越图中的层。A/B 完成后 D 就可启动，即使 C 仍在执行；C/D 完成后 F 就可启动，即使 E 尚未完成。图中的层是排版层，不是同步阶段。

## W2：多源新闻综合，8 个 Agent

输入是准备好的多篇新闻文档和报道要求，输出是注明来源、事件背景及未解决分歧的报道。没有在线检索、用户追问或外部工具等待。

| Agent | 工作 | 必须完成的前驱及其提供的材料 |
| --- | --- | --- |
| H 时间线分析 | 逐文档提取并复核事件顺序 | 无；原始文档 |
| I 来源与事实分析 | 整理各来源的事实、出处和差异，复核定位 | 无；原始文档 |
| J 背景条件分析 | 提取并复核事件背景、实体关系与适用范围 | 无；原始文档 |
| K 事件归并 | 按来源将时间线中的重复事件对齐，保留分歧 | H 的时间线与 I 的事实来源 |
| L 背景梳理 | 根据来源支持组织背景解释，检查条件是否充分 | I 的来源记录与 J 的背景条件 |
| M 报道草稿 | 基于归并事件和背景条件写出并修订报道草稿 | K 的事件与 J 的条件；不等待 L/N |
| N 证据一致性核查 | 检查归并事件与背景解释是否相容，形成证据问题清单 | K 的事件与 L 的背景解释；不等待 M 草稿 |
| O 整合修订 | 用证据问题清单校核草稿，生成并修订最终报道 | M 的草稿与 N 的核查 |

依赖边：`H→K, I→K, I→L, J→L, K→M, J→M, K→N, L→N, M→O, N→O`。

I 向 K/L 提供共享来源，K 向 M/N 提供共享事件。M 在 K/J 完成后可以与仍未完成的 L 并行；M/N 也互无依赖。N 检查的是证据记录，不是尚未完成的 M 草稿，因而没有隐藏的 M→N 依赖。O 完成二者的合并与修订。

## 相比单个 fan-out / fan-in 的区别

- 有多个局部汇合点；各节点等待的前驱集合不同，没有全层屏障。
- 同一个前驱输出供多个下游使用，故障可影响多个后续路径。
- 跨层依赖连接原始分析与后续撰写，调用阶段可以交错。
- 可并行的 Agent 不限于图中的同一排；当前关键路径取决于整条剩余 DAG 与实际时长。

不通过增加冗余传递边制造复杂性。所有画出的任务边都是不可由其他路径替代的直接依赖，并由表中具体材料解释。节点与边数是设计参数，不是实测工作负载统计。角色是否必要及是否有足够有意义的多轮过程，仍需真实运行与输出质量验证；不合格或天然单轮角色必须如实报告。

## 连续多轮与运行约束

每个 Agent 的全部外部依赖在第一轮前已收到。内部 `1→2→…→R` 使用同一 Agent 身份，追加之前接受的输出、已有材料和下一轮说明；没有与其他 Agent 逐轮互相反馈。同一 Agent 同时最多有一轮未完成，轮数未知并依任务停止条件产生。需要分别核对实际 token 前缀与 KV 驻留，不能用消息累计代替缓存命中测量。

编排器按本节点的前驱完成情况启动任务，而不是先 `gather` 一整排 Agent。以下仅是调度语义示意，实际模型应用尚未实现：

```python
async def execute_task(agent):
    inputs = await asyncio.gather(*(tasks[p] for p in predecessors[agent]))
    # run_agent 在任务内部连续执行自己的各轮。
    return await run_agent(agent, inputs, prepared_documents)

tasks = {}
for agent in topological_order:
    tasks[agent] = asyncio.create_task(execute_task(agent))
result = await tasks[final_agent]
```

这仍需要真实服务并行资源。使用独立 DP 实例验证不同 Agent 服务区间重叠；三个初始 Agent 全同时执行需要三份独立执行资源。至少两个实例可验证部分执行重叠。TP rank 不作为独立实例；并发提交、队列区间和任务存活区间均不能代替服务重叠证据。每轮的衔接、排队、服务时间和 worker 身份仍需完整记录。

## 框架能力与边界

2026-10-04 检查了 [AutoGen GraphFlow 官方文档](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/graph-flow.html)：支持有向图、顺序/并行/条件/循环，以及按输入激活组区分 all/any。它是可参考的编排能力，不证明本文两个任务应用已经实现或满足连续多轮要求。当前选用的图全部是固定 DAG、全前驱完成语义，没有条件激活、动态增加 Agent 或跨 Agent 回环。

[LangGraph Graph API 官方文档](https://docs.langchain.com/oss/python/langgraph/use-graph-api)说明并行节点按 superstep 执行；列表形式的多前驱边、分别添加的边和 `defer=True` 有不同触发行为，后者等待全图不再有待执行任务。若用该框架适配本图，需要核验局部就绪是否被 superstep 或全局等待改变，不能直接把图拓扑当作运行语义。尚未确定或接入具体框架。

## 对 AegisKV 的作用

这些图可检查 Tracker 是否根据完整剩余 DAG 更新完成时间与 Slack。例如 B 同时影响 D/E，K 同时影响 M/N；其恢复延迟会传播到多个路径。E 的耗时增加可能改变 W1 中经 E→G 的路径是否决定完成时间，而 F 可以在 E 尚未完成时推进。上述都是依赖推论，不是已观察到的关键路径切换或恢复收益。

简单拓扑保留为边界基线。正式 workload 必须由真实应用需求、执行特征与输出质量确定，不能为得到正 Slack、长 KV 或明显恢复收益而加角色、等待或填充。当前两图的代表性、多轮数量、执行重叠与性能仍待验证。

## 图源、导出与复现

- [可编辑图源](sources/complex-workflow-dag.drawio)：第 1 页中文，第 2 页英文。
- [设计约束](sources/scenario-contract.json)、[图复核](FIGURE_REVIEW.json)、[DAG 检查](review/dag-checks.json)。
- [中文 PDF](complex-workflow-dag-zh.pdf)、[中文 PNG](complex-workflow-dag-zh.png)。
- [英文 PDF](complex-workflow-dag-en.pdf)、[英文 PNG](complex-workflow-dag-en.png)。

PDF 按 168 mm 宽放置；`review/` 含同宽彩色与灰度预览。全部箭头采用同一种深色实线表示任务完成依赖；交叉处用跨线弧表示没有连接，依赖由箭头端点决定。每个多输入 Agent 等待其所有前驱。

```bash
.venv/bin/python benchmark/AegisKV/exports/complex-workflow-dag-20261004/build_complex_workflows.py --output benchmark/AegisKV/exports/complex-workflow-dag-20261004/sources/complex-workflow-dag.drawio
python benchmark/AegisKV/exports/complex-workflow-dag-20261004/verify_dag.py
python benchmark/AegisKV/exports/complex-workflow-dag-20261004/render_complex_workflows.py --language zh
python benchmark/AegisKV/exports/complex-workflow-dag-20261004/render_complex_workflows.py --language en
python benchmark/AegisKV/exports/complex-workflow-dag-20261004/prepare_final_size.py
```

生成器复用相邻 `two-workflow-scenarios-20261004/build_two_workflows.py` 中的绘图基础类和配色，不依赖旧实验。复核文件记录这项源码依赖的哈希。

图注：论文审阅与多源新闻综合的 Agent 协作依赖。每个节点表示一个完整 Agent 任务；箭头表示材料依赖，目标任务在全部直接前驱完成后就绪，排版层没有全局屏障。两图是本项目设计的应用方案，实例化并行分析、证据整合与阶段性核查修订；具体拓扑及执行特征的代表性仍待验证。
