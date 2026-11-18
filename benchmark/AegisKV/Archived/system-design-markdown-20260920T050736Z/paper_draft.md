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

![Figure 1(c)：上下文规模与恢复成本，原 Figure 2](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/recovery-cost.png)

[Figure 1(c) PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/recovery-cost.pdf)

**Figure 1(c) 支撑第二个动机。** 已替换为 Qwen2.5-7B-Instruct-1M 的三路径实测；旧版四模型 AIConfigurator 估计独立归档。当前绘图长度为 8K, 64K, 256K, 1,010,000 tokens。在 1,010,000 总上下文处，HBM、DRAM、Recompute 分别为 **15.89 s、17.37 s、1088.53 s**。DRAM 已避免大部分历史重算；HBM 额外减少的是传输等待，不能将它与无副本的全部差距当作 Peer 相对 DRAM 的收益。

条件：同次分配的 2 张 A100-PCIE-40GB、TP2、BF16 权重与 KV、batch 1；SGLang 0.5.10rc0 原生 DCA，关闭稀疏加速，固定支持 A100 的注意力构建和 FlashInfer SiLU。总上下文 C=M+64：HBM 已驻留全部历史；DRAM 从 pinned host memory 实际 H2D 完成后计算尾部，不使用假设带宽，也不与计算重叠；Recompute 从空缓存按至多 8K 的块重建 M，再独立处理同一段 64-token 尾部。固定 M/64 分块边界，保留另一个合并尾部分块未通过校验的诊断，不将它混入曲线。

一个固定合成文本流，各长度各路径预热后一次正式计时；参考状态构造充当 Recompute 预热。没有独立 workload 重复，因此不绘制误差线或声称性能分布。所有正式点均通过尾部各层 KV、hidden state、decode 检查及后续 greedy token 校验。计时在尾部 KV 全部完成后停止，不含词表投影、检测、排队、模型加载和服务接管；这是 worker 微基准，不能直接证明 WCT 收益或长上下文回答质量。

[原始配对数据与配置](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1516025/measured.json)；[逐次记录](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1516025/trials.jsonl)。

**独立衔接段：故障发生在工作流不同位置，会产生不同的 WCT 影响。** 在两个动机之后单独展开这一段，用 Figure 2 将“重建代价”和“工作流位置”联系起来。

![Figure 2：不同故障位置的重建时间与 WCT 损失，原 Figure 1(c)](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/recovery-exposure.png)

[Figure 2 PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/recovery-exposure.pdf)

**Figure 2 用于引出 AegisKV。** 对 Figure 1(a) 的四个活动分支，在同一个 29.5 秒时刻分别假设施加故障。A1 重建约需 35.2 秒，但其 91.2 秒余量可以吸收这一代价；A2 只需 32.2 秒，却因零余量而全部暴露给 WCT。A3 和 A4 分别产生 17.6 和 17.0 秒的 WCT 损失。因此，重建更便宜的分支也可能更需要保护。

这四行是独立的单分支反事实，不是四个分支同时故障。重建时间采用活动请求的 64-token hash-block 输入代理，加上假设尾部，以 Qwen3-14B/A100 的静态模型估计；其他执行和排队保持不变。本例解释依赖传播机制，多请求同时恢复及其资源竞争需要另行评估。

**本节最后自然引出系统：** AegisKV 面向工作流完成时间分配有限的 KV 保护资源，将请求的延迟容忍度与其 KV 的实际恢复价值联系起来，并考虑保护占用 HBM、DRAM 和带宽对正常服务的影响。已有有效缓存仍可参与恢复；新增保护需要以额外成本换取可见的恢复收益。具体的请求级决策、请求内放置、容量控制与故障接管放到 System Design。

**配图顺序已同步到 LaTeX：** Figure 1 为通栏三联图，依次是工作流例子、分支时长差分布、恢复成本；Figure 2 为独立单栏恢复暴露图。图文件继续使用语义名称，编号由 LaTeX 管理。


# 3. System Design

**本章的组织主线：先定义共享接口与可恢复状态，再展开请求间和请求内两级决策，最后说明容量收缩与故障接管如何兑现这些决策。** 预测器放入它服务的请求级决策中；Recovery Manager 在概览中先绑定目标，在末节执行故障接管。模块职责保留，旧节号不作为约束。

| 新章节 | 核心问题 | 主要责任主体 | 主要输出 |
| --- | --- | --- | --- |
| 3.1 Overview and Recovery Contract | 和正常服务如何分工，保证什么？ | Controller、Recovery Manager、引擎 | 目标绑定、接口、恢复约定 |
| 3.2 Incremental Checkpointing and Shared Replicas | 在已有缓存上补什么状态？ | KV Master、目录、Connector | 保护引用、已提交恢复前沿 |
| 3.3 Protection Across Requests | 有限保护优先给谁？ | Tracker、KV Master | 请求的追加保护级别与准入顺序 |
| 3.4 Placement Within a Request | 一个请求保存哪些层与块？ | KV Master | 请求独立的 L、各层实际 K 与更新计划 |
| 3.5 Capacity Adaptation and Safe Demotion | 正常推理需要空间时如何退让？ | Adapter、共享分配器 | 窗口 Peer 预算、真实释放量 |
| 3.6 Failure-time Takeover and Recovery | 故障后如何从这些状态继续执行？ | Recovery Manager、引擎、Connector | 经核查的恢复与继续输出 |

## 3.1 Overview and Recovery Contract

**第 1 段：用整体图说明责任。** 正常缓存继续决定健康运行期间的复用、卸载和普通淘汰；AegisKV 根据工作流和恢复需求提出额外保护。数据目录、分配器和传输执行共享，策略职责分开。

![现有 Figure 4：AegisKV 的控制与数据路径](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/system-overview.png)

[原始 PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/system-overview.pdf)

**本图用于第 1 段，承担模块导航。** 保留等比例单栏。现有 Local KV、Peer KV、Shared DRAM、directory 与 Connector 可以承载新叙述，但图中尚未明确“普通保留与保护引用”的边界。正式改图时补充这一边界即可，模块徽标不再用于推断章节次序。

**第 2 段：先给出恢复目标绑定。** 请求到达、普通 Router 选好源 DP 后，Recovery Manager 绑定兼容的存活候选 DP。Peer 备份目的地与恢复目的地一致，便于故障时本地使用 HBM。绑定不预留计算或显存；负载变化或目标失效时，重新核查位置与可行性。

**第 3 段：明确故障恢复的最低约定。** 已确认 token、请求/工作流身份、目标、对象版本和 checkpoint manifest 在源故障域外可获取。一个有效前沿需要匹配的模型/布局、层与分片、选择器状态和 token 历史，而不是某个块复制结束。缺失 KV 可以依赖可恢复输入重建；“请求还能重算”与“已经承诺的 checkpoint 有效”是两种不同状态。

**第 4 段：定义与基础系统的接口。** 查询副本及保留状态；申请/释放保护；按统一账本核查容量；接收提交、淘汰、请求/工具与故障事件。普通策略也要遵守保护引用和正在执行的 I/O 引用，保护申请则可能因预算不足被拒绝。这里提出的是需实现的接口，不宣称可以无修改套到任意引擎。

**写作取舍。** 参考 [LUMEN 的概览](https://arxiv.org/html/2606.17787v1#S4.SS1)先交代状态和控制点的方式，但本节不展开其模型重载辅助机制。AegisKV 当前目标是存活兼容副本上的 KV 恢复；[RaidServe](https://mast.stanford.edu/pubs/raidserve/)处理不规则 GPU 可用性下的 TP 服务，涉及另一层执行拓扑问题。

## 3.2 Incremental Checkpointing and Shared Replicas

**本节是正常缓存与容错的接口落实：读者要先知道“保护了什么”，才有基础理解后面的保护优先级。**

**第 1 段：定义对象与复用条件。** 对象按模型/权重与布局、相同前缀和位置、层、分片、封存 token 区间及版本标识。多个请求可引用同一兼容副本，物理字节只计一次。角色相同或文本片段相同不足以自动认定 KV 相同。

**第 2 段：解释从缓存到保护的增量动作。** 已有有效且能存活的 DRAM 副本，添加保护引用即可；没有则复制缺失状态。相同版本的在途复制可合并依赖，但不能提前发布为已提交。DRAM 需要显式接纳，保护使普通缓存不能回收的占用也要计费。

**第 3 段：覆盖 prefill、decode 与上下文增长。** Prefill 完成后提供已封存状态，decode 每新增配置的 `Z` token 触发策略评估；`Z` 与物理块大小不同。当前 trace 的 64-token 映射只是一个配置，不能写成稀疏注意力的普遍规定。若请求此前没有 checkpoint，后来因上下文增长需要保护，应补齐目标前沿缺失的历史依赖，而不是只保存最新 `Z` token。

**第 4 段：发布有效 checkpoint。** 请求复制和完成复制分开；只有所需依赖完整提交，才发布新 manifest 并替代旧前沿。复制拒绝、失败或滞后时继续使用旧前沿，报告更长重放尾部；没有前沿则由可恢复输入重建。Peer 与 DRAM 可独立复制与提交，Peer 热集不能冒充全量恢复覆盖。

**第 5 段：解释请求结束和工具交接。** 分别维护正常缓存保留、请求的保护引用、物理计算/I/O 引用。本轮请求结束可以释放本轮保护，正常策略仍可保留历史供下一轮复用；共享块的其他拥有者继续持有引用。若要跨工具等待承诺 Agent 级 KV 保护，需要另定寿命与预算，不能把普通缓存 TTL 当作该承诺。

**建议补图：共享副本与保护引用。** 放在第 2 段后：用同一份 DRAM 对象画出“普通复用引用”和“故障保护引用”，旁边只画缺失后缀的新增复制。沿用这份对象，在第 5 段解释释放一个引用不等于删除数据。当前系统概览不能替代这个生命周期图。

**与文献的关系。** [Mooncake](https://www.usenix.org/conference/fast25/presentation/qin)提供 KV 分层存储的背景，[DéjàVu](https://proceedings.mlr.press/v235/strati24a.html)说明流式 KV 状态复制的用途；共享已有对象并不免除 AegisKV 对版本、保留与故障域的检查。它们是接口和机制参考，不意味着本方案已适配其完整实现。

## 3.3 Workflow-aware Protection Across Requests

**本节对应第一层核心决策：决定哪些请求需要追加保护，以及谁先获得有限预算。**

**第 1 段：把 Tracker 作为输入生成机制。** 根据当前残余 DAG、进度与部署校准的剩余时间估计得到 Slack。分支/汇合处分段，避免父任务等待与子任务计算重复统计；未知依赖或预测不足使用保守值。Tracker 不再单独撑起一个“预测器贡献”小节。

**可选配图：已有轨迹预测结果。** 如果需要说明采用既有预测能力，可在第 1 段后引用下图；若篇幅有限，保留原论文引用即可。

![现有 Figure 3(a)：已有 Agent 轨迹预测结果，可选](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/agent-prediction.png)

[原始 PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/agent-prediction.pdf)

**本图的作用与边界。** 它引自 Heddle，展示剩余轨迹长度的相关性；不等于剩余执行秒数的准确率，也不是 AegisKV 或本地 GBDT 的验证。该图不会单独证明 Slack 可用性。

**第 2 段：比较不追加保护与追加保护。** 从已有副本出发估计可行恢复路径，再结合 Slack 和资源代价决定额外投入。把原 R 标签解释为“不追加保护”：恢复时仍允许命中普通缓存，只有缺失状态才重算。

| 请求级动作 | 它改变什么 | 它不保证什么 |
| --- | --- | --- |
| 不追加保护 | 不新增或续接额外保留承诺 | 普通缓存仍可命中，但未被承诺的副本可能消失 |
| DRAM 保护 | 确保接纳并提交指定恢复前沿 | 不保证加载比重算快，也不消除排队 |
| 申请 Peer 加速 | 允许该请求竞争快速驻留 | 零 Slack 或候选资格不保证获得 Peer 容量 |

**第 3 段：给出请求间准入规则。** 对受策略事件影响的请求，按声明的 Slack/恢复暴露优先级评估，并将新增物理字节、已有共享副本和当前保护引用纳入可行性检查。不得只列一个优先级分数而不说明容量不足时怎么做。现行设计可保留 Slack 优先的启发式，但不宣称它是全局最优 WCT 分配。

**第 4 段：说明竞争与系统影响。** 正在运行的其他请求所持 Peer 保护引用不能被普通新请求抢占；没有可安全释放空间时拒绝本次 Peer 增量，正常推理仍继续。已有副本、复制与未来重算都会影响其他请求，不能把“自身 Slack 足够”作为全系统成本为零的依据。

**第 5 段：说明不确定性和刷新。** Slack、副本状态、历史长度和恢复目标负载改变时复核；不要求每个新 token 都重新求解。未知故障尾部按声明的未来状态画像评估，不能直接设成 `N=Z`。若使用故障概率，其时间范围与健康运行成本要一致，但本轮 `Z` 仍固定。

**算法安排。** 本节给出请求级保护选择的短伪代码：查询状态 → 估计当前路径 → 判定追加保护 → 提交 DRAM/Peer 申请 → 接纳失败时保留可行回退。块集和层数调用 3.4 的子过程。这样能直接回应对话中“请求优先级与请求内部优先级应分层介绍”的要求。

**与文献的关系。** [KVFlow](https://arxiv.org/html/2507.07400v1)的未来访问距离用于正常复用，而本节使用故障恢复对工作流的影响；两者需要明确区分。现有 2.2 的工作流示例用于解释这一动机，不是本节策略的性能结果。

## 3.4 Recovery-driven Placement Within a Request

**本节对应第二层核心决策：一个已进入保护评估的请求，具体应该在 Peer HBM 保留多少层、每层哪些块？**

**第 1 段：先确定真实恢复需求。** 重放尾部会跨 Query、层和 KV 组产生历史需求。需要恢复原生 selector 的辅助状态，并取真实选择所需对象的并集；不能只用一次 Query 的 top-k 代表整个恢复工作集。实际需要的块无论在 HBM、DRAM 还是已重建区，都应可以被选择。

**第 2 段：用已有覆盖率图说明候选块可以预测，但收益有限。** 历史访问频率用于选择候选，强制所需状态单独检查；预测误差产生等待或流量，不能通过跳过必要输入改变原生注意力。

![现有 Figure 3(c)：过去访问对未来恢复 KV 的覆盖](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/retry-kv-prediction.png)

[原始 PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/retry-kv-prediction.pdf)

**本图用于第 2 段。** 相同字节预算下，比较历史频率与近期性；每个模型 3 个 PG19 文档，胡须为文档范围。NOSA、MiniCPM4、Seer 的差异说明该机会依赖模型与块粒度。它支持候选信号的可用性，不证明 Agent 重试性能，也不能将覆盖率直接换算为 WCT 收益。

**第 3 段：定义 L、K 和物理粒度。** `L_r` 是请求自己的目标 Peer 层深；`K_{r,l}` 是该请求该层实际已提交驻留的块数。目标配额可以固定为块数，也可以按历史比例设定，因此历史增长不必导致 K 永远增长。即使数量不变，块身份也会改变。所有设置要声明，K 不等于 selector 的 top-k 或在途传输数量。

**第 4 段：用恢复流水说明哪些层值得提前驻留。** 逐层计算可以隐藏后续传输，Peer 的价值是消除仍暴露的等待。结合请求的历史 `M`、未提交尾部 `N`、带宽和计算画像比较候选层深；不把某个案例推成全窗口统一 L。

![现有 Figure 5：恢复流水与 Peer 的额外作用](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/recovery-pipeline.png)

[原始 PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/recovery-pipeline.pdf)

**本图用于第 4 段。** 先说明 (b)/(c) 已有的按层流水及预取收益，再比较 (c)/(d) 的 Peer 增量。数据由实测 forward 延迟派生的层均值和假设带宽组成；7 层、约 147 MiB 属于固定历史/尾部案例，不是算法输出的普遍定值。该图不能作为 Adapter 控制统一 L 的证据。

**第 5 段：写出请求内的选择与更新过程。** 保留当前放置和若干层深作为候选，按预测的暴露等待减少、迁移字节与容量代价选择稳定改进。新旧热集保留交集，退出旧块，只传入新增块；实际容量不足可缩小增量或维持当前集合。若限定为前若干层，明确这是控制搜索范围的启发式。

**第 6 段：给出一个贯穿整个请求的例子。** 前期历史短、不值得追加；历史增长后补齐 DRAM 前沿；需要更快恢复时竞争 Peer；随后配额不变但热块替换；最后请求结束或系统收缩。这个例子应复用 3.2 的对象身份和事件，不再另引一组抽象符号。

**算法安排。** 本节展开 3.3 调用的块级子过程：生成候选 → 预演交集/退出/新增 → 核查依赖、临时空间与引用 → 比较收益成本 → 发布实际提交集合。不同请求各有 L；Adapter 只给总容量。

**与文献的关系。** [ECHO](https://www.usenix.org/conference/osdi26/presentation/liu-guangda)已经研究原生稀疏注意力中的无损预取与加载重叠，[SYMPHONY](https://www.usenix.org/conference/nsdi26/presentation/agarwal)已经根据网络结构和请求优先级管理 KV。AegisKV 应解释恢复目标、故障状态与工作流影响怎样改变驻留决策，不能把“预测热块”或“优先较早层”单独视为新贡献。

**建议补图 D〔分析或模拟优先〕。** 在固定 `Z` 下画若干明确的 `M/N` 或故障阶段条件中的 L—Peer 字节—暴露等待关系；再画一个请求随上下文增长的计划/已提交 L 和 K 轨迹。各条件使用同一恢复终点与强 DRAM 加载策略。未知故障时刻用声明的分布或分位数，不以单个尾部替代全部情况；本轮仅定义设计，尚未绘制或运行。

## 3.5 Capacity Adaptation and Safe Demotion

**本节回答健康运行压力变化时的资源闭环，容量控制由 Adapter 负责。**

**第 1 段：说明窗口预算。** Adapter 在每个时间窗口估计正常 KV 使用和增长余量，给目标 DP 发布 Peer 总容量。可以沿用管理池一半的配置上限；管理池排除权重和固定运行时状态，预算包含现有 Peer 占用。正文不固定为 5 秒；窗口内每次申请仍核查物理空间。

**第 2 段：明确请求竞争与系统收缩的权限差别。** 普通请求不能抢占其他运行请求的保护副本；Adapter 为正常服务收缩容量时，可以让带保护引用的副本降级到 DRAM。它改变的是物理驻留位置，而不是绕过正在执行的 kernel/DMA 引用。

**第 3 段：解释安全降级。** 先确认是否已有有效 DRAM 副本；有则复用，没有则申请空间、写回并提交。接着切换目录，禁止新读者进入旧地址，等待旧使用者释放引用，最后返还 HBM 空间。DRAM 失败时保留仍受承诺的旧副本，报告未完成收缩。

**第 4 段：处理资源账本和反馈。** 正常缓存、保护对象、在途传输、临时空间和待释放缓冲区都计入物理占用。目标预算不是瞬间可用空间；收缩期间正常准入仍可能等待。复制与迁移需要限流及进展保障，实际释放与保护覆盖变化通知 KV Master，随后由它复核每个请求的 L。

**算法安排。** 保留一个容量更新与安全降级伪代码：估计需求 → 发布预算 → 停止超预算准入 → 优先安全回收 → 必要时迁移受保护对象 → 提交/切换/排空 → 报告实际占用。`Z` 固定，Adapter 不承担请求级层数决策。

**配图安排。** 回引 3.1 的 Figure 4 解释控制对象，沿用3.2 建议的共享副本图及其迁移面板解释第 3 段。后续容量时间序列可同时画“目标预算、实际占用、待释放字节、前台需求”，但现有恢复流水图无法替代这项验证。

**文献参考。** [TokenCake](https://arxiv.org/html/2510.18586v4)与 [Continuum](https://arxiv.org/html/2511.02230v6)说明健康状态下空间与任务进度的联系；[SYMPHONY](https://www.usenix.org/conference/nsdi26/presentation/agarwal)提供协同内存管理的参考。这里的具体 Peer 预算和保护降级仍是 AegisKV 需要验证的设计。

## 3.6 Failure-time Takeover and Demand-driven Recovery

**本节让前面的保护决策形成完整闭环：恢复位置已绑定、checkpoint 已提交、Peer 热集已准备，故障发生后怎样继续执行？**

**第 1 段：确认并隔离故障。** Recovery Manager 确认源执行失效，隔离旧 epoch，从存活控制状态取得请求和 token 日志。未确认故障或尚未完成隔离时，不把两份执行都当成可提交的有效源。

**第 2 段：选择有效前沿与当前目标。** 核查目标模型、实际可用空间和副本版本；Peer 只有在真实恢复目标上才能算本地驻留。目标变化时重新解析位置；半份复制和已失效地址不能使用。需要的普通缓存副本可以参与恢复，但仍须通过相同有效性检查。

**第 3 段：按真实需求推进计算。** 先恢复必要的选择器和模型状态，再按原生选择获取输入；已驻留块直接用，DRAM 缺失块按需取，无可用状态时依赖日志重建。未命中不能被跳过；重放方式必须满足声明的原生语义和数值约定。

**第 4 段：解释并发恢复与健康请求共存。** 多个 retry 按各自数据就绪与引擎支持的执行边界推进，不因备份优先级形成“一个请求恢复完才轮到下一个”的屏障。计算、HBM、链路和 TP collective 的实际约束仍需满足；空闲 Peer 副本不自动提供恢复执行空间。

**第 5 段：写清完成条件和回退。** 请求恢复后从已确认 token 之后继续输出，并避免重复交付。复制中故障、迁移中故障、目录版本变化、DRAM 不足和目标失效分别说明可用旧前沿或重算回退。释放或转移旧保护引用后，正常缓存继续决定健康复用生命周期。

**配图安排。** 第 1–2 段回引 Figure 4 的恢复绑定和 Retry 路径；第 3 段回引 Figure 5 的按需加载和计算流水；第 5 段沿用3.2 建议的共享副本图中的提交/迁移状态。不再为相同数据路径重复画一张 Overview。

**本章收束。** 请求级和块级策略是本设计的主要分配机制，checkpoint、引用与接管约定使其可执行，Adapter 约束其健康运行代价。性能是否成立需在同一正常缓存与物理资源配置下，对强 DRAM 容错和 AegisKV 进行有故障/无故障配对验证；更强正常缓存可能减少可获得的追加收益。现有图像尚不能证明新的两级策略、动态迁移或端到端 WCT 改善。
