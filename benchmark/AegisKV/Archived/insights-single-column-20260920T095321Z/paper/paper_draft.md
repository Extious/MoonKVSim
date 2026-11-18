# 2. Background and Motivation

本节按“背景两部分 → 动机两部分 → 故障位置的 WCT 影响 → 引出 AegisKV”展开。下文与 `background_and_motivation.tex` 的叙述顺序一致，图号采用这次编译后的编号。

## 2.1 Background

**背景一：多智能体工作流成为重要的 LLM 应用形式。** 从编码助手和研究系统出发，介绍一个用户任务往往需要多个 Agent 协作。Agent 可以承担预先定义的角色，例如规划、开发或审查；也可以是为某个 subtask 临时创建的 subagent。一个 Agent 内部又可以包含多轮 LLM 请求、工具调用和结果处理，多个 Agent 之间形成串行依赖、并行分支和汇合。由此区分“一次请求完成”“一个 Agent 完成”和“整个用户任务完成”三个层次。

这一段用 [AutoGen](https://arxiv.org/abs/2308.08155)支持可定制角色与协作模式，用 [Anthropic 的多智能体研究系统](https://www.anthropic.com/engineering/multi-agent-research-system)支持主 Agent 按任务创建并行 subagent 的实际应用。正文采用“日益重要的应用形式”，不在缺少总体市场统计时声称已经占据多数 LLM 请求。顺带说明同角色请求可能复用兼容前缀，同一 Agent 的多轮工具交互则不断加入私有历史；具体缓存接口不在这里展开。

**背景二：大规模 LLM 部署使故障成为必须处理的问题。** LLM 服务通过大量 GPU worker 提供推理能力，一份模型副本还可能跨越多张 GPU。随着服务规模扩大，即使单个设备可靠，集群也必须处理设备和 worker 不可用的情况；这不意味着单卡故障率本身随规模上升。故障使相关副本无法继续服务，并失去对 GPU 上活跃 KV 的访问，健康副本既要接收转移的请求，也要恢复继续执行所需的状态。

这一段引用 [LUMEN](https://arxiv.org/html/2606.17787v1)说明服务规模下的故障、容量丢失与恢复问题，并用 [DéjàVu](https://proceedings.mlr.press/v235/strati24a.html)、[GhostServe](https://arxiv.org/html/2605.00831v1)说明 KV 复制与 checkpoint 已有直接研究。论文当前范围是 GPU/worker fail-stop，且控制状态、token 历史、备份存储与兼容恢复目标存活。到这里完成背景交代，再进入工作流目标和上下文增长两个动机。

## 2.2 Motivation

**动机一：以 WCT 为主要目标，不同 Agent 请求需要不同的保护优先级。** 先解释用户等待的是整个任务的必要结果，单独缩短一个请求或一个 Agent 的完成时间，未必能提前工作流结束。接着先展示 Figure 1(a) 的四分支例子，再介绍 Figure 1(b) 的数据集统计。

![Figure 1(a)：四分支工作流例子，原 Figure 1(b)](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/workflow.png)

[Figure 1(a) PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/workflow.pdf)

**Figure 1(a) 用于先建立直觉。** A2 在分支启动后的 151.6 秒完成，A1 在 60.4 秒完成。若 Main 的下一阶段需要全部分支结果，单独加速 A1 不会提前汇合，而延迟 A2 会推迟下游。其他分支可容忍的额外延迟不同，这种余量称为 Slack。图中的执行时间来自 trace；“需要全部分支结果”的依赖是本例明确采用的假设，不能只凭时间重叠认定为观测到的依赖。

![Figure 1(b)：Claude Code 工作流中的最大分支时长差分布，原 Figure 1(a)](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/workflow-gaps.png)

[Figure 1(b) PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/workflow-gaps.pdf)

**Figure 1(b) 在例子之后补充数据集证据。** 使用 [SemiAnalysis 发布的 Claude Code / CC-Weka 数据集](https://huggingface.co/datasets/semianalysisai/cc-traces-weka-062126)。发布数据包含 393 个 session；当前分析保留 121 个工作流中的 286 组相互重叠、完成后有 Main 请求的分支组。每组计算最长与最短分支的执行时长差，每个工作流贡献其中的最大差值，中位数为 138 秒，P90 为 1,173 秒。

这里说明所选工作流存在明显的分支时长异质性，再回到例子中的依赖解释，得到第一个动机：保护优先级应考虑请求延迟对 WCT 的影响。分布的统计单位是“每工作流最大分支时长差”，不是所有 Agent 完成时间的分布，也不是随机故障时刻的 Slack 分布。数据集不记录完整结果消费关系，因此当前 fan-in 筛选采用时间推定。这些条件保留在正文与图注中。

**动机二：上下文逐渐增长，无可用 KV 时的重建代价随之增加。** 多轮推理累积历史输出、代码、工具结果和其他 Agent 的结果。没有上下文压缩时，后续请求需要处理的历史越来越长。正常执行可以复用已生成的 KV，但 GPU 故障使它们不可访问时，如果没有仍可使用的副本，就需要重建缺失状态。这会增加恢复延迟，并占用健康 GPU 的计算资源。

![Figure 1(c)：上下文规模与 Prefill KV 填充成本](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/recovery-cost.png)

[Figure 1(c) PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/recovery-cost.pdf)

**Figure 1(c) 支撑第二个动机。** 已替换为 **1-token Prefill** 新口径，使用作业 1516148 同一次分配的 8K、64K、256K、1,010,000 数据。总上下文为 C=M+1；HBM/DRAM 复用 M 个 token 的 KV 后仅执行 1-token EXTEND，Full prefill 则从空 KV 填充全部 C 个 token。在 1,010,000 总上下文处，HBM、DRAM、Full prefill 分别为 **15.78 s、16.99 s、1089.44 s**。旧 64-token 数据保留历史记录，没有重标成新结果。

条件：同次分配的 2 张 A100-PCIE-40GB、TP2、BF16 权重与 KV、batch 1；SGLang 0.5.10rc0 原生 DCA，关闭稀疏加速，固定支持 A100 的注意力构建和 FlashInfer SiLU。HBM 已驻留全部历史；DRAM 从 pinned host memory 实际 H2D 完成后再 Prefill 一个新 token，不使用假设带宽，也不与计算重叠；Full prefill 按至多 8K 的块填充 M，再独立 Prefill 同一个新 token。按实际 token 数复制不完整页中的历史 KV，三路径使用固定 M/1 边界。

终点是模型主体 forward 返回并 CUDA 同步，此时全部 C 个 token 的 KV 已填充，不含词表投影/采样。这个终点包含最后一层 attention/MLP，并非对最后一次 KV 写入单独打点；测量没有故障注入或 64-token 重建尾部，不包含模型加载、KV 备份创建、故障检测、排队和服务接管。

一个固定合成文本流。HBM/DRAM 各预热一次、正式计时三次，点为中位数，误差线仅为 min–max；完整空缓存 Prefill 每长度正式计时一次，之前只做短前缀内核预热，没有重复整个长上下文预热，可能包含首次形状相关开销。复用路径与空缓存参考的各层新 token KV、hidden、DECODE hidden 和后续 greedy token 通过配对校验；不能把计时重复当成独立 workload 或推导置信区间。

**带宽与模型延迟分开解释。** 单独作业 1516171 在一张 A100 40GB 上，读取/传输相同 1 GiB 随机 BF16 数据，实测 HBM 流式读取 **1079.20 GB/s**、pinned H2D **23.98 GB/s**，相差 **45.00 倍**（9 次计时中位数）。它不代表整个 Prefill 的加速比，也不是 TP2 聚合带宽。DRAM 避免了历史重算；HBM 额外避免 H2D 等待，但两条路径仍需执行公共的模型前向计算。论文不能将 HBM 与空缓存的全部差距当作 HBM 相对 DRAM 的收益。

[新协议及预算](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/PREFILL_ONE_PROTOCOL.md)；[完整矩阵数据](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1516148/measured.json)；[逐次记录](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1516148/trials.jsonl)。

**独立衔接段：故障发生在工作流不同位置，会产生不同的 WCT 影响。** 在两个动机之后单独展开这一段，用 Figure 2 将“重建代价”和“工作流位置”联系起来。

![Figure 2：不同故障位置的重建时间与 WCT 损失，原 Figure 1(c)](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/recovery-exposure.png)

[Figure 2 PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/recovery-exposure.pdf)

**Figure 2 用于引出 AegisKV。** 对 Figure 1(a) 的四个活动分支，在同一个 29.5 秒时刻分别假设施加故障。A1 重建约需 35.2 秒，但其 91.2 秒余量可以吸收这一代价；A2 只需 32.2 秒，却因零余量而全部暴露给 WCT。A3 和 A4 分别产生 17.6 和 17.0 秒的 WCT 损失。因此，重建更便宜的分支也可能更需要保护。

这四行是独立的单分支反事实，不是四个分支同时故障。重建时间采用活动请求的 64-token hash-block 输入代理，加上假设尾部，以 Qwen3-14B/A100 的静态模型估计；其他执行和排队保持不变。本例解释依赖传播机制，多请求同时恢复及其资源竞争需要另行评估。

**本节最后自然引出系统：** AegisKV 面向工作流完成时间分配有限的 KV 保护资源，将请求的延迟容忍度与其 KV 的实际恢复价值联系起来，并考虑保护占用 HBM、DRAM 和带宽对正常服务的影响。已有有效缓存仍可参与恢复；新增保护需要以额外成本换取可见的恢复收益。具体的请求级决策、请求内放置、容量控制与故障接管放到 System Design。

**配图顺序已同步到 LaTeX：** Figure 1 为通栏三联图，依次是工作流例子、分支时长差分布、Prefill 成本；Figure 2 为独立单栏恢复暴露图。图文件继续使用语义名称，编号由 LaTeX 管理。


# 3. System Design

**本章沿用当前 PDF 的六小节架构：设计依据 → 系统全貌 → 请求的延迟容忍度 → 恢复目标与接管 → 请求级和块级保护决策 → 容量控制。** 下文是对应的中文写作提纲；共享副本、增量 checkpoint 和生命周期内容融入负责它们的模块。章节顺序用于解释职责，实际执行由请求、checkpoint、故障和窗口事件驱动。

| 小节 | 核心问题 | 主要输出或作用 | 对应图与算法 |
| --- | --- | --- | --- |
| 3.1 Design Insights | 哪些特征支持差异化保护？ | 工作流与 KV 两个层次的设计依据 | Figure 3(a)–(c) |
| 3.2 System Overview | 模块如何协作，正常缓存与容错如何分工？ | 控制路径、数据路径、共享接口 | Figure 4，单栏 |
| 3.3 Workflow Tracker: GBDT and CPM | 如何估计请求的延迟容忍度？ | 请求 Slack | Algorithm 1 |
| 3.4 Recovery-aware Router | 正常请求如何派发，故障后由谁接管？ | 正常路由、恢复映射、故障重路由 | Figure 5，回引 Figure 4 |
| 3.5 KV Master: Request-Specific Backup Decisions | 哪些请求值得保护，各请求保护哪些 KV？ | 保护级别、请求独立的 L、每层 K 和更新计划 | Algorithm 2、Figure 6 |
| 3.6 Adapter: Windowed Peer Capacity Control | 正常推理需要空间时，保护如何退让？ | 窗口 Peer 预算、安全降级、实际释放量 | Algorithm 3，回引 Figure 4 |

## 3.1 Design Insights

**本节承接 Motivation，简洁说明差异化保护为什么有实现机会，以及这些依据如何落实到模块。** 第 2 节已经解释 WCT 和恢复成本的重要性，这里进一步讨论可获得的预测信号与恢复需求。三个依据分别服务于 Tracker 和 KV Master。

**Insight 1：执行上下文有助于预测 Agent 的剩余工作。** 角色、任务特征和执行进度可以提供预测信号，已有轨迹预测结果说明剩余工作具有一定可预测性。AegisKV 使用部署校准的剩余时间估计，再结合工作流依赖计算 Slack。具体输入、训练与传播过程放到 3.3。

![Figure 3(a)：已有 Agent 轨迹预测结果](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/agent-prediction.png)

[Figure 3(a) PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/agent-prediction.pdf)

**本图用于 Insight 1。** 图引自 Heddle，展示剩余轨迹长度的预测相关性。它支持采用预测信号的依据；剩余执行秒数误差、Slack 误判和本地 GBDT 的效果仍需单独验证。3.3 回引此图，避免重复插图。

**读图方法。** 横轴 `Observed agent steps` 表示预测时已经观察到的 Agent 执行步数：在第 1 步后利用已有上下文预测，在第 2 步后加入新生成内容与工具反馈，再次预测。它不是 token 数、秒数或预测剩余步数。纵轴 `Pearson correlation` 表示同一任务领域内，多条轨迹的预测长度与实际长度之间的线性相关性；每个点是这批轨迹的汇总指标，而非单个 Agent 的执行结果。三条线分别对应 Coding、Search 和 Math。原论文使用 Qwen3-14B 作为 rollout 模型，Heddle-1/2 表示预测时点。

| 任务领域 | 第 1 步后预测 | 第 2 步后预测 |
| --- | --- | --- |
| Coding | 约 0.67 | 约 0.72 |
| Search | 约 0.72 | 约 0.88 |
| Math | 约 0.82 | 约 0.94 |

数值从 [Heddle Figure 13](https://arxiv.org/html/2603.28101v1#S7.SS2) 的矢量图提取并四舍五入，不是作者提供的逐条预测数据。图中只有两个观测时点，连线用于比较两次评估，不代表已经测得整个执行过程中的连续变化。0.94 表示较强的正线性相关，不能解释为“94% 的预测正确”或“时间误差只有 6%”。

**它与 AegisKV 的关系。** 原文的预测目标是剩余轨迹长度；原文 Figure 5 以输出长度展示轨迹差异，其调度模型用长度乘每 token 时间估算生成成本，因此这里应理解为输出工作量的预测依据。AegisKV 的 Slack 则需要剩余执行时间，还涉及工具耗时、排队、推理速率和依赖关系。正文从本图可以引出“运行上下文提供预测信号”，之后由 3.3 说明如何估计时间并验证误差。即使所有长度都被预测成真实值的两倍，Pearson 相关性仍可为 1；因此相关性高不能独立证明时间估计准确。

**Insight 2：稀疏注意力使恢复对象具有结构差异。** 不同原生稀疏机制具有不同的层、块、KV 组与辅助状态需求。恢复规划需要使用模型实际要求的对象，不能把全部 KV 字节视作同等的快速驻留候选。

![Figure 3(b)：所选稀疏模型发布与原生上下文长度](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/sparse-models.png)

[Figure 3(b) PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/sparse-models.pdf)

**本图用于 Insight 2。** 所选模型的发布时间、上下文长度与选择单位说明需要处理多种稀疏机制；样本内最大值阶梯和模型发布例子不代表市场占有率，也不能单独证明热块放置有效。图注沿用 LaTeX 中的模型来源与单位定义。

**Insight 3：历史选择可以预测一部分后续恢复需求。** 过去被访问的块可以作为提前放置的候选，但命中效果依赖模型、物理块粒度和重放尾部。KV Master 利用这些信号选择热集，恢复执行仍按真实需求获取预测遗漏的块。

![Figure 3(c)：历史访问对后续恢复 KV 需求的覆盖](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/retry-kv-prediction.png)

[Figure 3(c) PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/retry-kv-prediction.pdf)

**本图用于 Insight 3。** 在相同历史 KV 字节预算下比较历史频率与近期性；每个模型使用 3 个 PG19 文档，柱和胡须表示文档均值与范围。NOSA、MiniCPM4、Seer 的差异说明预测机会依赖模型与选择粒度。该图支持候选信号的可用性，覆盖率不能直接换算为 Agent 重试或 WCT 收益。3.5 回引此图说明块级选择。

**本节收束。** Tracker 将剩余工作预测转为请求级延迟容忍度，KV Master 将恢复需求预测转为请求内的放置候选。实际保护还要经过容量、提交状态和正常服务代价的检查；后续小节依次解释这些决策如何执行。

## 3.2 System Overview

**第 1 段：用整体图介绍三个层次和模块责任。** 应用层提供工作流、Agent、请求身份及 DAG 更新；控制层的 Tracker 管理 Slack，Recovery-aware Router 统一负责正常派发、恢复目标绑定和故障重路由，KV Master 制定保护策略；引擎侧 Adapter 管理本地 Peer 容量，由 Connector 执行传输。Controller 保存目录、路由版本和保护元数据；KV 数据直接在引擎与存储间传输。

![Figure 4：AegisKV 的控制与数据路径](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/system-overview.png)

[Figure 4 PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/system-overview.pdf)

**本图用于第 1 段，承担模块导航。** 保持等比例单栏。徽标 1–4 对应 Tracker、Recovery-aware Router、KV Master 和 Adapter，分别在 3.3–3.6 展开；徽标不代表事件发生顺序。图中仅保留一个 Router，内部的 Run → Retry/Peer 映射表示正常执行 DP 与预定接管/备份 DP 的对应关系；黑色实线表示正常派发，红色虚线表示故障重路由，Target DP 控制路径把绑定结果交给 KV Master。对称 DP 具有本地 KV 和 Peer 区域，Peer 与 DRAM 路径独立提交。两 DP 的互相接管和空间比例均为示例。

**第 2 段：明确正常缓存与额外保护的分工。** 正常缓存继续决定健康运行期间的复用、卸载和普通淘汰；AegisKV 根据工作流和恢复需求提出额外保留与放置要求。两者共享对象目录、分配器和传输机制。已有兼容且满足故障域要求的有效副本可以复用，增加保护引用；仅缺失的状态需要新增复制。

**第 3 段：解释共享对象与资源计费。** 共享条件包括模型/权重与布局、相同前缀及位置、层、分片和封存 token 区间。相同角色或相同文本片段不足以认定 KV 相同。多个请求引用同一副本时物理字节只计一次，但保护使普通缓存无法回收的占用仍有代价。区分普通缓存保留、请求保护引用和 kernel/DMA 使用期间的物理引用；生命周期在 3.6 展开。

**第 4 段：串起一次请求的控制过程。** 请求到达后，Router 选择正常执行 DP 并绑定恢复与 Peer 目标，Tracker 提供 Slack；KV Master 在 prefill、固定 Z 的 decode checkpoint 及策略事件上决定保护级别和热集；Adapter 按当前预算接纳并反馈实际提交结果。时间窗口结束时 Adapter 更新总容量，故障确认后 Router 激活恢复路由。Z 固定为系统配置，L 由 KV Master 按请求决定。

**第 5 段：概括恢复约定与接口。** 已确认 token、输入和控制元数据在源故障域外可获取，并存在兼容恢复目标。基础系统提供副本查询、容量预留、保护引用、版本化提交、位置退休及事件通知。已有普通缓存也可以参与恢复，但要通过相同有效性检查。3.4 说明 Router 如何使用这些接口；完整 checkpoint 的发布条件在 3.5 说明，准入、传输和引擎执行约束在 3.6 展开。这些是需要实现的接口。

**文献与配图取舍。** 保留 [Mooncake](https://www.usenix.org/conference/fast25/presentation/qin)作为分层存储背景、[LUMEN](https://arxiv.org/html/2606.17787v1#S4.SS1)作为服务恢复控制点的参考。当前方案聚焦存活兼容副本上的 KV 恢复。共享引用边界先在正文说清；若后续补图，可在本节增加同一 DRAM 对象被普通缓存和容错共同使用的小图，并供 3.6 回引。该补图尚未绘制，不为它预占正式图号。

## 3.3 Workflow Tracker: GBDT and CPM

**本节回答如何得到请求的 Slack。** GBDT 是剩余时间预测器的一种实现，CPM 将预测与工作流依赖联系起来；本节重点是预测结果如何服务保护决策。

**第 1 段：定义残余工作流。** 用尚未完成的 Agent 执行片段构成残余 DAG。父 Agent 在 fork/join 边界处分段，避免把子任务执行同时计入父任务等待；每个活跃请求映射到自己的执行片段。已完成片段移除，未开始片段的预测表示依赖满足之后所需的执行时间。

**第 2 段：解释 GBDT 的输入与目标。** 输入只使用当前可见的角色/模型、经过时间、已知输入长度以及已完成请求的输出长度和耗时等信息；训练目标是快照时刻到片段完成的剩余时间。模型直接预测剩余时间，之后不重复减去已经过时间。工作流与时间划分训练集和测试集，避免同一轨迹的快照泄漏。

**第 3 段：用 CPM 将剩余时间变成 Slack。** 前向传播得到最早完成时刻和当前工作流完成预测，反向传播得到不推迟该完成时刻的最晚完成时刻；两者之差形成片段 Slack，由活跃请求继承。连续请求共享片段余量，不能把它当作每个请求都能独立消耗的一份预算。

**第 4 段：说明刷新与保守回退。** 请求到达/完成、DAG 更新和策略窗口触发刷新。只有编排器声明剩余依赖完整、请求映射有效且预测可用时才使用估计 Slack；未展开分支、未知依赖或缺失预测使对应工作流回退到零 Slack。新工作使此前的完整性声明失效，需要重新评估。

**算法与配图安排。** 沿用 Algorithm 1：检查结构和输入 → GBDT 预测剩余时间 → CPM 前向与反向传播 → 输出请求 Slack。第 2 段回引 3.1 的 Figure 3(a)，说明已有预测研究提供的依据。验证应报告秒级误差、错误地赋予正 Slack 的频率、关键路径排序、回退率和保护决策损失；轨迹相关性本身不足以证明这些性质。

## 3.4 Recovery-aware Router

**本节介绍统一负责正常执行与故障接管的 Router，核心是将路由目标与 Peer 备份位置提前关联。** 正常派发时同时建立恢复映射；故障确认后使用该映射重新提交请求。Router 决定位置，KV Master 决定保护内容，Adapter 与 Connector 负责容量和数据传输。

**正常派发的依据：同一 Agent 的历史提供较强的缓存局部性。** 在介绍恢复绑定之前，先解释 Router 为什么需要考虑正常请求的缓存亲和性。分析此前 SGLSim 使用的 [CC/Weka 数据集](https://huggingface.co/datasets/semianalysisai/cc-traces-weka-062126)：393 个工作流、2,090 个 Agent、98,827 个请求。只匹配同一工作流内、同一模型且在目标请求到达前已经完成的源请求。同一 Agent 的历史覆盖 **97.90%** 的累计输入 token 代理量，其他 Agent 覆盖 **10.06%**。

![Figure 5：同一 Agent 与其他 Agent 的前缀覆盖](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/agent-prefix-reuse.png)

[Figure 5 PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/agent-prefix-reuse.pdf)

**本图放在正常派发的解释旁，支持缓存亲和性这一设计依据。** 主 Agent 后续请求的两类覆盖分别为 98.79% 与 4.43%；子 Agent 后续请求为 95.41% 与 35.70%。因此，同一 Agent 的后续请求值得优先检查之前 DP 上的兼容缓存，但并不强制绑定该 DP，负载和实际驻留仍参与决策。子 Agent 首轮没有自身历史，却能从其他 Agent 获得 **70.93%** 的前缀覆盖，因此不能忽略共享前缀。

**不要把边际覆盖混为总覆盖。** 图中的两组柱可能覆盖相同前缀，不能相加。在每个请求上先计算“其他 Agent 覆盖超出同一 Agent 最佳前缀的部分”，再按输入量聚合，额外覆盖为 **0.37%**；它不是其他 Agent 的总覆盖比例。原 SGLSim 图采用互斥归因，且没有过滤模型；原 CSV 与图片保留在 [数据与溯源目录](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/agent-prefix-reuse/README.md)，当前正文图使用新增同模型过滤后的结果。

**统计与证据边界。** 输入长度及匹配长度均由 64-token 有序哈希块计数得到，是 token 数的代理量；按每组累计输入量加权，不是逐请求比例的平均。All requests 包含首次主 Agent 请求，其两类覆盖均为零。源请求只贡献已记录的输入前缀，未单独补入输出 KV。数据不记录实际权重/布局兼容性、驻留、驱逐或路由结果，因此这里展示潜在前缀覆盖，不称为缓存命中率。同名模型仍需运行时兼容检查；哈希只在工作流内可比较，不能将本图推广为不同工作流之间同角色复用很少，也不能据此宣称故障恢复或 WCT 已改善。

**第 1 段：正常派发与恢复目标绑定。** 请求到达时，Router 根据正常负载和兼容缓存局部性选择源 DP，并为该请求记录兼容、满足故障域隔离条件的恢复 DP。恢复目标同时是后续 Peer 备份的目的地。例如请求在 DP0 运行，预定由 DP1 接管，那么获准的 Peer 热块就放在 DP1。等价且隔离的 DP 可采用环形映射作为简单例子；更一般的逐请求映射可以分散恢复负载，但这里不宣称其负载分配最优。

**第 2 段：把恢复映射交给保护策略。** Router 将请求身份、源 DP、目标 DP 和路由版本保存在可存活控制状态中，并发布给 KV Master。目标绑定不预留 Peer 容量、计算或恢复工作空间，也不自动触发备份。KV Master 决定 R/D/P、L 与热块；目标 Adapter 决定能否接纳。这样，正常派发和备份策略通过同一个未来接管位置协同。

**第 3 段：故障确认后激活恢复路由。** 健康监控结合成员、设备错误与 Adapter 报告的 GPU 进展确认源失效，存活运行时隔离旧执行 epoch。Router 接收该事件，取得受影响请求、已确认 token、有效 checkpoint 和副本位置，重新提交到预定 DP。由引擎和 Connector 使用本地 Peer 副本、加载 DRAM 或重建缺失状态；Router 不直接执行块复制或 KV 重建。

**第 4 段：处理目标失效或容量不足。** 重新提交前检查目标健康、模型/布局兼容性及执行空间。目标不可用或工作集无法接纳时，可以等待或改派到新的有效目标。改派更新路由版本并通知 KV Master，重新查询实际副本位置；旧目标上的 Peer 副本不能继续算作新目标的本地 HBM。改变路由本身不会完成 KV 迁移或提交。

**第 5 段：说明 Router 使用的恢复状态约定。** Router 查询目录中最新且依赖完整的已提交 manifest，详细发布条件见 3.5；新 checkpoint 尚未完成时使用旧有效前沿，没有前沿时依赖可恢复输入重建。源 epoch、已确认 token 和输入日志在源故障域外可用，运行时拒绝旧 epoch 写入并避免重复交付；外部工具副作用仍由编排器的幂等约定处理。这些是 Router 使用的运行时保证，不能仅靠重路由自动获得。

**第 6 段：提交多个 retry，交给引擎推进。** 各请求通过状态与目标检查后独立进入恢复，不因保护优先级形成一个请求完成后另一个才能开始的屏障。实际执行遵守引擎的批处理和 kernel 边界，空间、链路和进展保障在 3.6 说明。本地有 Peer 副本也可能因缺少执行空间而排队；路由可用性与执行可行性分别检查。

**配图安排。** Figure 5 用于上述正常路由的缓存局部性依据；回引 Figure 4 中 Router 内的 Run → Retry/Peer 映射、到 KV Master 的 Target DP 控制路径，以及通向引擎的正常派发和 Retry on failure 两条路径。Figure 6 在 3.5 解释备份位置如何减少取数等待。保留 [DéjàVu](https://proceedings.mlr.press/v235/strati24a.html)与 [LUMEN](https://arxiv.org/html/2606.17787v1)作为恢复机制的已有研究参考；本节重点是路由与保护位置的协同，所列运行时接口仍需验证。

## 3.5 KV Master: Request-Specific Backup Decisions

**本节是主要决策部分，内部按“决策事件 → 请求级保护 → 请求内放置 → 增量更新与提交反馈”展开。** 请求间和块间两层决策均由 KV Master 负责；Adapter 提供总容量约束。

**决策事件与对象粒度。** 请求到达时建立策略；prefill 完成后提供已封存状态，decode 每增加配置的 Z 个 token 触发评估；Slack、上下文、预算或副本状态显著变化也可提前触发。Z 与物理块大小是两个配置，当前选择 trace 使用 64-token 块，不能把它写成所有原生稀疏算法的固定要求。保护对象按层、块及兼容性元数据标识，辅助状态另行计费。

**第一层：决定请求需要什么保护。** 从已有副本及其有效性出发估计可行恢复路径，结合 Slack 决定额外保护需求。保留当前 R/D/P 组织方式：R 不要求追加备份，无可用状态时依赖重算；D 申请并提交 DRAM 保护；P 在可行恢复覆盖基础上竞争 Peer 加速。正常缓存仍可能命中，不能因选择 R 就主动丢弃可用副本。

| 请求级动作 | 需要落实的决策 | 容量不足或路径不可用时 |
| --- | --- | --- |
| R：不追加保护 | 核查现有状态与缺失部分的重建代价 | 依赖可恢复输入重建缺失状态 |
| D：DRAM 保护 | 申请缺失状态的容量并发布有效前沿 | 保留旧前沿；没有前沿时重算 |
| P：申请 Peer 加速 | 给出请求内热集与层深候选，并核查实际预算 | 拒绝增量或缩小接纳，使用可行的 DRAM/重算路径 |

**请求间优先级与接纳。** 按 Slack 及稳定请求标识顺序评估受事件影响的请求；比较重建、DRAM 加载和 Peer 加速的恢复暴露与新增代价。小 Slack 带来较高保护优先级，但不保证获得容量。正在运行的其他请求持有的 Peer 保护引用不能被普通申请抢占；无可安全释放空间时拒绝增量，正常推理仍可继续。DRAM 也需要独立准入。这个顺序是局部启发式，不宣称全局最优 WCT。

**第二层：决定请求自己的 L、每层 K 和块身份。** L_r 是请求目标 Peer 层深，K_{r,l} 是该请求该层实际已提交的 Peer 块数。另设目标热集配额，可以是固定块数，也可以按历史块数比例配置；因此历史增长不必导致 K 持续增长。数量保持不变时，块身份仍可能变化。K 与 selector 每个 Query 的 top-k、在途复制数和命中率保证分别定义。

**候选块与恢复需求。** 回引 Figure 3(c)，用历史原生选择频率排序候选，并包含模型要求的强制状态；同分按近期性与稳定块标识处理，冷启动使用已观察前缀和明确回退规则。配额不足以容纳强制状态时申请更大且计费的配额，或者拒绝该层的 Peer 接纳。重放需求是尾部跨 Query 和 KV 组实际选择的去重并集。热集预测与原生选择分离，3.4 的需求加载保证真实输入可用。

**层深与恢复流水。** 结合请求的已提交历史 M、未知故障时的尾部 N、带宽和计算画像比较若干层深。计算能够隐藏部分后续传输，Peer 的额外价值是减少仍暴露的加载等待。若仅搜索前若干层，需要声明这是限制搜索空间的启发式。

![Figure 6：恢复流水与 Peer 驻留的额外作用](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/recovery-pipeline.png)

[Figure 6 PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/recovery-pipeline.pdf)

**本图放在层深决策的解释之后。** 先说明 (b)/(c) 的按层流水及预取，再比较 (c)/(d) 的 Peer 增量。图使用实测 forward 延迟派生的层均值和假设带宽；7 层、约 147 MiB 是固定历史/尾部条件下的例子。它不能校准全部层深决策，也不能证明全窗口统一 L 或多请求 WCT 收益。

**比较收益、成本与不确定性。** 候选从同一资源快照和同一预测窗口出发，使用相同的未来 M/N、提交滞后与负载样本，比较正常服务延迟变化和故障概率加权的恢复暴露。样本需声明来源；N 不能直接设为 Z，复制滞后时还可能超过 Z。迁移、复制和空间占用对其他请求的影响也进入比较。保留当前集合的候选始终参与，只有在画像有效且改善超过不确定性与切换余量时才更新。画像缺失、过期或漂移时限制自主扩张并采用可行回退，不把 Figure 6 的单例当作通用画像。

**增量 checkpoint 与热集更新。** 先查询已有兼容副本，已有有效且能存活的 DRAM 副本增加保护引用即可；相同版本的在途复制可合并依赖，但仍须等待完成。若上下文增长后才首次需要保护，应补齐目标前沿缺失的历史依赖。新旧热集保留交集，退出现有集合的块按 3.6 安全降级，只传入新增块；所有临时空间、待释放缓冲区和共享引用均计入可行性检查。

**提交与反馈。** 策略评估、复制请求和已提交保护是不同状态。新前沿需要匹配模型/权重与布局、所需层与 TP 分片、封存 token 区间、选择器状态和对应 token 日志；完整 manifest 提交后才替代旧前沿，不能取独立对象位置的最大值当作公共前沿。复制失败或滞后时保留旧前沿并报告更长重放尾部。实际接纳可能小于目标，目录发布已提交层/块集合与真实释放量，KV Master 据此复核。Peer 与 DRAM 可独立提交，Peer 拒绝不意味着 DRAM 已接纳。

**算法安排。** 沿用 Algorithm 2，在一个过程内清楚区分两层决策：查询资源与副本 → 按 Slack 评估请求的 R/D/P → 生成请求内层深与热集候选 → 预演保留/退出/新增及其成本 → 选择稳定改进或回退 → 重新核查物理预留 → 发布已提交结果。Z 固定，不同请求各有自己的 L。

**贯穿例子与后续证据。** 用一个请求说明：历史较短时不追加保护；历史增长后补齐 DRAM 前沿；恢复暴露增加时竞争 Peer；之后 K 可以不变而热集替换；请求结束或系统收缩后释放或降级。后续分析/模拟图可在固定 Z 下比较不同 M/N 条件的 L—字节—等待关系，并展示计划与已提交的 L/K 轨迹；这些图尚未绘制。正常复用与故障保护的区别可参考原提纲中的 [KVFlow](https://arxiv.org/html/2507.07400v1)、[ECHO](https://www.usenix.org/conference/osdi26/presentation/liu-guangda)和 [SYMPHONY](https://www.usenix.org/conference/nsdi26/presentation/agarwal)，具体贡献仍需通过匹配条件的对比验证。

## 3.6 Adapter: Windowed Peer Capacity Control

**本节说明目标 DP 的资源闭环：确定窗口 Peer 容量，并兑现接纳、回收与安全降级。** Adapter 不决定公共 L，也不调整 Z；请求的层深和热集由 KV Master 负责。

**第 1 段：为正常推理预留空间。** 每个时间窗口估计正常 KV 需求和增长余量，从管理池中扣除，再限制在零到管理池一半的配置上限内。管理池排除权重与固定运行时状态，包含当前 Peer 占用；输出是允许的总占用而非新增空闲空间。窗口不固定为 5 秒，窗口内每次申请仍核查物理容量。

**第 2 段：区分请求竞争与系统收缩。** 普通新请求只能使用空闲空间或可安全释放的无保护引用对象，不能抢占其他活跃请求的保护副本。请求自身可以替换热集或减小层深。Adapter 为正常服务收缩预算时，有权将仍有保护引用的对象降级到 DRAM，但必须保留所承诺的逻辑恢复状态，并等待实际 kernel/DMA 引用释放。

**第 3 段：解释请求完成和工具交接。** 一轮推理请求结束或交接给工具时释放该请求的保护引用；共享块的其他拥有者继续持有引用。普通缓存可根据正常复用策略保留副本，无保护引用对象进入可回收队列，物理使用结束后才可释放。如果要承诺跨工具等待的 Agent 级保护，需要另外定义寿命与预算；普通缓存 TTL 本身不构成该承诺。

**第 4 段：按已提交副本执行安全降级。** 先确认是否已有匹配且有效的 DRAM 副本；有则复用，没有则预留空间、写回并提交。随后切换目录并关闭旧 Peer 地址的新引用，等待旧版本的读者和 DMA 结束，最后释放 HBM 并返还字节。写回或 DRAM 接纳失败时保留仍受承诺的 Peer 副本，报告尚未完成的收缩。

**第 5 段：给出收缩次序与反馈。** 超过新预算时停止新增 Peer 预留，优先回收无保护引用对象；仍不足时按 KV Master 提供的顺序降级受保护对象：较大 Slack、较深层、较低近期选择频率及稳定对象标识。共享对象按剩余拥有者中最小 Slack 确定优先级。报告实际减少的驻留与尚未释放的字节，随后由 KV Master 复核各请求 L。此顺序选择迁移对象，不要求迁移或 retry 逐请求串行完成。

**第 6 段：统一 DRAM 与 HBM 的物理账本。** 已提交对象、在途预留、临时缓冲区、待释放对象和必要元数据都计入容量；共享物理字节只计一次。DRAM 保护也有明确上限，接纳失败时保留旧有效前沿或使用重算回退。收缩需要传输与引用排空，实际占用可能暂时超过目标预算；限流和必要写回的服务份额保证进展，不能把目标降低直接记为已释放空间。

**恢复执行接口。** Router 提交 retry，Adapter 配合引擎检查工作空间并报告就绪状态，Connector 获取实际缺失的块；恢复 selector、按原生需求取数和重放由引擎执行。就绪 retry 在有界 prefill chunk/decode step 上推进，TP 排列和 collective 次序一致；无法拆分的阻塞批次按实际代价计入画像。正常备份、按需加载和必要写回各有配置的服务份额，正常备份的链路带宽上限不代表同等的延迟开销上限。资源不足反馈给 Router 排队或改派，回写和引用排空则继续遵循本节的安全顺序。

**算法与配图安排。** 沿用 Algorithm 3：估计正常需求 → 发布窗口预算 → 停止超预算接纳 → 优先安全回收 → 必要时降级受保护对象 → 提交/切换/排空 → 报告真实占用。回引 Figure 4 说明控制位置；后续若在 3.2 补共享副本图，可复用其引用与迁移面板。容量时间序列应区分目标预算、实际占用、待释放字节和正常需求，目前尚无该图。保留 [TokenCake](https://arxiv.org/html/2510.18586v4)、[Continuum](https://arxiv.org/html/2511.02230v6)与 [SYMPHONY](https://www.usenix.org/conference/nsdi26/presentation/agarwal)作为原提纲的正常服务与内存管理参考。

**本章收束。** 现有证据包括已归属的预测结果、原生选择 trace 和单请求恢复流水模型。动态热集迁移、层深画像、并发恢复、正常推理干扰及端到端 WCT 效果仍需验证。在相同正常缓存和物理资源配置下进行有故障/无故障配对比较，覆盖迁移中故障、目录竞态、DRAM 耗尽、复制积压和共享链路压力，并保留零收益或负收益结果。
