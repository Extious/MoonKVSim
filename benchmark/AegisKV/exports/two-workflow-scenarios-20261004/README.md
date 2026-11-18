# 两个 workflow 场景：并行 Agent DAG 与连续多轮

状态：依据当前论文任务图语义构造的应用场景示意。尚未实现或采集这两个应用；没有实测时间、token 数、KV 驻留量或性能结论。图没有使用旧实验结果，也没有替换当前论文中的图。

本图保留为简单并行结构基线。新增的局部汇合、共享前驱和跨层依赖候选见[复杂 workflow DAG](../complex-workflow-dag-20261004/README.md)。

## 图和论文语义

- W1（论文证据问答）：A 方法分析、B 实验与证据、C 局限与条件从准备好的论文与问题并行开始；D 等待三者整个任务完成后整合证据并回答。
- W2（多文档新闻摘要）：E 事件与时间线、F 来源与事实并行；G 等待 E/F 完成后进行事实对齐与冲突分析；H 等待 G 完成后撰写并修订摘要。
- 外层大框是 Agent 任务，小框是该 Agent 的 invocation；例如 A 框内的 `1 → 2 → … → R` 等价于 `A(1) → A(2) → … → A(R)`。`R` 是该 Agent 自己的最终调用次数，不表示所有 Agent 轮数相同；省略号表示可继续迭代，不指定固定轮数。
- 实线为同一 Agent 内部的连续调用。虚线为输入或跨任务依赖；连接 Agent 大框的边表示整个前驱任务完成，不表示一轮结束便可启动后继。菱形标明 AND 汇合，要求所有输入任务完成，不是条件选择；小圆点表示分叉。
- 蓝色区域中的 Agent 是互无前后依赖的并行分支，置于同一 DAG 层。W1 有三个并行分支 A/B/C，W2 有两个 E/F；G/H 构成汇合后的串行阶段。不能将 A、B、C 或 E、F 在编排器中串行运行。
- 绿色条带表示已生成、前缀兼容时可复用的历史 KV；斜线条带表示本轮新增 KV。条带长度仅作示意，不代表 token 数、缓存命中率或物理驻留量。
- 这是任务依赖图；纵向位置不代表实际开始时间。两个 workflow 的不同任务与不同轮次可以被服务端调度，但图没有指定 GPU 执行顺序。

## 连续多轮的应用约束

每个 Agent 开始前一次性收到其外部依赖所需的材料。在自己的任务内部，只使用本地已有材料、之前的模型输出及本地检查结果；没有等待其他 Agent、用户输入、在线搜索或外部工具的步骤。

一轮返回后，本地编排器追加该轮接受的输出，检查任务完成条件；若尚未完成，追加下一轮任务说明并立即提交下一次调用。同一 Agent 同时最多有一个未完成调用。后继 Agent 在前驱整个任务完成后才启动，不插入前驱的内部调用链。

| Agent | 第一轮产物 | 后续调用的实际工作 |
| --- | --- | --- |
| A 方法分析 | 问题相关的方法及来源位置 | 对照原文检查假设、步骤和遗漏，必要时修订 |
| B 实验与证据 | 相关实验设置、结果与证据表 | 逐项核对结果支持的论点、比较条件及缺失证据 |
| C 局限与条件 | 适用条件和限制清单 | 复核反例、证据边界与遗漏，形成有来源支持的清单 |
| D 证据整合与回答 | 基于 A/B/C 输出的答案草稿 | 对照证据复查问题覆盖、来源支持和冲突，修订答案 |
| E 事件与时间线 | 多文档事件及时间线草稿 | 复核事件顺序、重复与遗漏，修订时间线 |
| F 来源与事实 | 按来源整理的事实记录 | 核对事实的出处、实体对应及未解决的分歧 |
| G 事实对齐与冲突 | 基于 E/F 的对齐记录和冲突清单 | 回查已有原文与记录，区分可解决冲突和需保留分歧 |
| H 摘要撰写与修订 | 基于对齐记录的摘要草稿 | 检查覆盖、事实支持、分歧表达与重复，修订摘要 |

上表为待实现的工作安排；复查必须有实际任务需要，不能为增长 KV 添加无意义调用。若运行后某个角色自然只有一轮，应记录该事实并调整应用范围，而不能把它伪装成多轮。

历史使用同一 `workflow_id` / `agent_id`，按发生顺序追加；不能每轮重写开头、仅保留最近输出或更换 Agent 身份。仍需核对后端实际 token 序列：消息累计本身不保证 token 前缀一致，也不保证 KV 仍在 HBM。

应用结构能约束“下一轮无需等待外部依赖”，但不能保证 GPU 执行没有间隔。实际采集需要同一时钟域中的 `call_complete`、`next_call_submit`、`next_call_start`，分别报告：

```text
本地衔接间隔 = next_call_submit - call_complete
服务端排队时间 = next_call_start - next_call_submit
```

按全部同 Agent 的相邻调用检查间隔及依赖事件，不预设未测量的毫秒阈值。失败、重试与超时单独记录；有外部等待的样本不能标为无外部等待。端到端 workflow 计时仍包括本地处理和服务端排队。

## 分支必须实际并行

任务 DAG 提供并行条件，执行还取决于编排与服务资源。新应用必须先启动所有独立分支，再等待其完成；不能在循环中 `await` 完一个分支才启动下一个。以下是待实现的编排约束示例，不是已经运行的应用代码：

```python
# run_agent 内按同一 Agent 身份顺序执行各轮调用。
a, b, c = await asyncio.gather(
    run_agent("A", paper, question),
    run_agent("B", paper, question),
    run_agent("C", paper, question),
)
answer = await run_agent("D", paper, question, a, b, c)

e, f = await asyncio.gather(
    run_agent("E", documents),
    run_agent("F", documents),
)
aligned = await run_agent("G", documents, e, f)
summary = await run_agent("H", documents, aligned)
```

资源设置至少提供两个可独立执行的 DP 实例，并允许不同分支同时进入不同实例；若要求 W1 三条分支都同时执行，应提供至少三个。一个 TP 组的多个 rank 共同执行同一次推理，不能将其计为多个独立 Agent 执行实例。`asyncio.gather` 只建立并发提交，不能单独证明模型执行并行。

新 trace 必须记录分支的调用开始/结束及实际 worker 身份，核验不同 Agent 在独立执行实例上的服务区间存在交集。仅有任务存活区间、请求提交区间或排队区间重叠不足以证明模型服务重叠；如需声称 GPU 内核物理同时执行，再用设备时间线核验。没有执行重叠的配置不能作为并行主场景；相关失败或边界运行仍保留并报告。

并行与 AND 汇合使恢复延迟对 WCT 的影响取决于其他分支的剩余工作。例如，在独立资源且恢复不扰动其他分支的分析条件下，设当前剩余时间为 `r_A, r_B, r_C`，仅 B 增加恢复延迟 `d_B`，则汇合延迟增量为：

```text
Δjoin = max(r_A, r_B + d_B, r_C) - max(r_A, r_B, r_C)
```

这解释了为什么要保留有不同剩余工作量的并行分支。实际分支时间、Slack 及故障对其他分支的资源影响都要重新采集，不能仅根据 DAG 形状预设正 Slack。多个分支共同失效或共用恢复资源时，应按共同故障与完整调度重新计算，不能套用上述单分支增量。

## 交付与复现

- 可编辑源：[sources/two-workflow-scenarios.drawio](sources/two-workflow-scenarios.drawio)，第 1 页中文、第 2 页英文，每页包含两个场景。
- 场景约束：[sources/scenario-contract.json](sources/scenario-contract.json)。
- 中文图：[two-workflow-scenarios-zh.pdf](two-workflow-scenarios-zh.pdf)、[PNG](two-workflow-scenarios-zh.png)。
- 论文英文图：[two-workflow-scenarios-en.pdf](two-workflow-scenarios-en.pdf)、[PNG](two-workflow-scenarios-en.png)。
- 原生导出保留为 `*.drawio.pdf/png/svg`；最终 PDF 为 168 mm 宽的矢量图，PNG 为同一 PDF 的渲染。
- 复核记录：[FIGURE_REVIEW.json](FIGURE_REVIEW.json)。实际尺寸预览在 `review/`，包含彩色与灰度版本。

在项目根目录运行：

```bash
.venv/bin/python benchmark/AegisKV/exports/two-workflow-scenarios-20261004/build_two_workflows.py --output benchmark/AegisKV/exports/two-workflow-scenarios-20261004/sources/two-workflow-scenarios.drawio
python benchmark/AegisKV/exports/two-workflow-scenarios-20261004/render_two_workflows.py --language zh
python benchmark/AegisKV/exports/two-workflow-scenarios-20261004/render_two_workflows.py --language en
python benchmark/AegisKV/exports/two-workflow-scenarios-20261004/prepare_final_size.py
```

字体配置只对本目录导出进程生效。中文使用 FandolSong，英文使用 Linux Libertine O；配色沿用当前论文图的绿色、蓝色与赭色。

## 建议图注

中文：两个包含并行分支的文档分析 workflow DAG 构造示例。外层框为 Agent 任务，内层编号为同一 Agent 的连续调用。W1 的 A/B/C 与 W2 的 E/F 分别并行推进；后继任务仅在所需前驱任务全部完成后开始。实线表示同 Agent 调用依赖，虚线表示输入或跨任务依赖，小圆点表示分叉，菱形表示 AND 汇合。KV 条带仅示意前缀兼容时的历史复用与新增量。轮数因 Agent 而异；图不是实测执行重叠或 GPU 时间线。

English: Constructed DAG examples of two document-analysis workflows with parallel branches. Outer boxes denote Agent tasks; numbered inner nodes denote consecutive invocations of the same Agent. A/B/C in W1 and E/F in W2 progress in parallel, and successors start only after all required predecessor tasks finish. Solid arrows denote intra-Agent invocation dependencies, dashed arrows denote input or inter-task dependencies, dots denote forks, and diamonds denote AND joins. KV bars illustrate compatible historical prefixes and newly generated KV. Invocation counts vary by Agent; execution overlap and GPU timing are not measured in this schematic.
