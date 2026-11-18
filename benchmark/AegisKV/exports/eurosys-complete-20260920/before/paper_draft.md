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

**Figure 1(c) 支撑第二个动机。** 作业 1517055 在同一次 2×A100-PCIE-40GB 分配上实测 8K、64K、256K 和 1,010,000。按用户最新要求，图中仅保留三条曲线：稀疏 Full Prefill、HBM reuse、DRAM reuse（无 Overlap）。1,010,000 处依次为 **565.93 s、1.266 s、2.517 s**；HBM 相对无重叠 DRAM 降低延迟 **49.7%**。旧 dense 结果与已启动批次的 overlap 诊断均保留为历史，不进入当前三曲线对比。

**统一计算与数据条件。** Qwen2.5-7B-Instruct-1M，TP2、BF16 权重与 KV、batch 1，SGLang 0.5.10rc0。历史 Prefill 使用 MInference 官方 Qwen1M vertical/slash 参数与 DCA，保留 32K 上下文启用阈值。稀疏实现直接共享 GQA K/V，去除按 query head 重复展开 K/V 的临时副本；多 query 前缀每组最多 2 个 query heads 以控制选择器临时显存，最后单 query 合并全部 heads。超过 32K 上下文阈值时，三条路径末尾一个新 token 也执行同一稀疏 EXTEND；阈值以内统一使用 grouped dense DCA。没有另加多 token 的恢复尾部。

**终点与传输。** 总上下文 C=M+1；Full Prefill 从空 KV 开始按至多 8K 的块处理 M，再续算一个 token。两种复用都使用该次稀疏 Prefill 生成的历史 KV。HBM 在计时前驻留历史；DRAM 在计时内完整搬运 M-token KV 并同步 copy stream 后再计算，包含末尾不完整页，不做压缩、选择性加载或传算重叠。统一计时至模型主体返回且 CUDA 同步，全部 C-token KV 就绪；不含输出投影、备份创建、模型加载、排队或故障检测。

**样本与验证。** 一个固定合成重复文本流。HBM/DRAM 各预热一次、正式计时三次；点为中位数，误差线为 min–max，不是置信区间。Full Prefill 每长度一次，当前图共使用 28 次正式计时。测量前有短前向与七组算子验证，包含 1M 上下文／8K-query 最大形状；64K 另有原始 all-head 稀疏完整参考，256K/1.01M 不重复完整上下文预热。验证最后 token hidden、全部层新 KV 和 greedy 输出；每种复用每个长度额外逐字节检查完整历史 KV。CUDA 事件确认 DRAM 复制完成后才开始模型计算。稀疏配置内的恢复正确性不等于稀疏与 dense 数值等价，也不是任务质量评估。

**图像结论。** 启用稀疏 Prefill 后，保留 KV 仍可避免大量历史重算，HBM 又省去串行 H2D 的等待。这里的 DRAM 明确不与计算重叠，图中的 HBM 优势不能推广到允许传算流水线的 DRAM 实现。完整 HBM 驻留是参考状态，有限 Peer 容量及端到端 WCT 收益仍需另外验证。

[实验与选取协议](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/SPARSE_OVERLAP_PROTOCOL.md)；[图中三路径数据](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1517055/published-three-paths.csv)；[完整原始记录](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1517055/trials.jsonl)；[发布校验](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1517055/publication-validation.json)。

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
| 3.1 Design Insights | 哪些请求需要保护，请求内部哪些 KV 值得提前放置？ | Slack 与恢复成本、稀疏恢复对象、热块预测信号 | 回引 Figure 2；Figure 3(a)–(b) 单栏上下排列 |
| 3.2 System Overview | 模块如何协作，正常缓存与容错如何分工？ | 控制路径、数据路径、共享接口 | Figure 4，单栏 |
| 3.3 Workflow Tracker: GBDT and CPM | 如何估计请求的延迟容忍度？ | 请求 Slack | Algorithm 1 |
| 3.4 Recovery-aware Router | 正常请求如何派发，故障后由谁接管？ | 正常路由、恢复映射、故障重路由 | Figure 5，回引 Figure 4 |
| 3.5 KV Master: Request-Specific Backup Decisions | 哪些请求值得保护，各请求保护哪些 KV？ | 保护级别、请求独立的 L、每层 K 和更新计划 | Algorithm 2、Figure 6 |
| 3.6 Adapter: Windowed Peer Capacity Control | 正常推理需要空间时，保护如何退让？ | 窗口 Peer 预算、安全降级、实际释放量 | Algorithm 3，回引 Figure 4 |

## 3.1 Design Insights

**本节承接 Motivation，按“请求级保护 → 请求内的恢复对象 → 恢复对象的提前预测”展开三条 Insight。** 先将第 2 节的 WCT 观察转化为保护依据，再通过长上下文模型采用稀疏注意力的趋势，引出请求内部的 KV 选择。Agent 剩余时间预测的具体方法与相关研究放在 3.3，预测准确率与鲁棒性安排到后续 Evaluation。

**Insight 1：保护力度取决于恢复成本与工作流 Slack 的关系。** 回引 Figure 2：较长的恢复可能被某个分支的 Slack 吸收，较短的恢复却可能延长另一个分支所在工作流的完成时间。因此，请求是否需要额外保护，应结合恢复延迟超出其估计 Slack 的程度判断。KV Master 比较可行恢复路径，同时考虑追加保护的资源代价。本条沿用 Motivation 的例子，不新增图。

**Insight 2：稀疏注意力使恢复对象具有结构差异。** 随着上下文增长，稀疏注意力正被越来越多的长上下文模型采用，以降低注意力计算开销。例如，[MiniCPM4.1](https://huggingface.co/openbmb/MiniCPM4.1-8B) 采用 InfLLMv2，[DeepSeek-V3.2](https://huggingface.co/deepseek-ai/DeepSeek-V3.2) 和 [GLM-5](https://huggingface.co/zai-org/GLM-5) 采用 DSA。Figure 3(a) 用多个模型家族的发布实例呈现这一趋势，并展示 token、block 和压缩状态等不同选择单位。

确定哪些请求需要快速恢复之后，还需要确定请求内部哪些状态值得优先驻留在 Peer HBM。对于采用稀疏注意力的模型，恢复所需的 KV 取决于重放 Query、层与 KV 组的实际选择，以及模型要求的辅助状态。因此，KV Master 根据这些对象形成放置候选，再由下一条 Insight 讨论如何提前预测候选的价值。

![Figure 3(a)：所选稀疏模型发布与原生上下文长度](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/sparse-models.png)

[Figure 3(a) PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/sparse-models.pdf)

**本图用于 Insight 2。** 所选模型的发布时间与上下文长度呈现稀疏注意力在多个长上下文模型家族中的采用，选择单位说明恢复规划需要适配不同机制。这里将“逐渐成为主流”具体表述为“正被越来越多的长上下文模型采用”；样本内最大值阶梯和发布实例不代表市场占有率，也不能单独证明热块放置有效。图注沿用 LaTeX 中的模型来源与单位定义。

**Insight 3：历史选择可以预测一部分后续恢复需求。** 过去被访问的块可以作为提前放置的候选，但命中效果依赖模型、物理块粒度和重放尾部。KV Master 利用这些信号选择热集，恢复执行仍按真实需求获取预测遗漏的块。

![Figure 3(b)：历史访问对后续恢复 KV 需求的覆盖](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/retry-kv-prediction.png)

[Figure 3(b) PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/retry-kv-prediction.pdf)

**本图用于 Insight 3。** 在相同历史 KV 字节预算下比较历史频率与近期性；每个模型使用 3 个 PG19 文档，柱和胡须表示文档均值与范围。NOSA、MiniCPM4、Seer 的差异说明预测机会依赖模型与选择粒度。该图支持候选信号的可用性，覆盖率不能直接换算为 Agent 重试或 WCT 收益。3.5 回引此图说明块级选择。

**排版与收束。** Figure 3(a)–(b) 在一个单栏图环境内上下排列，分别支撑 Insight 2 和 Insight 3。三条 Insight 依次回答哪些请求值得保护、请求内有哪些恢复对象、哪些对象可以提前选择；实际保护还要结合容量、提交状态与正常服务代价。后续小节解释这些决策如何执行。

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

**预测方法的研究背景。** 在介绍输入与目标时引用 Heddle 和 AgentDecarbonizer：前者使用上下文预测剩余轨迹长度，后者估计任务时长并根据执行进展更新。这些工作说明可利用的信号来源，但文献相关性不能当作本地 GBDT 的秒级准确率。原 Heddle 图已从 Insight 中撤下，文献和原图仍保存在归档中。

**第 1 段：定义残余工作流。** 用尚未完成的 Agent 执行片段构成残余 DAG。父 Agent 在 fork/join 边界处分段，避免把子任务执行同时计入父任务等待；每个活跃请求映射到自己的执行片段。已完成片段移除，未开始片段的预测表示依赖满足之后所需的执行时间。

**第 2 段：解释 GBDT 的输入与目标。** 输入只使用当前可见的角色/模型、经过时间、已知输入长度以及已完成请求的输出长度和耗时等信息；训练目标是快照时刻到片段完成的剩余时间。模型直接预测剩余时间，之后不重复减去已经过时间。工作流与时间划分训练集和测试集，避免同一轨迹的快照泄漏。

**第 3 段：用 CPM 将剩余时间变成 Slack。** 前向传播得到最早完成时刻和当前工作流完成预测，反向传播得到不推迟该完成时刻的最晚完成时刻；两者之差形成片段 Slack，由活跃请求继承。连续请求共享片段余量，不能把它当作每个请求都能独立消耗的一份预算。

**第 4 段：说明刷新与保守回退。** 请求到达/完成、DAG 更新和策略窗口触发刷新。只有编排器声明剩余依赖完整、请求映射有效且预测可用时才使用估计 Slack；未展开分支、未知依赖或缺失预测使对应工作流回退到零 Slack。新工作使此前的完整性声明失效，需要重新评估。

**算法与评估安排。** 沿用 Algorithm 1：检查结构和输入 → GBDT 预测剩余时间 → CPM 前向与反向传播 → 输出请求 Slack。GBDT 的目标、特征和更新机制在本节详细介绍。后续 Evaluation 设置 **Tracker Accuracy and Robustness**，放置误差 CDF，并报告错误正 Slack、关键路径排序、回退率、保护决策损失与 WCT 影响。

**当前证据状态。** [GBDT 离线诊断及后续图设计](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/exports/agent-gbdt-insight/README.md)保留全部误差和数据来源。当前结果不足以支持准确预测，不把这张诊断图作为 Insight 或有效性证明。预测评估的安排不表示新实验已经完成，也不把文献轨迹长度相关性换算为时间准确率。

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

**本节按三个小节展开：如何决策 R/D/P → 如何决策 L → 完整算法流程。** Router 已指定恢复目标，Adapter 给出窗口 Peer 总容量，Workflow Tracker 提供请求 Slack。KV Master 在这些输入下决定请求的保护目标和实际放置；同一请求的目标可随推理进展变化，不同请求可以使用不同 L。

### 3.5.1 Choosing R/D/P：如何决策 R/D/P

**先解释判断依据。** 回引 Figure 2：恢复延迟中超过 Slack 的部分会暴露出来。Figure 2 当前展示重算与 Slack 的关系，这里将同样的判断扩展到可行恢复路径；它本身不是三种保护方式的完整对比实验。比较时保留故障检测、重路由、重新接纳和未提交尾部重放的公共代价，避免只比较历史 KV 的加载时间。

**再给出请求级分类。** 用相同的未来上下文、尾部和负载样本估计重算与 DRAM 恢复时间，再与当前 Slack 比较。

| 请求级目标 | 判断与动作 | 容量不足或路径不可用时 |
| --- | --- | --- |
| R：不追加保护 | 重算恢复时间可被 Slack 吸收；已有兼容缓存仍可使用 | 依赖已有有效状态和缺失部分重算 |
| D：申请 DRAM 保护 | 重算不能被吸收，但更快的 DRAM 恢复可以；复用已有副本并申请缺失覆盖 | 保留旧有效 checkpoint；没有则重算 |
| P：申请 Peer 加速 | 其余请求竞争 Peer；下一小节决定 L 与热块 | 拒绝或缩小增量，选择可行的 DRAM/重算路径 |

这些是本次评估的保护目标，不能把 P 写成已获得 Peer，也不能把它解释为全部 KV 都进入 Peer HBM。Slack 为零时，Peer 也未必能消除公共恢复开销；目标是减少暴露延迟。加载不一定比重算快，拒绝 Peer 后不应强制选择更慢的 DRAM 路径。

**最后解释请求间竞争。** 按 Slack 从小到大、同分按稳定请求标识处理。新申请不能抢占其他活跃请求的保护副本。DRAM 也需要独立准入和提交；已有有效副本先复用。该分类使用估计值，是规划启发式，不保证恢复一定落在 Slack 内，也不等于求解全局最优 WCT。画像缺失或实际状态变化时采用正文规定的保守回退，并在恢复时重新核查路径。

### 3.5.2 Choosing Peer Depth L：如何决策 L

**先说明选择 L 之前要确定每层放什么。** L_r 是请求的目标 Peer 层深；当前候选采用前 L_r 层热集，属于受限搜索。K_{r,l} 是该请求该层实际已提交的 Peer 块数，不是原生 selector 每个 Query 的 top-k，也不包含在途副本。另设目标热集配额，可固定块数或按已封存历史块数比例配置；因此 M 增长不必导致 K 增长。当前 trace 使用 64-token 块，不是所有原生稀疏模型的统一要求。

**解释候选块及其变化。** 回引 Figure 3(b)，用历史原生选择频率排列候选，纳入模型必需的已封存 sink/window 块和辅助状态。同分按近期性与稳定块标识处理；配额不足时申请显式计费的更大配额或拒绝该层接纳。当前热度统计使用此前 512 个 decode step；观察不足时采用已观察历史和明确的冷启动回退。可选块连续两个统计窗口退出目标集合后再退出保护，避免频繁更换。统计窗口与 Z、容量窗口分别定义。恢复所需 KV 是尾部各 Query/KV 组实际选择的去重并集，不能将单次 top-k 直接乘 N。

**接着说明 L 为什么影响恢复。** 已提交历史 M、未提交尾部 N、带宽和计算画像共同决定暴露的加载等待。前面层的重放计算可以隐藏后面层的部分传输，所以增加一层 Peer 驻留的收益不一定相同。Figure 6 放在这里，先建立取数与计算重叠的直觉，再介绍候选深度比较。

![Figure 6：恢复流水与 Peer 驻留的额外作用](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/recovery-pipeline.png)

[Figure 6 PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/recovery-pipeline.pdf)

图中 (b)/(c) 解释按层流水与热块预取，(c)/(d) 解释 Peer 驻留的增量。数据使用实测 forward 延迟派生的层均值和假设带宽；7 层、约 147 MiB 是固定历史/尾部条件下的例子，不能直接作为所有请求的配置，也不能校准全部 L 决策或证明多请求 WCT 收益。

**然后比较若干可行 L。** 固定每层配额与选块规则，从同一资源快照出发，比较零层、当前层深和配置网格中的候选，并保留完全不改当前块身份的 keep 方案。候选预演保留交集、退出旧块和加入新块；传输、写回、临时空间、在途预留及真实释放都计入成本，不能抢占其他请求持有的保护副本。R/D 的目标 Peer 层深为零，P 才竞争正层深。

比较目标由两部分组成：**正常推理延迟的变化 + 故障概率加权后、超过 Slack 的恢复延迟。** 各候选使用相同预测窗口、未来 M/N、复制滞后与共享负载样本；不能直接设 N=Z，也不能默认 checkpoint 相位均匀。正常服务代价包括复制、降级及容量变化对同一批请求的影响。该目标是局部启发式，局部延迟之和不等于 DAG 的 WCT，多个关键分支的耦合仍需要验证。

**最后说明何时真正调整。** 只有候选收益超过当前 keep 方案的不确定性和切换余量时才改变放置；否则保持。画像需要明确来源、版本、适用范围、有效期及实际误差校验，不能用 Figure 6 的单例替代。画像缺失、过期或漂移时限制自主扩张和替换；Adapter 收缩和正确性要求仍优先。L 不变时块身份仍可变化；K 固定时也可以替换热块。

### 3.5.3 Complete Decision Procedure：完整算法流程

**先说明触发时机。** 请求到达时建立策略；Prefill 完成后提供已封存状态；Decode 每增加配置的 Z 个 token 触发请求复核。Slack、上下文、预算或副本状态显著变化也可以提前触发。Z 是系统配置，与物理块大小分别定义。每次复核可以保留原 R/D/P、L 和块集合；不要求每个 checkpoint 都迁移。但当前算法仍在每次事件纳入这些决策，完整评估开销需要测量，不能把“没有迁移”写成“没有决策开销”。

**Algorithm 2 将前两个小节串起来。** 输入受事件影响的请求、Slack、固定 Z、画像、Router 目标和 Adapter 预算；输出实际获准的保护与已提交 Peer 集合。流程为：

1. 查询已有副本、引用、预算和预留，形成资源快照。
2. 按 Slack 和稳定请求标识排序，对每个受影响请求执行 3.5.1 的 R/D/P 判断。
3. 对 D/P 先复用有效 DRAM 副本，再申请缺失覆盖，并保留失败回退。
4. 形成每层热块候选、keep 方案和深度候选，按 3.5.2 比较 L 与放置代价。
5. 选择足够稳定的改进或可行回退，生成保留、降级、新增计划；只用选中的计划更新虚拟资源快照。
6. 物理执行前原子地核查并取得预留，按实际复制和释放进展发布结果。

**解释增量更新。** 已有兼容且能在故障后存活的有效副本增加保护引用即可，相同版本的在途复制可合并依赖，但必须等待完成。若请求此前为 R、历史增长后首次需要 D/P，必须补齐目标 checkpoint 缺失的历史依赖，不能只存最近 Z 个 token。后续复用已提交历史；热集保留交集，仅补新增对象，退出对象按 3.6 安全降级。

**解释 checkpoint 何时有效。** 决策、在途复制和提交是不同状态。匹配模型/权重与布局、所需层与 TP 分片、封存 token 区间、选择器状态及 token 日志的完整 manifest，才形成新的有效恢复前沿。新副本尚未完成时保留旧前沿；Peer 与 DRAM 可以分别提交，但 Peer 被拒绝不表示 DRAM 已接纳。复制积压时 N 可以超过 Z；复制队列受字节和操作数限制，合并尚未启动且已被替代的计划，无法预留时跳过新申请并报告滞后。预演不是预留，实际获准的 L/K 与计划不符时再次复核。

**解释恢复正确性与验证边界。** 备份预测不改变模型原生注意力选择。恢复时先还原必要 selector 状态，按真实需求取得缺失块；预测错误影响流量或等待，不应丢弃模型要求的输入。批量重放是否等价于逐 token 重放需验证，不满足约定时逐 token 执行。画像校准、策略复核开销、动态迁移和端到端 WCT 收益仍属于待验证内容。

**贯穿例子与后续证据。** 用一个请求说明：历史较短时不追加保护；增长后补齐 DRAM 前沿；恢复暴露增加时竞争 Peer；之后 K 可以不变而块身份替换；请求结束或容量收缩后释放或降级。后续分析/模拟应在固定 Z 下展示不同 M/N 的 L—字节—等待关系，以及目标和已提交 L/K 的演变；这些图尚未绘制。正常复用与故障保护的区别可参考 [KVFlow](https://arxiv.org/html/2507.07400v1)、[ECHO](https://www.usenix.org/conference/osdi26/presentation/liu-guangda)和 [SYMPHONY](https://www.usenix.org/conference/nsdi26/presentation/agarwal)，具体收益仍需匹配条件的对比验证。

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
