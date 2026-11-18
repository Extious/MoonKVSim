# AegisKV：跨 HBM、DRAM 与共享存储的工作流感知 KV 检查点

> 完整中文译稿，对应 [英文论文 main.pdf](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/main.pdf)。章节、图、公式、算法及参考文献编号与英文稿一致；图像沿用原图，正文和图注逐段翻译。

## 摘要

多 Agent 应用在执行相互依赖的 LLM 请求时会不断积累可复用上下文。一个 worker 故障可能导致这些状态丢失，并同时延迟多个分支，而将所有上下文都保护在快速内存中的成本很高。我们提出 AegisKV，一种跨 Peer HBM、共享 DRAM 和共享存储管理 KV checkpoint 的工作流感知系统。三个层级中的互斥受管对象共同覆盖一个已提交 checkpoint。AegisKV 结合正常复用、带 guard 的工作流 slack 和因果稀疏需求，确定保护优先级。固定层／块配额在兼容的接管 DP 上加速选定请求；下层可续租信用和有界惰性更新管理容量压力。带版本的状态转换在迁移和显式回退期间保持恢复有效性。每个 DP 的 Adapter 调整 Peer 总容量，Master 更新请求成员与热块身份，而不改变校准后的配额或原生注意力语义。我们将实机重建微基准和留出 trace 诊断，与可复现的分析对照和匹配实验协议结合起来。在 36 个明确声明且禁用 Peer 的场景中，放置模型在 17 个场景中优于 LRU，在 19 个场景中持平。匹配条件的分析调度展示 Peer 的额外重叠收益；这两类模型都不是对三层系统的实测。历史中断时序驱动一个独立恢复负载模型，其中平均值下降与尾延迟恶化并存。历史分析对照揭示放置与重叠的交互，以及一项租金退化；实验协议检验资源竞争、预测误差和提交滞后如何影响当前控制器。要确立所提系统的性能，仍需端到端故障注入和正常服务测量。

## 1　引言

当多 Agent 应用的必要结果就绪时，应用才算完成：结果可能是经过测试的代码补丁、一份报告，或由并行搜索汇总而成的答案。因此，一个 LLM 请求的价值取决于它在工作流中的位置。关键分支上的延迟会推迟完成时间，另一个分支则可能在汇合前吸收这段延迟。面向应用的服务系统已在正常执行中利用这种结构[[14]](#ref-14)、[[17]](#ref-17)、[[20]](#ref-20)。故障提出了进一步的问题：当一个 worker 故障同时中断多个请求时，哪些历史应当保持快速可恢复？

长上下文使这一选择的成本变得高昂。Agent 会积累推理、代码和工具结果；丢失其驻留在 GPU 上的 KV 后，可能需要大量重建工作。Checkpoint 可以避免这些工作[[10]](#ref-10)、[[27]](#ref-27)，负载感知的恢复机制则将中断请求分配到不同位置[[3]](#ref-3)。分层缓存提供 DRAM 和存储容量[[21]](#ref-21)、[[28]](#ref-28)，但将每段历史都保留在较快层中的成本很高。

仅凭最近访问情况和恢复延迟无法决定放置。一段较长且最近使用过的历史，可能属于能够容忍存储访问延迟的分支，而较短的历史却可能位于关键路径上。较大的 slack 不能成为删除可复用历史的充分理由：后续正常调用可能反复重建该历史。同一 worker 的故障还会通过 DAG 和共享恢复资源耦合多个请求。只加速两个延迟分支中的一个，可能不会改变其汇合时间。最后，降级迁移是异步的：在存储层替代副本提交之前释放 DRAM，会使保护失效。

AegisKV 跨 Peer HBM、共享 DRAM 和共享存储管理 checkpoint。Tracker 估计工作流剩余时间；Master 结合正常复用、带 guard 的 slack 和因果块需求。三个受管层级持有互斥对象，其并集覆盖一个已提交 checkpoint。校准后的层、块和 checkpoint 配额针对兼容模型／布局固定。贪心 Peer 准入保护零 slack 请求，下层可续租信用采用有界惰性刷新。Router 绑定兼容的接管 DP；Adapter 调整 Peer 总容量；Connector 执行传输并报告结果。带版本的 manifest、资源预留和 reader lease 在迁移、容量压力缓解与显式回退过程中保持恢复有效性。

我们提出的贡献包括：感知工作流与访问需求的保护优先级；具有安全所有权转换的有界三层控制器；以及基于实机路径测量、留出 trace 诊断和分析对照的匹配评估协议。现有证据揭示了历史分配模型中的收益和持平、预测平均误差的小幅改善，以及队列尾部和租金退化。它们约束设计，但不验证当前控制器。核心经验假设是：在计入健康服务和迁移成本后，工作流感知保护可以改善有限资源分配。

## 2　背景

本节介绍基于 DAG 的 Agent 工作流如何映射到 LLM 服务系统，以及服务 worker 故障后系统如何恢复 Agent 的 KV 状态。

### 2.1　基于 DAG 的 Agent 工作流服务

多 Agent 应用通过协调具有不同职责的 Agent 完成用户任务。Agent 可以生成中间结果、调用外部工具、委派子任务，并使用其他 Agent 产生的输出。这些依赖构成有向无环图（DAG）：每个节点代表一次 Agent 调用，每条边代表数据依赖或控制依赖。

**Workflow** runtime 维护 DAG，并在依赖满足后释放相应调用。Fork 允许多个调用并行执行，join 则要求下游调用等待所有必要前驱完成[[14]](#ref-14)。

一个 **Agent** 可以在同一工作流中被多次调用。每个 turn 的输入可以包含 Agent 专属指令、此前的模型输出、工具结果，以及其他 Agent 传来的输出。这些输入形成不断演化的 Agent 历史，由工作流 runtime 保留。

[图 1](#fig-serving-model)展示 Agent 调用到 LLM 服务系统的映射。就绪调用作为推理请求提交，并在模型 workers 之间调度。一个 **worker** 包含一个模型副本，或一个跨张量并行（TP）组的分布式副本[[25]](#ref-25)，可以同时服务来自多个工作流的 Agent。

请求处理包括 prefill 和 decoding。Prefill 处理输入 tokens，并为每个 Transformer 层生成 KV cache；decoding 则为新生成的 tokens 追加 KV。当同一 Agent 的后续调用复用相同历史前缀时，对应 KV 允许 worker 只处理新增输入，而不必重新 prefill 完整历史[[7]](#ref-7)[[33]](#ref-33)。因此，活跃 Agent 会在迭代的 turns 中积累 KV 历史。

KV cache 按模型并行配置分布[[13]](#ref-13)。在 TP 下，每个 rank 保存自己的 KV 分片，以及注意力实现所需的元数据。因此，复用 KV 需要模型版本、并行配置、数值格式和 KV 布局兼容。

<a id="fig-serving-model"></a>

![图 1：基于 DAG 的 Agent 工作流服务](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/serving_model.png)

**图 1：** 基于 DAG 的 Agent 工作流服务。工作流 runtime 维护工作流依赖和已接受的 Agent 历史。就绪调用被调度到模型 workers，workers 在 Agent 的迭代 turns 之间保留相应 KV cache。

### 2.2　Worker 故障与 KV 恢复

本文考虑使模型 worker 不可用的 fail-stop 故障，worker 可以是一个模型副本或一个 TP 组。故障可能来自加速器、服务进程、主机或通信[[3]](#ref-3)[[10]](#ref-10)。受保护的故障域取决于部署，可以对应进程、分布式模型副本或整台主机。恢复副本只有在相应故障域失效后仍然可达，才能提供保护。例如，主机本地 DRAM 或 SSD 可能在进程故障后仍然可用，但不能保护主机故障。

一个 worker 可以保存多个 Agent 和工作流的 KV。因此，一次 worker 故障可能同时中断同一工作流的多个分支，以及来自其他工作流的 Agent。本文将同一次 worker 故障导致 KV 不可用的全部调用视为**一个故障事件**。

本文假设工作流 DAG、已接受 tokens 和已完成工具结果保存在故障 worker 之外。因此，受影响调用可以重新提交给兼容的幸存副本，使用相同的模型版本、并行配置、数值格式和 KV 布局。本文聚焦模型 worker 故障，因为它会移除大量 worker 本地 KV 状态，但工作流仍可从持久化输入恢复。工作流 runtime 或持久化 token 存储的故障与本文问题正交，可以通过常规复制机制处理。与这些控制状态和持久化状态不同，KV cache 随 Agent 历史增长，使完整复制成本高昂，由此产生本文研究的资源分配问题。本文假设至少一个声明的恢复域仍然可用。

如果没有幸存 KV 副本，替代副本必须 prefill 每个受影响 Agent 保留的历史，然后才能恢复生成[[27]](#ref-27)。另一条路径是恢复与某个已接受 token 前缀对应的完整 KV checkpoint，再重放该前缀之后已接受的 tokens[[27]](#ref-27)[[3]](#ref-3)。完整 checkpoint 包含所有模型层、所有模型并行分片所需的历史 KV tensors 和注意力元数据。部分 KV 副本可以加速恢复，但不能独立提供完整恢复覆盖。

<a id="sec-motivation"></a>

## 3　动机

如第 2 节所述，发生故障的 Agent 可以根据持久化输入重建 KV cache，也可以恢复幸存的 KV checkpoint[[27]](#ref-27)[[3]](#ref-3)。重建避免了正常执行期间的 checkpoint 开销，但需要重新 prefill Agent 累积的历史。Checkpoint 避免了这种重复计算，但随着 Agent 历史增长，会持续消耗内存与 I/O 资源。

本节首先量化为什么完整保护所有 Agent 的 KV 状态成本过高，随后提出指导 AegisKV 设计的三个观察。

### 3.1　完整 KV 保护成本高昂

Agent 的 KV 状态会在迭代执行过程中不断增长。后续调用通常包含此前的模型输出、工具结果和其他 Agent 的输出。因此，工作流后期发生的故障可能比早期故障丢失多得多的 KV 状态。

我们在两张 A100 PCIe 40 GB GPU 上使用 Qwen2.5-7B-Instruct-1M[[22]](#ref-22)[[11]](#ref-11)，以 TP=2、BF16 权重和 KV 状态、batch size 为 1，量化由此产生的恢复成本。我们将完整 KV 重建与从 HBM、主机 DRAM 和共享存储复用 KV 进行比较。完整重建从空 KV cache 开始，prefill 整个上下文。每条复用路径均从相同的历史 KV 状态开始，并处理一个额外 token。

当上下文长度为 1M tokens 时，完整重建耗时 571.2 s。复用历史 KV 状态后，从 HBM、主机 DRAM 和共享存储就绪所需的时间分别降为 1.3 s、2.7 s 和 10.2 s。对应的历史 KV 状态在两个 TP ranks 上共占 57.9 GB。因此，保留 KV 可以避免数百秒的重建，但单个长时间运行的 Agent 就可能需要数十 GB 的 checkpoint 容量。

### 3.2　O1：不同 Agent 的恢复价值不同

Agent 的 KV 重建时间并不直接决定它对工作流完成的影响。[图 2(a)](#fig-agent-value)展示一个 fork–join 工作流：A2 决定汇合时刻，而 A1 提前 91.2 s 完成。短于这一时间间隔（称为 slack）的延迟不会推迟下游阶段。

这种分支差异在我们分析的 traces 中很常见[[24]](#ref-24)。在 121 个包含根据时序推断的 fan-in 组的工作流中，最大分支时长差的中位数为 138 s，90 分位数为 1,173 s。由于 trace 没有显式依赖边，这些差值并非故障时 slack 的直接测量，但它们表明并行 Agent 对延迟的容忍程度可能存在显著差异。

[图 2(b)](#fig-agent-value)将示例工作流与其中四个活跃 Agent 的实测 KV 重建时间结合起来。相近的重建延迟并不会产生相近的工作流延迟。重建 A1 耗时 33.2 s，但该延迟落在 A1 的 91.2 s slack 以内，不会推迟汇合。重建 A2 的耗时与之相近，为 32.6 s，但 A2 没有 slack，因此全部延迟都会推迟汇合。A3 和 A4 的 slack 吸收了部分重建时间，分别留下 16.3 s 和 18.0 s 的工作流完成时间增量。

对于单独考虑的分支 $i$，这一关系为：

$$
\Delta W_i = \max(0, R_i - \sigma_i), \tag{1}
$$

其中，$R_i$ 是恢复延迟，$\sigma_i$ 是剩余工作流 slack。因此，保护最大或重建成本最高的 KV 状态，不一定能带来最大的工作流收益。

一次 worker 故障还可能中断多个 Agent。它们的恢复价值并非总能相加：如果另一个受影响分支仍是瓶颈，加速一个被延迟的分支可能无法提前汇合。因此，保护决策应同时考虑 Agent 在工作流中的位置，以及被同一故障影响的其他 Agent。

<a id="fig-agent-value"></a>

![图 2：不同 Agent 的恢复价值不同](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/agent_value.png)

**图 2：** 不同 Agent 的恢复价值不同。由于并行 Agent 的 slack 不同，相近的 KV 重建时间会产生不同的工作流延迟。纹理部分在汇合前被吸收；实色部分推迟汇合。(a) 在假定全部分支汇合的条件下保留 trace 时序。(b) 报告三次重建测量的中位数与 min–max 范围；WCT 增量是在保持其他执行不变的条件下计算得到的（[附录 A](#sec-motivation-protocol)）。

### 3.3　O2：不同 KV 区域的恢复价值不同

即使对一个重要的 Agent，不同 KV 状态对快速恢复的价值也不相同。[图 3(a)](#fig-kv-value)显示，历史 KV 访问集中于部分块。对于三个被评估的稀疏注意力模型，最热的约 20% 历史块分别贡献了 87.64%、74.76% 和 56.54% 的访问。

仅凭访问频率还不够。在按层顺序恢复时，前面层的计算可以与后面层的传输重叠。复制那些传输本来就会被隐藏的块，不会缩短恢复时间。只有缺失时会引起暴露等待的 KV 状态，才会直接影响恢复时间。因此，将某个 Agent 的完整 KV checkpoint 放入接管 HBM，可能消耗远多于快速恢复实际所需的容量。系统应区分避免完整重建所需的完整状态，以及为了减少恢复停顿而必须立即可用的状态子集。

<a id="fig-kv-value"></a>

![图 3：不同 KV 区域的恢复价值不同](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/kv_value.png)

**图 3：** 不同 KV 区域的恢复价值不同。(a) 历史访问集中于部分 KV 块。(b) 只有暴露在恢复路径上的缺失 KV 传输才会增加恢复时间。(a) 中的模型为 NOSA-8B[[9]](#ref-9)、NSA-8B[[6]](#ref-6) 和 MiniCPM4.1-8B[[18]](#ref-18)。曲线使用三个 PG19 文本的 32,704-token 前缀中最后 512 个 Queries；每个 Query 对同一历史 64-token 块跨 heads 只计一次，并对全部 32 层及文本取平均。阴影表示文本间的 min–max，排序是事后统计。(b) 为示意：L1 KV 已驻留，L2 在 L1 计算期间加载，而较晚完成的 L3 传输产生暴露等待。

### 3.4　O3：复制容量随时间变化

快速 KV 副本与前台推理共享 HBM。随着请求到达与完成、Agent 历史增长，以及活跃执行对 KV 状态和临时工作区的需求变化，可用于复制的 HBM 也会变化。因此，固定复制预算可能效率低下：高负载时，大预算可能挤占前台执行状态；低负载时，小预算又可能使可用 HBM 闲置。复制必须适应可安全使用的容量，避免干扰前台服务。

**小结。** 这些观察共同说明，高效故障恢复需要在两个层面进行选择，并随时间调整。系统必须根据 Agent 对工作流完成的影响区分 Agent，根据 KV 区域对暴露恢复延迟的影响区分 KV 区域，并随前台需求变化调整快速复制容量。第 4 节介绍 AegisKV 如何实现这三项要求。

## 4　AegisKV 设计

AegisKV 分配有限 KV 存储以减少工作流完成时间（WCT），同时保留正常缓存复用。本节先介绍架构，再介绍由[第 3 节](#sec-motivation)中的观察所引出的各组件。

### 4.1　系统总览

AegisKV 将工作流优先级与三层 KV 层级结合起来（[图 4](#fig-system-overview)）。Peer HBM 将选定层与热块保留在另一个数据并行（DP）副本上，以支持快速恢复；共享 DRAM 和存储保留其余状态，用于复用与恢复。三个层级共同覆盖每个已提交 checkpoint，传输完成后每个对象只有一个受管 owner。这种划分使系统能够保留长历史，同时以有界的逐请求配额，将稀缺 HBM 用于零 slack 请求的状态。

图中以两个 DP 副本、每个副本包含两个张量并行（TP）rank 为例。在这一布局兼容、按 head 切分的配置中，各 rank 保存相同 token 位置上不同 KV heads 的分片。Peer 放置将源 shard $i$ 中选定的对象映射到接管 DP 的 rank $i$。

Application 向 Controller 提供请求和工作流进度。**(1)** Workflow Tracker 估计每个 Agent 能吸收多少延迟，**(2)** Recovery-aware Router 选择其执行 DP 和接管 DP。**(3)** KV Master 利用紧迫性与位置信息，决定每个 KV 对象的保留位置，以及哪些热块值得使用 Peer 空间。在 Engine 内部，**(4)** Adapter 随服务需求变化调整可用 Peer 容量。Connector 执行 Master 的传输计划并报告结果。Worker 故障后，Router 将请求重定向到接管 DP；Connector 结合 Peer 命中与下层读取，恢复执行。

<a id="fig-system-overview"></a>

![图 4](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/system-overview.png)

**图 4：** DP=2、TP=2 的 AegisKV 架构，编号 (1)–(4) 与正文对应。每一 TP 行表示一个 GPU／HBM rank。以 DP0→DP1 恢复为例，DP1 的 rank $i$ 保存 DP0 的 shard $i$ 中选定的层／块对象；反方向具有对称能力。Local KV 是执行状态，Peer 保存受管恢复对象。共享 DRAM／存储位于两个 DP 边界之外，保存其余对象。蓝色连线传输 KV，深色虚线传输控制信息，红色虚线表示重试，橙色块为尚未封闭的尾部。图中在 DP1／TP0 展示 Master 与 Connector 的计划下发和状态返回；Adapter 按 DP 合并展示。

### 4.2　Workflow Tracker：剩余时间与 Slack

为在线提供工作流优先级，Tracker 先估计剩余执行时间，再计算 slack。它维护残余 DAG，节点对应已暴露的 fork／join 边界或任务完成边界之间的 Agent segment。一个 segment 可以跨越多次 LLM 调用与工具等待。子任务执行计入子路径，不在父路径重复计入；未知的未来分叉不包含在图中。

GBDT 根据因果特征预测 segment 剩余秒数 $d$：角色／模型、当前输入长度、已耗时、已完成调用数，以及此前调用的长度、耗时和上下文增长。缺失历史使用 mask 标记；训练、校准与评估以完整工作流为单位划分。标签终点位于 segment 边界，未来调用结果绝不作为特征。

[算法 1](#alg-workflow-tracker)以残余 DAG $G$ 和特征 $X$ 为输入。前向／后向关键路径遍历[[12]](#ref-12)以预测的工作流完成时刻为基准，计算最早完成时间 $EF$ 与最晚完成时间 $LF$。两者之差为名义 slack。Guard $g$ 取自校准工作流中 slack 正向高估误差的经验上分位数；扣除它得到建议 slack $s$，而非逐请求保证。同一 segment 中的请求共享该余量。

<a id="alg-workflow-tracker"></a>

**算法 1：剩余时间与 Slack**

| 行   | 操作                                                                        |
| --- | ------------------------------------------------------------------------- |
| 1   | $(G,X)\gets\operatorname{SnapshotProgress}()$                             |
| 2   | $\nu\gets\operatorname{NextVersion}()$                                    |
| 3   | **if not** `Supported`$(G,X)$ **then**                                    |
| 4   | &emsp;`PublishInvalid`$(\nu)$; **return**                                 |
| 5   | $d\gets\max(0,\operatorname{GBDT}(X));\quad g\gets\operatorname{Guard}()$ |
| 6   | $EF\gets\operatorname{Forward}(G,d)$                                      |
| 7   | $LF\gets\operatorname{Backward}(G,d,\max_v EF_v)$                         |
| 8   | **for** $v\in V(G)$ **do**                                                |
| 9   | &emsp;$s_v\gets\max(0,LF_v-EF_v-g_v)$                                     |
| 10  | `Publish`$(\nu,G,d,g,s)$                                                  |

`Supported` 检查输入、依赖、校准与时效性；无效估计不提供正 slack 额度。进度事件与周期刷新向 Master 发布带版本的时长 $d$、guard 和 slack，并使旧优先级估计失效。DAG 遍历开销为 $O(|V|+|E|)$。[第 5.5 节](#sec-eval-prediction)报告已有预测诊断，并规定剩余 segment 的验证实验。

### 4.3　恢复感知的 Router

Router 确定正常执行与恢复执行的位置。正常分派兼顾负载和兼容前缀的局部性。[图 5](#fig-agent-prefix-reuse)显示，主 Agent 和子 Agent 请求的同 Agent 潜在 token 覆盖率分别为 98.7% 和 93.9%。Agent 亲和仅是一种偏好：其他 Agent 的前缀同样可以提供复用机会，对子 Agent 的首个请求尤其如此。

请求到达时，Router 记录一个带版本的接管绑定，目标是源故障域之外且布局兼容的 DP。该 DP 中对应的张量并行（TP）分片可以持有选定 Peer 对象。确认故障后，Router 隔离旧 epoch，并在满足工作区和准入约束的条件下激活目标。新目标不能将旧目标的 Peer 对象计为本地对象：重新绑定时需要取回仍可达的对象；若唯一 owner 已丢失，则使用较旧 checkpoint／重放回退。该绑定为 Master 提供具体访问路径和目标负载，以支持恢复性能估计与 Peer 放置。

<a id="fig-agent-prefix-reuse"></a>

![图 5](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/agent-prefix-reuse.png)

**图 5：** Claude Code trace[[24]](#ref-24) 中按 token 加权的潜在前缀覆盖率：全部 98,827 个请求，拆分为 56,798 个主 Agent 请求和 42,029 个子 Agent 请求。每个请求的覆盖率是其输入与同一工作流、同一模型下更早完成的请求之间的最长公共前缀，按 token 数汇总。同 Agent 与其他 Agent 的柱状存在重叠：其他 Agent 在最佳同 Agent 前缀之外仅额外覆盖 0.37%、0.01% 和 2.05%。这些值表示复用机会，而非运行时缓存命中。

### 4.4　KV Master：面向工作流的分层放置

Master 首先将请求紧迫性与请求内部的 KV 需求结合，再将这一优先级延伸到重复使用与共享使用。可续租信用管理下层保留；固定大小的请求级策略分配 Peer 加速。事件循环将两类策略与实际传输和可用容量连接起来。

#### 4.4.1　感知 Slack 与访问需求的 KV 优先级

两个因素决定一个请求对 KV 块的需求价值：恢复对其工作流的影响程度，以及执行需要该块的可能性。令 $R_r$ 为请求当前放置下估计的恢复延迟，包括下层读取、重放和排队，$s_r$ 为扣除 guard 后的 slack。我们使用暴露比例：

$$
u_r=\frac{[R_r-s_r]^+}{\max(R_r,\varepsilon)},
 \qquad P_{r,l,b}=u_r\,\widehat p_{r,l,b}, \tag{2}
$$

其中，$\varepsilon>0$ 用于避免除零。因此，当恢复需要时间时，零 slack 对应完全紧迫；若 slack 足以覆盖恢复，则消除的是这一恢复紧迫性，而非普通复用价值。无效的 Tracker 估计使用零 slack。$P$ 是排序信号，不是可相加的 WCT 节省量估计。

在一个 dense-attention 层内，后续 Query 需要每个因果可见的历史块，因此这些块的访问因子均为 1。仅仅创建得更早，并不意味着未来价值更高。稀疏注意力则使用最近一段已完成 Query 的窗口：

$$
\widehat p_{r,l,b}=
 \frac{\text{选择块 }b\text{ 的 Query 数}}
      {\text{块 }b\text{ 因果可见时的 Query 数}}. \tag{3}
$$

对每个 Query，同一物理块跨 head 只计一次。可见性在稀疏选择之前定义，而不是在候选剪枝之后定义。在 200 次机会中被选择 40 次的块，其估计需求低于在 30 次机会中被选择 15 次的块；原始次数会颠倒这一排序。经过校准的逐层先验对小分母进行平滑。该因果估计在不修改原生 selector 的情况下预测需求；必需的辅助状态无论测得频率如何，都仍然是依赖项。正是[图 3(a)](#fig-kv-value)所示的访问集中度，使按块估计需求有价值；该估计保持因果性，快层中缺失的块从其 owner 取回。

优先级与保留成本不同。对于同一 dense 层中大小相同、成本相同的块，访问贡献相等；但对象大小、传输路径和重建成本仍可能不同。[图 6](#fig-retention-value)说明了单位字节成本为何同样重要。这为下层采用成本感知的信用提供动机，而下文 Peer 策略则有意使用更简单的紧迫性规则。

<a id="fig-retention-value"></a>

![图 6](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/retention-value.png)

**图 6：** 仅凭 slack 无法对保留价值排序。在这个独立故障示例中，A 使用两个容量单位，将恢复时间从 4 s 降到 2 s；B 使用一个容量单位，将恢复时间从 18 s 降到 8 s。Slack 为 0 的 A 节省 1 s/unit，slack 为 6 的 B 则节省 10 s/unit。正常使用价值为零。这个构造示例为成本感知的下层保留提供动机，并揭示仅按紧迫性进行 Peer 准入的局限；它不是策略加速结果。

#### 4.4.2　带惰性更新的可续租信用

前述优先级针对单个请求。跨请求来看，共享前缀可以服务多个 Agent，同一个 Agent 也可能在工具等待后再次使用它。Master 为每个有需求的 Agent 分配对象信用中的独立份额。不同 Agent 增加一个份额；同一 Agent 的新使用刷新其原有份额，而不是再累积一份相同价值。Agent 身份包含所属工作流实例，物理容量只计费一次。

对于下层对象 $x$，当前授予信用由正常复用项与恢复优先级共同组成：

$$
g_{a,x,j}=v^{\mathrm{reuse}}_{a,x,j}
                +\lambda_f c_{a,x,j}P_{a,x}. \tag{4}
$$

其中，$j$ 表示 DRAM 或存储；$\lambda_f$ 对统一决策时间范围内的故障风险加权。估计成本 $c$ 衡量对象离开 $j$ 后增加的服务工作：DRAM 降级后需要访问存储，或最后一份存储副本被移除后需要重建。复用项将因果的下一次使用估计与相应避免的服务工作相乘，且独立于 slack。这样可以为 slack 较大的多轮 Agent 保留有用状态。当恢复需要一个存在依赖的对象组时，其估计成本按字节分摊，而不是向每个块重复赋予整个组的成本。Agent 份额之和表达竞争需求，不等于精确的联合 WCT：工作流汇合点上的同时延迟不能相加。

一次性授予的信用会过时；每次 checkpoint 都重新授予信用，又可能无限期保留未使用的状态。受 Landlord 与 GreedyDual-Size 启发[[2]](#ref-2)、[[30]](#ref-30)，Master 将当前授予信用 $g$ 与已付租金 $d$ 分开：

$$
C_{x,j}=\sum_a[g_{a,x,j}-d_{a,x,j}]^+,
 \qquad H_{x,j}=\rho_j+C_{x,j}/b_x. \tag{5}
$$

存储池压力时钟 $\rho_j$ 按字节数 $b_x$ 计费，而非按经过的时间计费。时钟增加 $\delta$ 时，扣除 $\min(C_{x,j},b_x\delta)$，并在仍为正的 Agent 份额之间按比例分摊。所有已提交的驻留对象都会老化，包括有 lease 的对象；是否允许淘汰另行判断。实际复用或恢复使用只续租发起使用的 Agent，并以对象与 request/use ID 为单位去重。注意力观察更新需求；checkpoint 增长、分数更新和迁移保留已付租金。过期的 Agent 需求被移除。[图 9](#fig-renewable-credit)展示了这些不同事件。最近使用情况通过续租体现，需求通过选择概率与复用历史体现，工作流紧迫性通过 $u_r$ 体现；这些都是明确的信号，并不意味着该机制涵盖所有 LRU／LFU 变体。

**避免逐 token 更新信用。**

引擎为每层推进一个 Query 计数器，并且只记录被选中的块 ID。块的创建序号和窗口边界决定其访问机会数，无需为每个块递增分母。数量有界的 Query bucket 使旧的选择计数过期；dense attention 不需要这些计数器。统计信息在 checkpoint 事件中批量提交。Slack 变化只更新请求标量与版本，不触碰其各个块。

Master 仅在实际使用、候选检查或轮转扫描时具体更新一个块。它先结算该块自上次时钟以来产生的租金，再读取当前请求／需求版本，并在保留已付金额的同时刷新授予信用。两次具体更新之间，授予信用保持固定；因此，共享压力时钟可以避免每次计费都扫描全部驻留对象。如果尚未查看的 key 可能降低，只刷新过时堆顶是不够的。每轮在固定工作预算内刷新 $q$ 个低 key 候选和 $q$ 个轮转候选，然后选择受害对象。这是近似选择，[第 5.4 节](#sec-eval-rental)将其与立即全面刷新比较；它不是精确的全局最小值。工作量随观测到的选择、检查的候选及其 Agent 份额增长，而非每生成一个 token 就更新整个缓存。

#### 4.4.3　贪心 Peer 保护

Peer 加速恢复，但不参与租金机制。由于访问集中于部分块（[图 3(a)](#fig-kv-value)），固定的热集即可服务选定层的大部分读取。对于每种受支持的模型／布局，校准阶段固定 checkpoint 间隔 $Z$、前缀层深度 $L$ 和每个选定层的块数 $K$。在线策略改变热块身份与请求成员，而不改变这三个参数。一个 Peer slot 最多预留 $LK$ 个块，并为必需状态单独分配预算。短历史使用更少的块；共享物理对象只计费一次。这是固定配额，并不意味着每个请求的实际物理占用都相同。引擎 block size 与 $Z$ 独立配置；某项测量中的 64-token 单位不具有普适性。

[图 7](#fig-sparse-recovery)展示了相应放置。每个已封闭的层／块／TP 对象只有一个受管 owner，与执行侧工作 KV 区分开来。Peer、DRAM 和存储共同覆盖已提交 checkpoint；对象迁入 Peer 后，待交接完成再释放其下层副本。未选中的块留在下层，需求未命中时从实际 owner 取回。

<a id="fig-sparse-recovery"></a>

![图 7](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/sparse-recovery.png)

**图 7：** 跨三个互斥层级的 checkpoint，Peer 配额固定为 $L=2$、$K=2$。每个格子表示一组层／块对应的 TP 对象；四个格子位于 Peer，其余位于 DRAM／存储。第 1 层需要 B0/B1/B2：B0 在本地，B1 需要 H2D，B2 需要存储读取加 H2D。虚线尾部尚未提交。热块身份可以在配额内变化；被淘汰的 Peer 对象必须先向下迁移，其空间才能再次使用。

只有经过截断、扣除 guard 后 slack 为 $s_r=0$ 的请求，才能进入 Peer 候选队列，包括运行期间 slack 降到零的请求。已准入请求按 $\widehat p$ 为每层选择 $K$ 个块，依次以最近使用时间和块 ID 打破平局。请求完成或交接给工具后，该请求的 slot 可被淘汰。准入或缩减配额时，Master 先回收已结束请求，再按 slack 从大到小回收活跃请求。普通准入在 slack 相等时保留已有请求；新的同值请求等待 Peer，同时保留下层保护。必要的缩减使用最久未发生请求使用的顺序打破活跃请求间的平局。因此，活跃请求具有策略上的保留偏好，而非绝对淘汰锁；物理 read/copy lease 始终必须遵守。只有不再有保留的 slot 需要共享对象时，才能释放该对象。不同接管 DP 不能同时将其唯一 owner 计为本地。

**为何固定保留前若干层？**

令 $M$ 为已提交历史，$N$ 为其后已确认但尚未提交的尾部。恢复需要重放 $N$，这部分计算可以与后续层读取重叠。下层状态已经避免了重建，Peer 额外消除的仅是暴露出的传输等待。[图 8](#fig-design-pipeline)在同一时间轴上包含存储读取、H2D 和重放。在该示例中，需求未命中使稀疏加载比完整层流水线更慢；相对于相同稀疏需求，Peer 减少约 15 ms。该对比展示部分驻留，而不说明某个 $L$ 普遍最优。校准在已声明的历史／尾部与负载配置上扫描固定配额，在 HBM 预算下选定一个配置，然后在其他工作流上评估之前冻结它。不同请求可能适合不同深度；计划通过自适应深度和小规模 oracle 对比量化这种简化的代价。

<a id="fig-design-pipeline"></a>

![图 8](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/recovery-pipeline.png)

**图 8：** 存储／H2D／重放的分析调度：32 层、32K 历史、64-token 尾部，以及 1,024 MiB 独特 KV。(a)–(c) 将历史均分到 DRAM／存储；(d) 将前 $L=7$ 层中每层 $K=336$ 个 64-token 块移到 Peer：Peer 占 147 MiB，下层各占 438.5 MiB。已有 MiniCPM4-8B 重放校准值为 2.870 ms/layer；存储／H2D 速率 3.125/6.25 GB/s 为假设值。两个稀疏案例均预加载 336 块，每层未命中 64 块；未命中需求在前一层完成后才揭示。这些需求是构造的。冷 KV 的读取位于图示终点之后。放置已经完成；各 I/O 阶段相互独立，工作区充足，无前台流量。这些是机制调度，不是集成测量，也不是最优配额搜索。

#### 4.4.4　在线三层管理

Prefill 提供已封闭块；Decode 每固定 $Z$ 个 token 复核一次，完成／工具交接时提供最终快照，也包括短轮次。实际使用、Slack 变化、容量更新和传输结果也会调用[算法 2](#alg-placement)。新块获得创建该块的 Agent 的初始信用；未变化的前缀对象不获得新信用。

**准入与容量压力。**

下层存在空闲空间时接纳新状态，包括零信用状态。有容量压力时，Master 刷新候选受害对象，并试算按字节比例收费的租金，直到耗尽一个已检查且可安全移除的对象组的信用。新对象支付相同试算租金；信用归零的新对象在该层被延后准入。DRAM 拒绝后，可以将状态直接送入存储。已提交的零信用对象在需要空间前仍可使用；DRAM 受害对象迁往存储，存储的独立账目根据避免重建的价值来评估保留。删除最后副本前，必须为每个受影响的 manifest 发布有效的较旧 checkpoint 或输入／日志重放回退。依赖关系和物理 lease 约束所有受害对象选择。

Peer 准入／缩减遵循上述请求顺序。热集变化在同一 slot 内替换对象身份。两者都可能需要 Peer→DRAM 和 DRAM→存储的级联迁移。如果无法预留安全目的地，迁移就等待，源位置继续被占用。下层各 pool 的已付金额在往返迁移后仍保留，离开期间不收租。经过 Peer 的迁移和仅更新价值的刷新，都不会触发续租。

<a id="alg-placement"></a>

**算法 2：在线三层管理**

| 行   | 操作                                                       |
| --- | -------------------------------------------------------- |
| 1   | `ReconcileTransfers`$(e)$; `PublishSignals`$(e)$         |
| 2   | `RecordNewBlocksAndUses`$(e)$                            |
| 3   | $Q\gets\operatorname{LowKeysAndRotation}(q)$             |
| 4   | **for** $x\in Q$ **while** `WorkLeft`() **do**           |
| 5   | &emsp;`SettleRent`$(x)$; `RefreshGrantAndKey`$(x)$       |
| 6   | $P_D\gets\operatorname{LowerTierAdmission}(e,Q)$         |
| 7   | $P_H\gets\operatorname{PeerSlots}(s,B,L,K,e)$            |
| 8   | $P\gets\operatorname{PrepareCascade}(P_D,P_H)$           |
| 9   | **if** $P=\varnothing$ **then** `Defer`$(e)$; **return** |
| 10  | **if not** `ReserveIfCurrent`$(P)$ **then**              |
| 11  | &emsp;`Requeue`$(e)$; **return**                         |
| 12  | `Submit`$(P)$ *完成／失败触发一个新事件*                             |

Connector 依次复制、确认目的端、重定向所有权，并在读者排空后释放源。交接期间，两份副本都计入容量。被拒绝的预演既不改变所有权，也不改变已提交租金；成功的容量交接提交其试算租金和剩余信用。只有完整依赖覆盖才能推进 $M$；复制滞后可能导致 $N>Z$。受保护的源故障必须使已公布 owner 仍然可达；额外 owner 丢失需要显式回退。容量检查验证执行可行性，而非全局 WCT 最优性。动态价值、依赖对象和有预算的刷新，也使该机制不能继承 Landlord 的竞争保证。[第 5.4 节](#sec-eval-rental)规定同估值直接重评以及续租、老化和共享 Agent 的独立对照，并报告历史租金诊断。

<a id="fig-renewable-credit"></a>

![图 9](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/renewable-credit.png)

**图 9：** 一个共享、单位大小 DRAM 对象的信用。授予信用 3 和 2，在收取租金 2 后变为剩余份额 1.8 和 1.2。将 A 的授予信用更新为 4 时保留其已付金额 1.2，剩余 2.8；A 发生一次实际新使用时，其份额续租为 4。B 保持 1.2。惰性具体更新先结算此前租金，再更新授予信用。这是构造的记账示例；Peer 没有租金时钟。

### 4.5　Adapter：带保护条件的 AIMD Peer 容量调节

Master 在配额内选择内容；Adapter 随前台推理需求变化调整配额。它在压力下进行乘法减小，在稳定窗口后进行加法增加[[4]](#ref-4)。Peer 总授权容量受物理上限约束：

$$
C=\max\{0,\min(B_{\mathrm{cap}},
 B_{\mathrm{pool}}-B_{\mathrm{serve}}-B_{\mathrm{reserve}})\}. \tag{6}
$$

Pool 不包含权重／固定分配；服务高水位不包含 Peer，预留空间覆盖增长／工作区。已有 Peer 字节不会被重复扣除。$B_{\rm cap}$ 可以配置为 pool 容量的一定比例。

当前配额 $B$ 和稳定窗口计数 $z$ 均从零开始。压力信号（分配停顿、预留空间不足或内存相关准入等待）使 $B$ 乘以 $0<\gamma<1$。连续 $m$ 个稳定窗口的等待低于较低阈值后，如果存在被延后的零 slack Peer 需求，则允许按字节步长 $\Delta$ 增加配额；该需求在配额过滤之前计数。处于中间状态的窗口重置 $z$；遥测缺失时禁止增长。每次更新均受容量上限截断；紧急情况下可以在窗口内减小，但增长必须等待完整稳定窗口。参数和窗口长度均可配置。

**算法 3：按窗口调整 Peer 配额**

| 行   | 操作                                                            |
| --- | ------------------------------------------------------------- |
| 1   | $C\gets\operatorname{SafeCeiling}();\quad B'\gets B$          |
| 2   | **if** `Pressure`() **then** $(B',z)\gets(\gamma B,0)$        |
| 3   | **else if** `Stable`() **then**                               |
| 4   | &emsp;$z\gets z+1$                                            |
| 5   | &emsp;**if** $z\ge m$ **then**                                |
| 6   | &emsp;&emsp;**if** `PeerDemand`() **then** $B'\gets B+\Delta$ |
| 7   | &emsp;&emsp;$z\gets0$                                         |
| 8   | **else** $z\gets0$                                            |
| 9   | $B\gets\operatorname{RoundDownPage}(\min(C,B'))$              |
| 10  | `PublishBudget`$(B)$; `EmitCapacityEvent`()                   |

Adapter 设置总预算；Master 准入固定 $L/K$ 的请求 slot，并在固定 $Z$ 间隔及其他放置事件中刷新对象身份。如果占用加预留超过缩减后的配额，Master 暂停 Peer 准入并选择对象降级。其 DRAM 目的端可能先需要向存储降级。只有这些传输和正在进行的读取结束后，服务才可复用该内存；新配额是授权目标，而不是瞬时空闲空间的声明。

## 5　评估

<a id="sec-evaluation"></a>

核心问题是：面向工作流的保护能否减少故障后的**工作流完成时间**（WCT），且不在正常服务期间付出更大的代价。我们围绕端到端结果、恢复路径成本、机制贡献、预测质量和适用边界组织评估。实验设计借鉴三个方面：工作流感知服务中的应用级结果[[14]](#ref-14)、[[17]](#ref-17)；故障恢复中分别考察被中断与未中断请求[[3]](#ref-3)；以及 KV-cache 系统中先报告端到端测量，再通过状态恢复、调度和资源压力消融解释结果的组织方式[[8]](#ref-8)、[[21]](#ref-21)。

**已经测量的内容。**

当前实验材料包含 KV 路径实机微基准、基于实际 Agent trace 的留出预测结果、原生稀疏访问捕获，以及历史分析诊断。它尚未包含针对当前固定 $L/K/Z$、互斥三层控制器的故障注入 campaign。我们按实际适用范围报告已有证据，并在下文说明尚缺的实验。特别地，早期禁用 Peer 的分配模型和独立租金模型是诊断材料，而非当前策略的实现。图中区分实机测量、trace 观察和模型；没有以合成曲线代替尚未执行的系统对比。

### 5.1　实验方法与比较约定

<a id="sec-eval-method"></a>

**部署与工作负载。**

主要系统实验至少需要两个位于不同故障域、彼此兼容的服务副本，独立可达的后备存储，以及持久化输入／输出日志。GPU 进程、副本、主机和后备存储故障属于不同实验配置。分别记录 DP 与 TP、幸存计算容量、物理互连、存储后端、模型版本、数值精度、attention kernel、块大小和控制器版本。本地 NVMe、远程 NVMe 与共享文件系统是不同后端；本地磁盘不能保护主机故障。在可执行原型和硬件分配冻结前，这些部署字段保持未落实状态。

使用可执行的代码任务、多跳问答，以及受控的顺序／fork–join 工作流。每个原始 DAG 仅执行一次，保留完整 prompt 历史、工作流 ID 和绝对到达顺序。冻结工具响应以支持可复现的主要对比；实时工具属于独立的有效性实验。Dense 与原生稀疏模型路径分别设立配置，并明确排除不支持的上下文长度。先校准一个固定基线的可持续健康负载，再对全部策略使用相同的开环到达。首个决定性实验子集使用三个工作负载族、两条兼容模型路径、一个负载／预算设置、四种策略、两种故障条件和十次配对 campaign：共 480 个计划 run slots，而非 480 次已完成运行。更广的负载、上下文、容量与故障位置扫描在该子集之后进行。

**基线与资源核算。**

Recompute 保留已接受 tokens 和应用状态，但不保留额外的可恢复 KV，用于衡量 checkpoint 本身的收益。Hierarchical LRU（H-LRU）和 reuse-only 保护与 AegisKV 使用相同的传输、checkpoint 触发、恢复调度器、所有权协议及总物理资源。H-LRU 检查新优先级能否优于调优后的层级策略；reuse-only 将恢复紧迫性与正常局部性区分开。Zero-slack 对照在保留正常复用价值的同时隔离工作流紧迫性。禁用 Peer 和固定 Peer 总容量的对照分别隔离 Peer 加速与 Adapter。All-DRAM 和小实例离线策略明确标记为参考，并注明各自放宽的假设。兼容的外部 DéjàVu、GhostServe、LUMEN 或 Mooncake 实验材料可提供额外系统对比[[27]](#ref-27)、[[10]](#ref-10)、[[3]](#ref-3)、[[21]](#ref-21)；独立重实现的机制按实际身份命名，不为不兼容的实验材料编造性能。

所有等资源策略都计入执行和保护所用 HBM、元数据、暂存空间、预留与待释放字节、checkpoint 写入以及迁移流量。共享对象在稳定状态下占用一份物理分配；交接期间两份副本都计费。Peer、DRAM 和存储 owner 的并集覆盖一个 checkpoint。Peer 不会免费获得一份完整的下层副本。$L$、$K$ 和 $Z$ 在校准工作流上选定，并在留出评估前冻结。逐请求自适应层深度或热集大小属于独立参考；当前 Adapter 已经可以调整 Peer 总容量，同时保持逐请求配额固定。

**结果指标与统计单位。**

对于策略 $p$ 和工作流 $w$，使用该策略自身的无故障配对运行：

$$
\begin{aligned}
D_{w,p}&=\mathrm{WCT}^{F1}_{w,p}-\mathrm{WCT}^{F0}_{w,p},\\
G_{w,p}&=D_{w,\mathrm{H\mbox{-}LRU}}-D_{w,p}.
\end{aligned} \tag{7}
$$

$F0$ 表示不注入故障，$F1$ 表示匹配的故障条件。$G$ 为正表示故障惩罚更小。除 $D$ 和 $G$ 外，还报告绝对 WCT、统一观察时限内的完成情况、SLO goodput 和健康服务成本。分别考察直接被中断的工作流、共享恢复资源的工作流，以及资源隔离的对照组。Campaign 是独立重复单位；同一 campaign 内的工作流、请求和块不是独立运行。既报告对象数量，也报告 campaign 数量，并先在每个 campaign 内聚合配对差值，再计算 campaign 层级的不确定性。

TTFT 从原始请求到达时开始计时，包括重试。对于故障时已经进入 decode 的请求，报告从故障到首个恢复输出 token 的延迟，以及 token 间延迟的尾部。端到端 TPOT 包含首个与最后一个已接受输出 token 之间的恢复停顿；仅 decoder 的 TPOT 是单独标记的诊断指标。重放或被丢弃的 tokens 不会扩大已接受输出的分母。

### 5.2　端到端工作流完成时间

<a id="sec-eval-workflow"></a>

**决定性实验。**

主要故障在固定工作流／Agent／请求达到其冻结逻辑 token 进度的 80% 时触发。终止完整源副本，并纳入全部被中断请求。分别扫描 20/50/80/95% 进度；不能用统一墙上时钟时刻代替相同进度。在归因运行中，冻结故障前的源映射和已提交覆盖。在完整系统运行中，允许路由与实际提交前沿不同，但比较原始到达 cohort，并报告实际被中断的 ID 和墙上时钟触发时刻。不能为各策略选择不同的被中断子集。路由和触发时刻的差异仍是完整系统效应的一部分；机制归因则使用上述冻结映射与覆盖的对照。

主要结果应针对每个工作负载族和负载，将 WCT 分布与同 ID 的 $G$ 值配对展示。延迟旁同时显示完成情况和超时；仅完成案例的延迟使用共同的合格 cohort。故障惩罚可以为零或负，因此不宜用 $D$ 作比值分母。有说服力的结果必须优于 H-LRU 或 reuse-only，而不仅是 Recompute，并且在计入健康服务成本后仍然成立。

**已有的分配诊断。**

[图 10](#fig-eval-placement-pairs)重新分析已有的 36 配置、四分支模型。它改变状态大小、分支 slack 和存储带宽，并在相同配置间进行比较。历史 workflow-value 分配器在 17 个案例中改善，在 19 个案例中持平。在基础案例中，LRU 和 workflow value 分别向 12 s 的剩余汇合时间增加 3.6208 和 1.6125 s。2.0083 s 的差值对应**故障惩罚**下降 55.5%，而非完整工作流 WCT 下降 55.5%。该模型没有 Peer 层、固定 slot 准入或惰性下层控制器。它支持工作流优先级的相关性以及配对指标的选择，但不能证明端到端 AegisKV 加速。

<a id="fig-eval-placement-pairs"></a>

![图 10：历史分配模型的配对故障惩罚差值](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/evaluation/eval-placement-pairs.png)

**图 10：** 历史分配模型：在 36 个等权配置中，相对于 LRU 的配对故障惩罚减少量。正值有利于 workflow-value 放置；19 个持平案例保持可见。这些是禁用 Peer 的确定性场景，不是实测工作流。

### 5.3　恢复路径与相互干扰

**已有的实机校准。**

[图 11](#fig-eval-recovery-paths)重新组织了前文 KV 重建对比中使用的已有路径计时。配置为 Qwen2.5-7B-Instruct-1M、两张 A100 PCIe 40 GB GPU、TP2、BF16，batch size 为 1。对同一固定合成 token 流，在 8K、64K、256K 和约 1.01M tokens 处进行评估。HBM／DRAM 复用对每个输入计时三次；完整 Prefill 和 DPC 共享文件系统复用各计时一次。统一终点是相同输入的 KV 已经就绪、可以继续执行，包含取回状态与必需计算。这些是路径测量，而非独立工作流 campaign。

在最长上下文处，已驻留 HBM、主机 DRAM、共享文件系统与完整重建分别耗时 1.3050、2.6632、10.1561 和 571.2127 s。较大的重建差距为保留状态提供动机；较小的 HBM–DRAM 差距是 Peer 层可能进一步减少的部分。该测量不包含 Peer 传输、后台 serving、并发恢复或故障检测。文件系统服务端缓存不受控制，因此它既不是冷 SSD 延迟，也不是带宽结论。

<a id="fig-eval-recovery-paths"></a>

![图 11：实测 KV 路径延迟](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/evaluation/eval-recovery-paths.png)

**图 11：** 对同一固定输入流测得的 KV 路径延迟。HBM 和 DRAM 显示三次计时重复的中位数与观测范围；重建和共享文件系统的数据点各只有一次观测。HBM 表示已驻留状态的复用，SharedFS 表示 DPC 共享存储。这些是校准测量，不是故障注入的系统结果。

**所需的因果分解。**

记录故障检测、fencing／重新路由、准入、目录查找、存储读取、网络传输、H2D、必需重放、请求恢复和 DAG 完成。追踪依赖边并识别实际关键路径；直接相加彼此重叠的组件时长会高估恢复时间。固定需求与覆盖，对比 Peer 关闭／开启和重叠关闭／开启。分别测量总字节、未使用的预取、GPU 工作量、临时副本和恢复池占用时间。一个请求变快不一定减少汇合延迟或总恢复工作量。

在相同前台到达下，注入影响 1/2/4/8 个工作流的突发故障，并使用 1/2/4 个幸存目标。绘制队列占用，以及被中断／未中断工作流的 WCT、TTFT 和 TPOT 随时间的变化，同时提供资源隔离对照。在主张连带延迟前，必须指出共享的恢复队列。这借鉴 LUMEN 的 cohort 划分[[3]](#ref-3)，同时保留 WCT 作为 AegisKV 的主要结果。

### 5.4　机制贡献与信用成本

<a id="sec-eval-rental"></a>

使用匹配干预，而不是同时移除多个机制。主要消融包括：zero-slack 回退与预测 slack；仅复用、仅恢复和联合优先级；逐 Agent 份额与仅创建者份额，且物理去重保持不变；因果可见机会归一化与原始选择次数；固定 slot 的 Slack、FCFS、recency 和恢复成本准入；以及固定 Peer 容量与带保护条件的 AIMD。对于下层，将当前惰性信用策略与同估值直接重评、普通成本／大小 GDS 或 Landlord、不按实际使用续租，以及无压力老化进行比较。保持相同所有权、lease、到达／故障机会、价值估计和物理预算。

Lazy 与 eager 刷新既需要相同 CPU 预算下的比较，也需要不限工作预算的 eager 参考。报告决策时间、检查的候选数、扫描年龄、过时排序、不同受害对象、迁移字节和配对 WCT。标量检查次数更少，本身不能确立控制器更快。五组因子实验揭示交互：Slack × 共享 Agent 份额、归一化需求 × 状态恢复流水线、可续租信用 × 惰性刷新、负载感知路由 × 共享链路竞争，以及 Peer 驻留 × 流水线。每组都在其他特征固定时使用完整四格。Campaign 层级的差中之差区分组合效应与两项分别观测到的改善。

**已有的负面结果。**

历史加性租金诊断包含 512 次决策；直接重评和原始 trial-rent 变体都进行了 396 次价值检查。二者的 miss 加 movement 成本分别为 462.96 和 506.39 个模型单位：trial rent 更差 9.38%。[图 12](#fig-eval-rental-diagnostic)也保留了后续修正变体。诊断修正不能验证当前逐 Agent 惰性信用控制器。这个反例说明同估值直接基线是必要的，而不是说明加入租金能够改善 WCT 或减少 CPU 成本。

<a id="fig-eval-rental-diagnostic"></a>

![图 12：历史租金诊断](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/evaluation/eval-rental-diagnostic.png)

**图 12：** 历史租金诊断。保留直接重评、原始 trial-rent 变体及其修正变体的 miss 与 movement 成本，越低越好。原始负面结果保留；模型成本和价值检查次数不是实机 WCT 或控制器 CPU 测量。

### 5.5　预测质量与稀疏需求

<a id="sec-eval-prediction"></a>

**剩余时间。**

[图 13](#fig-eval-tracker-errors)使用来自 170 个工作流的 1,443 个符合条件的第二次请求 Agent 快照，每个 Agent 一个快照，采用按工作流隔离的五折划分。目标是整个 Agent 的剩余墙上时间，而非当前 Tracker 所需的剩余 segment 时长。训练折中位数、基础 GBDT 和带历史 GBDT 的平均绝对误差分别为 438.6、406.7 和 407.1 s。然而，基础 GBDT 的 p95 绝对误差仍比中位数基线更差（1113.8 对 1036.1 s）。图中保留完整误差尾部，包括超过 85,000 s 的误差。平均误差的小幅下降不能确立可信的 slack，这些标签也不能验证 segment 级预测。

当前 Tracker 需要新的因果 segment 标签、按工作流隔离的训练／校准／测试集，以及在更晚工作流上的验证。测量剩余时间误差、真正关键分支上的假阳性 slack、关键路径排序、回退频率和预测／更新成本。评估 zero-slack 和 oracle-duration 参考。预测诊断按完整工作流进行 bootstrap；不能从汇总 WAPE 或特征相关性推导误差 CDF。对于陈旧 profile、模型变化、缺失 DAG 边和工具延迟，依据实际结果重新计算决策进行研究，而不是添加装饰性的误差条。

<a id="fig-eval-tracker-errors"></a>

![图 13：留出集中的完整 Agent 剩余时间预测误差](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/evaluation/eval-tracker-errors.png)

**图 13：** 整个 Agent 剩余时间预测的留出绝对误差。ECDF 包含来自 170 个工作流的全部 1,443 个 Agent 快照；不同折按工作流隔离。它是描述性结果，没有编造置信带。整个 Agent 的预测准确率不能验证剩余 segment 的 slack。

**原生访问与预测窗口敏感性。**

[图 14](#fig-eval-sparse-demand)在同一模型内的相同字节预算下，对比历史频率、recency 和离线需求 oracle。捕获使用 32,768 个历史 tokens、此前的 512-Query 排序窗口，以及之后用于评估的 64 个 Queries。每个对象是某一层中包含全部 KV heads 的 64-token 块。预算为每层 512 个历史块中的 205 个，约为 40%。Coverage 是未来需要的不同历史字节中，已经被选中的比例；各文档等权，每个模型使用三个文档。它既不是 attention mass，也不是 GPU 命中率测量。

历史频率对 NOSA-3B、MiniCPM4-8B 和实验性 SeerAttention／Qwen3 路径的 coverage 分别为 77.82%、53.57% 和 43.02%；同预算 oracle 的 coverage 分别为 93.75%、58.98% 和 43.28%。Seer 较小的 oracle 差距限制了该预算下更好排序器的价值。将未来窗口扩展到 512 个 Queries 后，频率 coverage 降至 58.90%、44.08% 和 40.47%；完整窗口扫描保留在实验材料中。这些历史计数包含原生 head／group 选择事件。它们是当前去重、可见机会归一化概率估计的基线，而非对该估计的测量。

当前策略所需的实验使用严格位于过去的窗口，对比原始次数、归一化次数、recency 和随机选择。同预算离线 oracle 可以使用真实未来需求，但仅作为已知未来的参考。扫描历史长度、未来窗口、预算和未见文档／工作流，并计入 selector 状态和全部物理对象。在校准工作流上冻结 $L/K/Z$，再在留出工作流上测试。最后，在 miss 和前台竞争下测量暴露等待与 WCT：高 coverage 本身不能证明 Peer 的净收益。

<a id="fig-eval-sparse-demand"></a>

![图 14：相同预算下的原生稀疏需求诊断](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/evaluation/eval-sparse-demand.png)

**图 14：** 每层相同 205／512 块预算下的原生稀疏访问诊断。历史频率和 recency 为之后的 64 个 Queries 选择状态；离线 oracle 能看到这些 Queries 的实际需求。数据点和汇总保留三个文档之间的变化；这是观测到的需求 coverage，不是置信区间或故障恢复加速比。

### 5.6　健康服务与持续故障

**正常服务成本。**

在 $F0$ 下运行完整原始工作负载，包括首次调用、工具等待和后续请求。测量 WCT、TTFT、TPOT、SLO goodput、GPU-seconds、控制器 CPU／内存、checkpoint 字节，以及逐层级请求命中与 token 命中。将绝对到达 trace 固定在参考容量的 30/60/85%；不能按各策略自身吞吐分别归一化。记录 Peer 增长引起的执行 HBM 容量损失和迁移竞争。Trace 中的前缀重叠不是运行时缓存命中。在声明的故障频率下，将有条件的恢复收益与摊销收益分开报告。模型中的排队延迟不是实测 TTFT，高故障频率压力测试也不能确立生产环境中的净收益。

**为何平均值不足以说明问题。**

历史 LANL 时序模型保留 22 个系统中清洗后的 21,738 个节点不可用区间。每次开始事件在各系统独立的 FIFO spare pool 中触发一个假设的四分支恢复。[图 15](#fig-eval-trace-tails)显示，workflow-value 分配的事件加权平均值更低（9.4673 对 10.4533 s），但 p95 更差（40.0292 对 37.0375 s），p99 也更差（232.1125 对 204.1208 s）。即使当前汇合更早结束，较长的恢复池占用仍可能损害后续恢复。这些是记录时序驱动的模型结果，而非实际观测的 LANL Agent 工作流或实测 AegisKV 故障。

<a id="fig-eval-trace-tails"></a>

![图 15：历史 trace 驱动恢复模型的均值与尾部](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/evaluation/eval-trace-tails.png)

**图 15：** 历史 trace 驱动恢复模型：在相同记录事件时序下的平均和尾部故障惩罚。Workflow-value 放置减少平均值，同时恶化 p95 与 p99。结果将假设的工作负载和 spare-pool 模型与记录的不可用开始事件结合起来；它不是实测集群可用性。

对于连续重放，保留故障簇、不可用持续时间、幸存容量和不重叠日历块；同时报告事件加权与系统／窗口加权汇总。可用的 LANL 再分发数据有 23,739 行，而原始来源记录为 23,741 行，来源差异尚未解决[[15]](#ref-15)、[[23]](#ref-23)。Reflex／ByteDance alerts 在各 job 内独立平移，且缺乏可靠 down／up 对，因此不能定义全局故障日历[[5]](#ref-5)、[[1]](#ref-1)。InfiniteHBD[[26]](#ref-26)等现代节点故障 trace 同样需要保留原始节点级语义和训练集群适用范围。任何 serving 可用性结论之前，都必须明确 trace 来源与资源映射。

### 5.7　适用范围与控制器扩展性

容量实验考察保护何时失去优势。在相同物理预算下，分别扫描 Peer、DRAM 和存储，包含 Peer 关闭、目的端满载和最后副本压力。实际覆盖与提交滞后区分容量不足和复制路径过载：尚未提交的尾部 $N$ 可能超过 checkpoint 间隔 $Z$。因此，需要结合写积压、迁移流量、未使用预取和回退频率解释 WCT。分别考察存储、NIC 和 H2D 瓶颈，以揭示收益是否依赖某个有利的传输速率比例。

扩展性实验将副本数、TP 度和故障域与控制器状态规模区分开。增大 DAG、共享 owner 的 fan-out、活跃对象数和候选预算，可揭示决策质量与更新成本的权衡。使用实际决策时间尾部、CPU 使用、元数据和前台停顿，对比有界惰性刷新、等预算 eager 和不限预算 eager。保留饱和与不支持的配置；将操作次数乘以假设的节点成本不能代替控制器计时。

鲁棒性实验检验：当 DAG 内的时长误差相关、profile 过时，或工具与到达突然变化时，回退和容量控制是否仍有价值。阶跃、斜坡和突发负载暴露 Adapter 的超调与稳定时间。关键容量结果是真正释放的字节：降低配额目标不会释放内存，直到 Peer→DRAM→存储级联与读者排空完成。

### 5.8　恢复正确性与可复现性

<a id="sec-eval-plan"></a>

正确性是解释任何延迟结果的先决条件。状态转换测试在过时 epoch、重复事件和不完整恢复状态下，检查互斥覆盖、提交后再重定向，以及读者排空后再释放。唯一 owner 丢失必须触发已声明的较旧 checkpoint／重放回退。压力与跨层往返案例检查物理占用、保留的已付租金和取消；Peer 案例检查规定的受害顺序、平局规则和物理 leases。实验材料枚举了注入点和带 seed 的交错执行。

在复制、提交、所有权切换和确认前后注入故障，以测试已接受 token 的持久性和完整兼容的状态恢复。下一个输出的等价性使用声明的数值容差，而已确认输出绝不能重复。应用工具幂等性是独立要求。结果同时提供转换覆盖和失败的随机调度；早期复制式 Peer 示例不能确立互斥所有权下的这些不变量。

收集主要结果前，冻结源码／模型／后端版本、工作负载和故障 ID、物理预算及校准选择。随机化策略顺序，从十次配对 campaign 开始；根据 pilot 方差和精度增加重复，而不是根据期望的效应正负。按 campaign 聚合并公开 bootstrap 方法、seed 和区间。确定性模型场景没有实验置信区间；微基准范围描述同一输入的重复计时，而非独立工作流的不确定性。将超时保留在完成情况的分母中，不编造完成时刻。

实验材料包含完整实验矩阵、逐图来源哈希、长格式绘图表、原生尺寸矢量导出和生成命令。所有尚未执行的系统配置仍明确标记为计划。执行顺序是正确性与后端校准、配对单次故障结果、健康开销与决定性消融，再进行连续 trace 重放和规模／压力测试。美观图像与完整协议不能弥补当前端到端实现证据的缺口。

## 6　相关工作

**容错 LLM 服务。**

DéjàVu 对 KV 进行流式传输与复制[[27]](#ref-27)；GhostServe 通过主机内存中的纠删码校验保护 KV[[10]](#ref-10)。RaidServe 使用循环放置、混合注意力与恢复路由处理 TP 韧性和负载不均衡[[29]](#ref-29)。LUMEN 在负载降低的条件下协调 checkpoint、请求重新分配与容量恢复[[3]](#ref-3)。放置对比必须使用同样强的恢复调度器。

**分层上下文缓存。**

Mooncake 将 KV 池化并围绕局部性进行调度[[21]](#ref-21)；其 SSD offload 在内存压力下将状态溢写到 SSD[[16]](#ref-16)。CachedAttention 使用分层缓存、逐层预加载与异步保存[[7]](#ref-7)。Strata 处理碎片化 I/O、延迟命中和缓存感知调度[[28]](#ref-28)。HCache 在平衡 I/O 与计算的同时恢复中间激活[[8]](#ref-8)。我们提出的区别在于共同故障下的工作流价值，以及安全降级与显式最后副本回退。

**工作流感知的服务与预测。**

Parrot 优化应用级执行[[14]](#ref-14)；KVFlow 使用未来调用距离进行前缀淘汰[[20]](#ref-20)。Pythia 与 Cortex 利用工作流语义[[19]](#ref-19)、[[31]](#ref-31)。TOPAS 使用剩余路径、复用和移动成本调度状态保留与执行[[17]](#ref-17)；因此，仅为缓存加入关键路径分数不足以构成新颖性。本文拟议的区别是在同一 worker 故障后，处理陈旧 checkpoint 和有限层级转换下的恢复。Heddle 预测执行轨迹[[32]](#ref-32)，但这不能确立 AegisKV 对剩余墙上时间的预测准确率。

**放置机制。**

关键路径分析[[12]](#ref-12)与基于成本／大小的缓存[[30]](#ref-30)提供了基础组成部分。AegisKV 的价值依赖 DAG、共享队列和对象位置，因此 Landlord 的竞争界不能直接迁移。计划中的小实例可行 oracle 将量化近似损失。AegisKV 结合带惰性刷新的下层可续租信用、因子化请求／块优先级，以及固定配额 Peer 准入。在匹配资源与控制工作预算下，必须通过相对于直接重估的独立消融，确立租金、实际使用续租和价值刷新，以及稀疏排序与重叠各自的收益。

## 7　结论

AegisKV 结合正常复用、工作流紧迫性与块需求，管理有限的 Peer HBM、DRAM 和共享存储。互斥所有权使完整 checkpoint 分布于这些层级；固定配额的热集加速恢复。在线控制器结合惰性下层信用与贪心 Peer 准入，区分迁移与最后副本删除，并在每次转换中保持已提交覆盖。分析场景识别了潜在收益与局限。历史 trace 驱动恢复模型表明，平均改善可以与尾部退化同时存在；独立租金诊断揭示了需要重新验证的成本。这些先前的模型结果并未验证互斥三层控制器。详细协议与单栏图支持后续实机正确性和性能实验，而这些实验仍是确立系统级收益所必需的。

**AI 辅助。**

生成式 AI 辅助了文稿撰写、实验规划和实验材料代码编写；作者仍对验证负责。

## 参考文献

<a id="ref-1"></a>

**[1]** ByteDance Research. 2026. LLM Training Alert Trace. Revision 89f843a78b1a278e430215cf23800c9fac6e43c0; CC BY 4.0. [来源](https://huggingface.co/datasets/bytedance-research/llm-training-alert-trace)

<a id="ref-2"></a>

**[2]** Pei Cao and Sandy Irani. 1997. Cost-Aware WWW Proxy Caching Algorithms. In *USENIX Symposium on Internet Technologies and Systems*. USENIX Association. [来源](https://www.usenix.org/conference/usits-97/cost-aware-www-proxy-caching-algorithms)

<a id="ref-3"></a>

**[3]** Zhang Cao, Shujie Han, Juncheng Zhang, Yuanming Ren, Yongkun Li, and Patrick P. C. Lee. 2026. LUMEN: Coordinated Failure Recovery for Distributed LLM Serving. arXiv:2606.17787 [来源](https://arxiv.org/abs/2606.17787)

<a id="ref-4"></a>

**[4]** D.-M. Chiu and Raj Jain. 1989. Analysis of the Increase and Decrease Algorithms for Congestion Avoidance in Computer Networks. *Computer Networks and ISDN Systems* 17, 1 (June 1989), 1–14. [来源](https://pbg.cs.illinois.edu/courses/cs598fa09/readings/cj89.pdf)

<a id="ref-5"></a>

**[5]** Hua Ding, Yun Zhang, Bo Zhang, Wenxiao Wang, Libo Chen, Huan Yu, Zhe Nan, Zuquan Song, Weiqiang Lou, Gaohong Liu, Xi Yang, Yuhan Li, Qinlong Wang, Shuguang Wang, Wencong Xiao, and Shenghong Li. 2026. Reflex: Event-Driven Automated Fault Localization for Large-Scale LLM Training. In *Companion Proceedings of the ACM International Conference on the Foundations of Software Engineering*. [doi:10.1145/3803437.3805245](https://doi.org/10.1145/3803437.3805245)

<a id="ref-6"></a>

**[6]** fasa-org. 2026. MiniCPM-4-8B-NSA Model Checkpoint. Hugging Face. Revision 126d6d657ce3b18d99f835ec0ef326e4899fa370. [来源](https://huggingface.co/fasa-org/MiniCPM-4-8B-NSA)

<a id="ref-7"></a>

**[7]** Bin Gao, Zhuomin He, Puru Sharma, Qingxuan Kang, Djordje Jevdjic, Junbo Deng, Xingkun Yang, Zhou Yu, and Pengfei Zuo. 2024b. Cost-Efficient Large Language Model Serving for Multi-turn Conversations with CachedAttention. In *2024 USENIX Annual Technical Conference (USENIX ATC 24)*. USENIX Association, 111–126. [来源](https://www.usenix.org/conference/atc24/presentation/gao-bin-cost)

<a id="ref-8"></a>

**[8]** Shiwei Gao, Youmin Chen, and Jiwu Shu. 2024a. Fast State Restoration in LLM Serving with HCache. Author preprint; EuroSys 2025. arXiv:2410.05004 [来源](https://arxiv.org/abs/2410.05004)

<a id="ref-9"></a>

**[9]** Yuxiang Huang, Pengjie Wang, Jicheng Han, Weilin Zhao, Zhou Su, Ao Sun, Hongya Lyu, Hengyu Zhao, Yudong Wang, Chaojun Xiao, Xu Han, and Zhiyuan Liu. 2026. NOSA: Native and Offloadable Sparse Attention. Preprint, version 2, January 29, 2026; first posted in 2025. arXiv:2510.13602 [来源](https://arxiv.org/abs/2510.13602v2)

<a id="ref-10"></a>

**[10]** Shakya Jayakody, Youpeng Zhao, Chinmay Dhanraj Nehate, and Jun Wang. 2026. GhostServe: A Lightweight Checkpointing System in the Shadow for Fault-Tolerant LLM Serving. In *Proceedings of Machine Learning and Systems*, Aakanksha Chowdhery and Zhihao Jia (Eds.), Vol. 8. MLSys, Bellevue, WA, USA, 15 pages. [来源](https://proceedings.mlsys.org/paper_files/paper/2026/hash/d99e8e80a6c41e148db686918dd7eab3-Abstract-Conference.html)

<a id="ref-11"></a>

**[11]** Huiqiang Jiang, Yucheng Li, Chengruidong Zhang, Qianhui Wu, Xufang Luo, Surin Ahn, Zhenhua Han, Amir H. Abdi, Dongsheng Li, Chin-Yew Lin, Yuqing Yang, and Lili Qiu. 2024. MInference 1.0: Accelerating Pre-filling for Long-Context LLMs via Dynamic Sparse Attention. In *Advances in Neural Information Processing Systems*, Vol. 37. Curran Associates, Inc., 52481–52515. [doi:10.52202/079017-1663](https://doi.org/10.52202/079017-1663)

<a id="ref-12"></a>

**[12]** James E. Kelley, Jr. and Morgan R. Walker. 1959. Critical-Path Planning and Scheduling. In *Papers Presented at the December 1–3, 1959, Eastern Joint IRE-AIEE-ACM Computer Conference*. Association for Computing Machinery, New York, NY, USA, 160–173. [doi:10.1145/1460299.1460318](https://doi.org/10.1145/1460299.1460318)

<a id="ref-13"></a>

**[13]** Woosuk Kwon, Zhuohan Li, Siyuan Zhuang, Ying Sheng, Lianmin Zheng, Cody Hao Yu, Joseph E. Gonzalez, Hao Zhang, and Ion Stoica. 2023. Efficient Memory Management for Large Language Model Serving with PagedAttention. In *Proceedings of the 29th Symposium on Operating Systems Principles*, 611–626. [doi:10.1145/3600006.3613165](https://doi.org/10.1145/3600006.3613165)

<a id="ref-14"></a>

**[14]** Chaofan Lin, Zhenhua Han, Chengruidong Zhang, Yuqing Yang, Fan Yang, Chen Chen, and Lili Qiu. 2024. Parrot: Efficient Serving of LLM-based Applications with Semantic Variable. In *18th USENIX Symposium on Operating Systems Design and Implementation*. USENIX Association, Santa Clara, CA, USA, 929–945. 978-1-939133-40-3 [来源](https://www.usenix.org/conference/osdi24/presentation/lin-chaofan)

<a id="ref-15"></a>

**[15]** Los Alamos National Laboratory. 2005. USRC Data Sources: Failure Data. Historical 1996–2005 node interruption records; accessed 2026-09-21. [来源](https://usrc.lanl.gov/data/failure-data.php)

<a id="ref-16"></a>

**[16]** Mooncake Project. 2026. SSD Offload: Shared Memory to Filesystem-Backed Storage. Project documentation, accessed September 20, 2026. [来源](https://kvcache-ai.github.io/Mooncake/deployment/ssd/ssd-offload.html)

<a id="ref-17"></a>

**[17]** Hongqiu Ni, Han Tian, Chi Zhang, Guopeng Li, and Haisheng Tan. 2026. TOPAS: Workflow-Aware Prefix-State Scheduling for Multi-Agent LLM Serving. Preprint, version 1. arXiv:2608.25523 [来源](https://arxiv.org/abs/2608.25523v1)

<a id="ref-18"></a>

**[18]** OpenBMB. 2025b. MiniCPM4.1-8B Model Card and Release History. [来源](https://huggingface.co/openbmb/MiniCPM4.1-8B)

<a id="ref-19"></a>

**[19]** Nikos Pagonas, Yeounoh Chung, Kostis Kaffes, and Arvind Krishnamurthy. 2025. Cortex: Workflow-Aware Resource Pooling and Scheduling for Agentic Serving. Version 1. arXiv:2510.14126 [来源](https://arxiv.org/abs/2510.14126)

<a id="ref-20"></a>

**[20]** Zaifeng Pan, Ajjkumar Patel, Zhengding Hu, Yipeng Shen, Yue Guan, Wan-Lu Li, Lianhui Qin, Yida Wang, and Yufei Ding. 2025. KVFlow: Efficient Prefix Caching for Accelerating LLM-Based Multi-Agent Workflows. Version 1. arXiv:2507.07400 [来源](https://arxiv.org/abs/2507.07400)

<a id="ref-21"></a>

**[21]** Ruoyu Qin, Zheming Li, Weiran He, Jialei Cui, Feng Ren, Mingxing Zhang, Yongwei Wu, Weimin Zheng, and Xinran Xu. 2025. MOONCAKE: Trading More Storage for Less Computation—A KVCache-centric Architecture for Serving LLM Chatbot. In *23rd USENIX Conference on File and Storage Technologies (FAST 25)*. USENIX Association, Santa Clara, CA, 155–170. 978-1-939133-45-8 [来源](https://www.usenix.org/conference/fast25/presentation/qin)

<a id="ref-22"></a>

**[22]** Qwen Team. 2025. Qwen2.5-1M: Deploy Your Own Qwen with Context Length up to 1M Tokens. [来源](https://qwenlm.github.io/blog/qwen2.5-1m/)

<a id="ref-23"></a>

**[23]** Bianca Schroeder and Garth A. Gibson. 2006. A Large-Scale Study of Failures in High-Performance Computing Systems. In *International Conference on Dependable Systems and Networks (DSN)*. [来源](https://www.usenix.org/cfdr-data)

<a id="ref-24"></a>

**[24]** SemiAnalysis. 2026. CC Traces—Weka, With Subagents, v7 only (Jun 21 2026). Hugging Face dataset. [来源](https://huggingface.co/datasets/semianalysisai/cc-traces-weka-062126)

<a id="ref-25"></a>

**[25]** Mohammad Shoeybi, Mostofa Patwary, Raul Puri, Patrick LeGresley, Jared Casper, and Bryan Catanzaro. 2019. Megatron-LM: Training Multi-Billion Parameter Language Models Using Model Parallelism. arXiv:1909.08053. Version 4, revised March 2020. [来源](https://arxiv.org/abs/1909.08053)

<a id="ref-26"></a>

**[26]** Chenchen Shou, Guyue Liu, Hao Nie, Huaiyu Meng, Yu Zhou, Yimin Jiang, Wenqing Lv, Yelong Xu, Yuanwei Lu, Zhang Chen, Yanbo Yu, Yichen Shen, Yibo Zhu, and Daxin Jiang. 2025. InfiniteHBD: Building Datacenter-Scale High-Bandwidth Domain for LLM with Optical Circuit Switching Transceivers. In *Proceedings of the ACM SIGCOMM 2025 Conference*. Public fault trace: [来源](https://github.com/stepfun-ai/InfiniteHBD-Trace). [doi:10.1145/3718958.3750468](https://doi.org/10.1145/3718958.3750468)

<a id="ref-27"></a>

**[27]** Foteini Strati, Sara McAllister, Amar Phanishayee, Jakub Tarnawski, and Ana Klimovic. 2024. DéjàVu: KV-cache Streaming for Fast, Fault-tolerant Generative LLM Serving. In *Proceedings of the 41st International Conference on Machine Learning*, Vol. 235. PMLR, Vienna, Austria, 46745–46771. [来源](https://proceedings.mlr.press/v235/strati24a.html)

<a id="ref-28"></a>

**[28]** Zhiqiang Xie, Ziyi Xu, Mark Zhao, Yuwei An, Vikram Sharma Mailthody, Scott Mahlke, Michael Garland, and Christos Kozyrakis. 2026. Strata: Hierarchical Context Caching for Long Context Language Model Serving. In *20th USENIX Symposium on Operating Systems Design and Implementation (OSDI 26)*. USENIX Association, Seattle, WA, 1–16. 978-1-939133-55-7 [来源](https://www.usenix.org/conference/osdi26/presentation/xie-zhiqiang)

<a id="ref-29"></a>

**[29]** Ziyi Xu, Zhiqiang Xie, Swapnil Gandhi, and Christos Kozyrakis. 2026. RaidServe: High-performance Resilient Serving. In *Proceedings of Machine Learning and Systems*, Aakanksha Chowdhery and Zhihao Jia (Eds.), Vol. 8. MLSys, Bellevue, WA, USA, 15 pages. [来源](https://proceedings.mlsys.org/paper_files/paper/2026/hash/507b4aacefe5325908e24f042617b741-Abstract-Conference.html)

<a id="ref-30"></a>

**[30]** Neal E. Young. 2002. On-Line File Caching. *Algorithmica* 33, 3 (2002), 371–383. [doi:10.1007/s00453-001-0124-5](https://doi.org/10.1007/s00453-001-0124-5)

<a id="ref-31"></a>

**[31]** Shan Yu, Junyi Shu, Yuanjiang Ni, Kun Qian, Xue Li, Yang Wang, Jinyuan Zhang, Ziyi Xu, Shuo Yang, Lingjun Zhu, Ennan Zhai, Qingda Lu, Jiarong Xing, Youyou Lu, Xin Jin, Xuanzhe Liu, and Harry Xu. 2026. Pythia: Exploiting Workflow Predictability for Efficient Agent-Native LLM Serving. Version 2. arXiv:2604.25899 [来源](https://arxiv.org/abs/2604.25899)

<a id="ref-32"></a>

**[32]** Zili Zhang, Yinmin Zhong, Chengxu Yang, Chao Jin, Bingyang Wu, Xinming Wei, Yuliang Liu, and Xin Jin. 2026. Heddle: A Distributed Orchestration System for Agentic RL Rollout. arXiv:2603.28101 [cs.LG] [来源](https://arxiv.org/abs/2603.28101v1)

<a id="ref-33"></a>

**[33]** Lianmin Zheng, Liangsheng Yin, Zhiqiang Xie, Chuyue Sun, Jeff Huang, Cody Hao Yu, Shiyi Cao, Christos Kozyrakis, Ion Stoica, Joseph E. Gonzalez, Clark Barrett, and Ying Sheng. 2024. SGLang: Efficient Execution of Structured Language Model Programs. In *Advances in Neural Information Processing Systems*, Vol. 37. Curran Associates, Inc., Red Hook, NY, USA, 27 pages. [doi:10.52202/079017-2000](https://doi.org/10.52202/079017-2000)

<a id="sec-motivation-protocol"></a>

## 附录 A　Motivation 测量协议

<a id="fig-context-recovery"></a>

![图 16：KV 重建与复用成本](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/context_recovery.png)

**图 16：** 在两张 A100 PCIe 40 GB GPU 上实测 Qwen2.5-7B-Instruct-1M 的 KV 重建与复用成本（TP2、BF16、batch 为 1），超过 32K 后使用稀疏注意力。完整 Prefill 从空 KV 开始；复用从 $(C-1)$ 个缓存 token 开始，再计算一个 token。KV 重建时间包括所需的读取与计算，直到全部 $C$ 个 token 的 KV 就绪。

**范围与配置。**

[图 16](#fig-context-recovery)与[图 2(b)](#fig-agent-value)使用相同的固定 Qwen2.5-7B-Instruct-1M 权重、SGLang 0.5.10rc0、PyTorch 2.9.1/CUDA 12.8，在两张 A100 PCIe 40 GB GPU 上以 TP2、BF16 权重／KV 和 batch 为 1 执行。两组实验分别申请同型号 GPU，使用由模型 tokenizer 编码的同一固定重复合成文本。Trace 提供工作流位置与长度代理，不提供基准测试 prompt。我们的 adapter 使用固定 MInference vertical/slash 配置与 DCA 位置处理，在超过 32,768 tokens 后采用稀疏注意力，包括最后一个 token 的 EXTEND。SM80 稀疏 kernel 构建和模型／注意力源码均附哈希存档。GQA 的 K/V 共享；前缀执行每组最多包含两个 Query head，单 Query 则将全部 head 一起批处理。这些是插桩 worker 测量，而非未修改服务前端的吞吐测量。

**统一终点。**

对于 $C=M+1$，完整 Prefill 从空 KV 开始，以最多 8,192 tokens 的块计算 $M$ 个 token，再单独执行一个 token。复用消耗完全相同的稀疏计算所得 $M$-token 状态，包括不完整页，并执行最后那个 token。同步墙上时间在各 TP rank 间取最大值，在模型主体完成、全部 $C$ 个 token 的 KV 驻留时结束，早于输出词表投影。模型加载、备份创建和正确性检查不计入时间。不包含检测、重新路由、服务排队延迟或注入故障。

**状态恢复路径。**

HBM 从已驻留 KV 开始。DRAM 在计算前从 pinned 主机缓冲区复制全部历史层。共享存储在计算节点的 DPC 共享文件系统上打开、读取并关闭逐 rank KV 文件，然后执行相同的 H2D 复制与计算。这些阶段不重叠；没有压缩或选择性加载。1,010,000-token 案例在两个 rank 上共恢复 57,917,382,656 个逻辑历史字节；文件另外包含已记录的对齐填充。Direct I/O 与页驻留检查排除了 Linux 文件页命中，但 DPC 服务端和内部缓存不受控制。该曲线是共享存储路径测量，而非冷设备延迟或已确认 SSD 的测量。测量后删除 KV 文件。

**计时样本。**

[图 16](#fig-context-recovery)在一次资源分配中测量 8,192、65,536、262,144 和 1,010,000 tokens。HBM／DRAM 每个长度预热一次、计时三次；完整 Prefill 与共享存储各计时一次。计时前执行短前向与算子检查；64K 还执行完整的原始全 head 稀疏参考。256K/1.01M 没有额外的完整 Prefill 预热，也没有存储读取预热。因此，这些完整 Prefill／存储数据点描述单次运行，而非稳定延迟分布。[图 2(b)](#fig-agent-value)使用两次资源分配，在 $C=100{,}865$、$105{,}921$、$108{,}865$ 和 $113{,}665$ 处测量，每个长度完整预热一次并进行三次完整 Prefill 计时。首次分配完成了三个长度；最后一个长度在提前终止信号后恢复测量。其不完整计时保留在实验材料中，但整组排除。图中报告中位数与 min–max。重复是同一输入的计时样本，不是独立工作流或置信区间。原始计时与全部样本都保留在实验材料中。

**校验与工作流映射。**

在重建／复用路径之间检查完整历史哈希、最终 hidden state、所有层的新 KV 和贪心输出。重复完整 Prefill 额外检查输出一致性，CUDA 事件时间线检查串行复制。这些检查验证所比较稀疏状态执行的一致性，不验证其与 dense attention 等价或长上下文任务质量。对于[图 2(b)](#fig-agent-value)，四个历史长度是活跃请求 trace hash-block 数乘以 64。它们是大小代理，不是原模型准确 token 数或故障时观测到的 KV 前沿。该示例按四个并行分支和约 100 s 的差值选取；它不是该工作流的最大差值组。每个反事实分别在 fork 后 29.5 s，将一段实测完整 Prefill 时长作为额外分支暂停插入。全分支汇合假设、其他执行与队列保持固定。因此，只有重建成本是实测；图中的 WCT 增量是条件计算，而非 Claude Code 工作流中实际观测的故障恢复。
