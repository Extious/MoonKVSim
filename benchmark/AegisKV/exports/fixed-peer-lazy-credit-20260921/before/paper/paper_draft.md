# AegisKV：面向工作流的 Peer HBM／DRAM／共享存储 KV 管理

英文完整稿与编译入口为 [main.tex](main.tex)，当前 PDF 为 [main.pdf](main.pdf)。最新设计为 **Peer HBM＋共享 DRAM＋Shared storage 的互斥分层驻留**：每个受管 KV 对象在稳定态只有一个 owner，三层并集覆盖完整 checkpoint；Peer 保存逐请求 L 层／逐层 K 个热块，其余对象在下层。**Peer 按恢复加速收益直接重估；DRAM／storage 使用可续租信用；完整方案通过当前 WCT 检查。** Z 固定配置，Adapter 仅调整 Peer 总容量。既有 Evaluation 保留旧策略／子机制证据边界，不视为新版集成控制器实测。

按 2026-09-21 最新要求，当前阶段取消 12 页压缩，以内容完整为先。Evaluation 保留 17 个完整小节，正文精简为 8 张必要单栏图，另外 26 张补充/备用图保存在实验包中；逐项实验规格、完整消融矩阵、trace 数据来源与可替换 CSV/绘图代码全部保留。图号以当前 `main.pdf` 为准。

## 1. Introduction

多 Agent 应用的用户等待的是整个任务完成，而不是某个请求单独完成。代码修改、并行检索和综合报告包含串行依赖、并行分支与汇合点；同样长的请求延迟，发生在不同分支上，对最终结果的影响可能完全不同。正常运行下的工作流调度和 prefix caching 已经利用这类信息，但故障提出了另一个问题：一个 worker 同时中断若干请求后，有限的快速恢复资源应该保护哪些上下文？

Agent 的多轮调用不断积累推理、代码和工具输出。失去 KV 后，重建长历史可能远比设备中断本身昂贵。KV checkpoint 可以避免这部分计算，但全部历史不能无限留在 DRAM。SSD 或共享存储提供更大容量，代价是读取、网络传输和排队。普通 LRU、单请求恢复速度、甚至单独的关键路径优先级，都不能完整描述这些权衡。

AegisKV 将共享缓存与故障恢复状态统一管理：**大 Slack 不禁止正常缓存；DRAM 降级与最后副本删除分别估值；同一故障域中断的请求共同经过 DAG 计算其影响。** KV Master 按真实复用续租、按竞争消耗信用，并在当前价值与完整计划检查下选择有限容量内的保留和迁移方案，引擎接口与传输路径在版本化 manifest、空间预留和 reader lease 约束下安全执行。Router 在请求到来时绑定故障域分离的 takeover／Peer DP，故障后激活；重绑定时读取仍可达的实际 owner；唯一 owner 丢失时使用旧 checkpoint 或输入／日志 replay fallback。

论文的拟议贡献包括：结合正常复用与共同故障的工作流恢复价值；区分降级和删除的在线有限容量管理；保留检查点有效性的异步迁移协议。分层缓存、KV 复制、预取和普通工作流调度均已有研究，不能作为本工作的独立新颖性主张。实验必须证明这些新增决策在强基线之上仍有收益。

## 2. Background and Motivation

### 2.1 工作流、Prefill 与故障恢复

多 Agent 应用把多轮 LLM 请求、工具调用和子任务连接成具有串行依赖、并行分支和汇合点的工作流。Agent 可以承担固定角色，也可以为一次子任务临时创建；请求、Agent 和完整工作流的完成条件不同。

Prefill 处理输入 token，生成逐层的 key/value（KV）状态。后续请求可以复用兼容前缀的 KV，避免重新计算逐渐积累的推理、代码和工具输出。保留历史需要容量，因此分层缓存使用 GPU HBM、主机 DRAM 和更大容量的存储。

GPU/worker 故障同时损失服务容量与活动 KV。本文考虑 fail-stop 故障，假定存在兼容的存活 replica，输入/token log 与控制状态可恢复，备份介质在故障域之外。已有 checkpoint 与恢复调度解决状态保存和工作迁移；这里进一步追问：**有限的快速恢复容量应留给哪些会影响工作流完成的历史？**

### 2.2 WCT 决定保护优先级

![工作流示例](figures/preview/workflow.png)

WCT 从任务释放计时，直到所有必要结果完成。Figure 1(a) 中 A2 在 fork 后约 151.6 s 完成，A1 在约 60.4 s 完成。如果后续 Main 需要四个分支的结果，单独加速 A1 不会提前汇合，延迟 A2 则会推迟下游执行。我们把一个分支在不推迟必要输出的情况下能吸收的额外延迟称为 slack。A0/A5 是 Main 阶段示意，节点宽度不表示执行时长；A1–A4 的条长和位置保留同一真实时间比例，虚线表示假定 all-branch join 后的余量。

![工作流最大分支差异](figures/preview/workflow-gaps.png)

Figure 1(b) 基于 393 个 CC/Weka session：保留分支执行有重叠、分支均已完成、最后一个分支结束后有 Main 请求的组别；期间允许 Main 活动。这个时序 fan-in 代理保留 121 个工作流、286 个分支组。先计算各组最长与最短分支的时长差，再取每个工作流的最大差值，中位数 138 s，P90 为 1,173 s。这是**筛选后工作流最大值的分布**，说明分支时长存在较大差异；trace 没有显式结果消费边，因此它不是已证明的依赖图，也不是故障时刻的 slack 分布。Figure 1(a) 仅用于说明一个符合条件的组，不是总体代表样本，也不是该工作流的最大差值组。

### 2.3 长上下文使快速恢复状态昂贵

![实测上下文恢复成本](figures/preview/recovery-cost.png)

Figure 1(c) 使用 Qwen2.5-7B-Instruct-1M、2×A100-PCIE-40GB、TP2、BF16、batch 1 和 SGLang 0.5.10rc0。四条路径共用 MInference vertical/slash 配置与 DCA 位置处理，超过 32K 后包括最后一个 token 均使用稀疏注意力。统一取 C=M+1：Full Prefill 从空 KV 生成 M-token 历史再计算一个 token；复用路径使用相同历史 KV，并计算相同的最后一个 token。计时终点是模型主体完成、全部 C-token KV 就绪，不含输出投影。HBM 表示状态已驻留的执行参考；DRAM 和 Shared storage 的恢复与计算串行。

在 1,010,000 tokens 处，Full Prefill 为 **571.21 s**，HBM、DRAM 和 Shared storage 分别为 **1.305、2.663、10.156 s**。复用避免了大部分历史计算，但介质层级仍影响 KV 就绪时间：本次共享存储比 DRAM 多 **7.49 s**。相应历史 KV 在两个 rank 上共占 **57.92 GB**，保留许多这样的历史会消耗大量 DRAM，而降级到存储则增加等待。这支持区分“保留可恢复副本”与“把副本保留在快速层”的价值。

这些值来自一个固定合成输入和串行路径。HBM/DRAM 各计时三次，显示中位数和 min–max；Full Prefill/Shared storage 每个长度各一次。它们说明该配置中的成本差异；内部存储缓存和传算重叠会改变差异大小。测量、预热与校验细节移至附录 A，Shared storage 仍指计算节点实际使用的 DPC 共享存储，不标成未经确认的 SSD。

### 2.4 故障位置改变保护收益

![实测重建时间与计算得到的工作流影响](figures/preview/recovery-exposure.png)

**Figure 2 的 Prefill 时间现在与 Figure 1(c) 使用相同模型、硬件类型和执行配置实测。** 补测来自作业 1517915（前三个长度）与 1517917（最后一个长度）；A1–A4 的历史长度代理分别为 105,920、100,864、108,864 和 113,664 tokens，各加一个 token，逐长度完整预热一次、正式计时三次。长度来自 trace 的 hash-block 数×64，测量输入仍是固定合成文本，并非原始 Claude prompt。条长为三次中位数，端点误差线为 min–max，不是置信区间。

随后在 fork 后 29.5 s 分别给一个分支插入额外暂停 R_i，其他执行与队列固定，假定所有分支都必须完成。由 trace 完成时刻计算离线 slack σ_i，WCT 增量为 max(0, R_i−σ_i)。A1 的实测中位数 **33.2 s** 被其 91.2 s slack 完全吸收；A2 的 **32.6 s** 因 slack 为零而全部暴露；A3/A4 分别增加 **16.3/18.0 s**。图中纹理表示被吸收的延迟，实色表示计算得到的 WCT 增量。

**实测的是重建时间，WCT 增量是条件反事实计算。** 这里没有重放原 Claude 工作流或注入实际故障，也不估计这类结果在总体中的发生频率。共同 worker 故障与共享恢复资源需要联合分析，留在 Design 与 Evaluation 中展开。

AegisKV 的动机因此收束为：依据工作流完成收益分配有限快速层容量和备份存储。保留可用副本可以避免重建，让 KV 更接近执行位置还能减少恢复等待；两者对不同分支的 WCT 价值不同。同时，正常复用、容量消耗和保护 I/O 也必须计入，而不能只依据单请求重建成本决定保护优先级。

## 3. AegisKV Design

AegisKV 在有限 KV 存储下优化 WCT，同时保留正常缓存复用。先用两条有证据支持的观察建立问题，再介绍系统职责、决策依据和在线执行。下面与英文正文采用相同顺序，保留六个小节、三个算法和八张图。

### 3.1 Observations

**Observation 1：工作流依赖决定恢复紧迫性。** Figure 2 中，相近的重建开销对 WCT 产生不同影响：部分分支的延迟可被 Slack 吸收，关键分支则暴露全部暂停时间。因此，仅看请求恢复时间不足以决定保护优先级，还需要其在剩余工作流中的位置。

**Observation 2：历史 KV 访问集中于部分块。** Figure 3 先说明长上下文模型采用了不同粒度的稀疏选择；Figure 4 再以原生访问轨迹展示，少量历史块承载较多重复访问。两图分别回答“模型采用了什么访问形式”和“实际访问是否集中”，区分完整历史状态与计算经常使用的子集。

![稀疏／混合注意力模型的发布时间与报告上下文长度](figures/preview/sparse-models.png)

**Figure 3：长上下文模型中的稀疏访问形式。** 编号依次为 MiniCPM4、MiniCPM4.1、DeepSeek-V3.2-Exp、DeepSeek-V3.2、GLM-5、MiniCPM-SALA、DeepSeek-V4 preview、MiniMax-M3、GLM-5.2、LongCat-Flash-Lite-Sparse。横轴为公告日期或首次官方仓库日期（5、9、10），纵轴为报告的上下文档位；标记描述稀疏分支的选择单位，非全模型统一预算。它是选定模型的调查，不是采用率或稀疏率增长曲线；英文图注保留逐项来源。

![三个模型的原生历史 KV 访问集中度](figures/preview/kv-access-concentration.png)

**Figure 4：少量逐层块承载较多重复访问。** NOSA-8B、NSA-8B（MiniCPM-4-8B-NSA）和 MiniCPM4.1-8B 使用相同三篇 PG19 文本、32,704-token 前缀末尾的 512 个 Query。每个 Query 跨 heads 去重，对每层 503 个历史 64-token 块按窗口频次排序，先平均 32 层再平均文本；阴影为文本 min–max。约 20% 的块分别承载 87.64%、74.76%、56.54% 的访问。不含压缩／selector 状态，也不代表预测命中率或恢复加速。

这两条观察引出两个关联的决策：**哪些工作流状态应优先保护，以及其中哪些部分需要快速访问。** 具体介质和策略从 Overview 开始介绍。

### 3.2 System Overview

AegisKV 将工作流优先级与三层 KV 存储结合。Peer HBM 在另一 DP 保存选定层和热块以加速恢复，共享 DRAM 和 storage 保留其余历史用于正常复用和故障恢复。完整 checkpoint 由三层并集覆盖，迁移完成后每个对象只有一个受管 owner。这样，长历史使用大容量介质，有限 HBM 留给快速访问后最能帮助工作流完成的状态。

应用向 Controller 提供请求和工作流进度。① Workflow Tracker 估计每个 Agent 能吸收多少延迟，② Recovery-aware Router 确定执行和接管 DP；③ KV Master 结合紧迫性与位置，选择每个 KV 对象的保存位置和值得放入 Peer 的热块。Engine 中，④ Adapter 随正常推理压力调整 Peer 可用容量。Connector 执行 Master 下发的传输计划并回报结果。Worker 故障后，Router 将请求转向接管 DP，Connector 结合 Peer 命中和后备读取恢复执行。

![Application／Controller／Engine 三层架构](figures/preview/system-overview.png)

**Figure 5：模块归属、物理资源和数据路径。** 保留单栏三层结构、黑色序号 ①–④ 及对称 DP。① Tracker 预测时间与 Slack；② Router 绑定执行和 takeover DP；③ KV Master 联合选择三层 owner、Peer 层／热块并管理下层信用；④ Adapter 控制 Peer 总额。Connector 执行传输，右侧双向控制箭头明确 Master 向 Connector 下发计划、Connector 向 Master 回报传输状态；图中以 DP1 展示该通信，DP0 具有相同能力。蓝色实线是 KV 通路，深色虚线为控制，红色虚线为 retry。三层共同覆盖 checkpoint，Shared DRAM／storage 不重复保存 Peer 对象；资源形状不表示容量比例。

### 3.3 Workflow Tracker: Remaining Time and Slack

为在线提供工作流优先级，Tracker 先预测剩余执行时间，再计算 Slack。残余 DAG 中的 segment 是 Agent 在已暴露 fork/join 边界之间的顺序执行段，可含多轮调用和工具等待；子任务耗时归入子路径，不重复计入父节点，未知未来分叉不作已知边。

GBDT 以角色／模型、当前输入长度、已耗时、调用数和此前调用的长度、时间、上下文增长预测 segment 剩余秒数。缺失值有 mask，未来结果不作特征；训练／校准／测试按完整 workflow 隔离。

Algorithm 1 的输入 G/X 是残余 DAG 和因果特征，预测输出 d 为逐 segment 剩余时间。CPM 前向得到 earliest finish EF，后向以预计 workflow 终点为共同期限得到 latest finish LF，两者之差是 nominal Slack。Guard g 来自校准集上 Slack 正向高估的上分位数，扣除后为建议 Slack s；它是经验余量，不是逐请求概率保证。一个 segment 内请求共享同一余量。

**Algorithm 1：Remaining time and slack**

```text
(G, X) ← SnapshotProgress()
ν ← NextVersion()
if not Supported(G, X):
    PublishInvalid(ν); return
d ← max(0, GBDT(X)); g ← Guard()
EF ← Forward(G, d)
LF ← Backward(G, d, max_v EF_v)
for v in V(G):
    s_v ← max(0, LF_v − EF_v − g_v)
Publish(ν, G, d, g, s)
```

Supported 检查输入、依赖、校准和时效；无效估计不提供正 Slack。进度事件和周期刷新向 Master 发布版本化时长、guard 和 Slack，使旧估值失效。两遍 DAG 传播为 O(|V|+|E|)，预测质量留在 Evaluation 验证。

### 3.4 Recovery-aware Router

Router 确定正常执行和故障后恢复的位置。正常路由兼顾负载与兼容前缀的亲和性，同 Agent 多轮复用为亲和提供依据，但其他 Agent 的共享前缀也可能帮助首次调用。

![同 Agent 与跨 Agent 潜在前缀复用](figures/preview/agent-prefix-reuse.png)

**Figure 6：Agent 亲和的依据。** 98,827 请求、2,090 Agent、393 CC/Weka workflow 的历史前缀分析中，同 Agent 潜在 token 覆盖为 97.90%，额外跨 Agent 覆盖为 0.37%。这是潜在复用，不是实际 cache hit；首个 subagent 调用仍可能受益于共享前缀。

请求到来时，Router 同时绑定故障域分离、布局兼容的 takeover DP，其对应 TP shards 也是 Peer 位置。故障时 fencing 旧 epoch，按工作区／准入条件激活目标；新目标不能将旧目标的 Peer 字节计为本地；重绑定需要读取或迁移仍可达 owner，唯一 owner 丢失时发布旧 checkpoint／replay fallback。绑定结果向 Master 提供具体 Peer 位置、传输路径和目标负载，衔接后续放置决策。

### 3.5 KV Master: Workflow-aware Tiered Placement

Master 使用 Tracker 的工作流估计和 Router 的接管绑定，依次回答四个问题：哪些请求值得保护、价值分给哪些 KV、这些 KV 放在哪里，以及需求变化时如何持续调整。

#### 3.5.1 Workflow-aware Request Value

**哪些请求的状态更值得保护？** 请求价值同时包含正常复用和故障恢复。保留前缀可避免下一轮调用重建历史；加速恢复则减少超过 guarded Slack 的工作流延迟。大 Slack 不等于低复用价值：反复重算仍占共享 GPU，也可能推迟其他请求。因此正常复用始终进入决策，已经可由执行侧缓存命中的部分不重复领取保留收益。

Slack 本身不能决定排序，还要比较能节省多少工作、占多少容量。Figure 7 用一个构造例说明这个区别。

![Slack 与单位容量收益](figures/preview/retention-value.png)

**Figure 7：请求紧迫性不等于单位容量收益。** A 用两单位容量使恢复 4→2 秒，Slack=0；B 用一单位容量使恢复 18→8 秒，Slack=6。单位收益分别是 1 和 10 秒，正常复用收益置零。这是排序反例，不是策略加速实测。

同一 worker 故障会共同打断多个分支，两个并列瓶颈只加速一个，join 可能完全不提前。因此完整方案 P→P′ 的最终判断是：

`ΔJ = Σ_e p_e Σ_w [T_w(P′, e) − T_w(P, e)]`。

T_w 为预测剩余 WCT，有限场景表包括正常继续执行及不同偏移的 source-domain failure，概率之和为一。两方案使用相同队列、服务画像、有限 workspace 和传输调度；迁移干扰计入执行时间，再通过残余 DAG 的 join-max 传播。每个受影响 segment 只加一次 Tracker guard。Workflow 估计无效时不使用正 Slack，退回请求延迟；资源画像无效时暂停可选迁移。

#### 3.5.2 Prefix and Block Value

**一个请求的价值应该分给哪些 KV？** 从有效 fallback 开始，按 token 顺序扩展可恢复前缀，每个增量包含该 token extent 在所有层、TP shards 和 selector 中的依赖。其信用来自正常复用节省，以及超过 guarded Slack 的恢复延迟节省，使用与完整目标相同的场景和预测范围。保留前一路径作为选择，使局部增益非负。

例如，逐步保留前缀后恢复时间为 12、7、5 秒，Slack=6 秒，则未加故障概率权重的两次增量是 **5 秒和 1 秒**，不把全部 6 秒都记在尾部。每次增量按新增物理对象的字节数分配；不同 Agent 对相同 prefix 的贡献叠加，同一 Agent 重复引用不重复授信，物理容量只计一次。这样，前缀可因更多使用者累积价值，后续块获得自身增量。

该分摊是容量筛选规则，不是假定各层独立决定恢复。可用 fallback 或依赖改变后要重估整个方案，局部份额之和不能替代 ΔJ。前缀价值回答“保留什么”；稀疏访问和逐层依赖进一步回答“其中什么必须更快就绪”，自然衔接 Peer 放置。

#### 3.5.3 Three-Tier Placement and Peer Acceleration

**这些 KV 应该放在哪一层，Peer 保存多少？** 三层采用稳定态互斥驻留：同版本、同层、同 token block、同 TP shard 的对象在 Peer／DRAM／storage 中只有一个受管 owner；完整 checkpoint 由三层对象的并集覆盖，包括原生辅助状态。这不限制执行 GPU 为正常推理持有工作 KV。进入 Peer 的对象在迁移完成后释放下层副本，不再要求额外完整 DRAM 后备。

对请求 r，L_r 是 Peer 的前缀层数，K_{r,l} 是 l≤L_r 层选中的 token-block 数及其 TP 对象。先满足原生必需依赖，再按此前已完成 Query 的选择频次排名；每个 Query 跨 heads 去重，平局按 recency、block ID。预算低于必需集合时不可行。稀疏选择单位、引擎物理块和 kernel tile 不必相同，64 tokens 不是统一算法要求。未选入 Peer 的对象位于 DRAM／storage，miss 从真实 owner 读取，不修改模型原生选择。

![三层互斥驻留与恢复路径](figures/preview/sparse-recovery.png)

**Figure 8：一个 checkpoint 分布在三层。** 三行表示层，B0–B3 表示历史 token blocks；每格只标一个 owner。Peer 的 L=2，K1=2、K2=1，其他格分布在 DRAM/storage。Layer 1 需要 B0/B1/B2：分别走 Peer hit、DRAM H2D、storage read＋H2D；虚线 tail 尚未提交。下方强调 Peer→DRAM→storage 是实际迁移，不能直接删掉 Peer 并假设下面已有副本。

最后完整 checkpoint 覆盖 M 个 token，其后已确认但未提交的 token 构成 N。恢复 M 避免历史重建，执行 N 时可覆盖部分后续层传输。Peer 的价值是**相对于同一对象留在下层，额外消除的暴露读取／H2D 等待及其 WCT 影响**，取决于 M、N、热集覆盖和恢复队列。Peer 不收租金，直接按该条件收益重估。

![同样唯一 KV 覆盖下的分层恢复](figures/preview/recovery-pipeline.png)

**Figure 9：区分保留价值与 Peer 加速。** 使用既有 MiniCPM4-8B 校准的分析流水线：32 层、32K 历史、64-token tail，replay 2.870 ms/layer，假设 H2D 6.25 GB/s，平均 preload／preload＋miss 比例 0.6584／0.7748。前三种情况的 1,024 MiB 全在 DRAM；第四种将前 7 层选中热集共 147.5 MiB 移到 Peer，DRAM 剩 876.5 MiB，唯一 KV 总量相同，storage 在此切片不活跃。总时间／暴露等待为 264/172、175/83、136/44、112/20 ms。第三到第四减少约 24 ms 等待，但 L=7 只适用于该画像。这里放置已完成，使用理想可抢占传输和均质层均值，不计迁移、有限 workspace 和前台排队，冷块在 replay 后传输；不是新控制器端到端实测。

Master 枚举有限的逐层 K 数量／比例模板与 L=0…模型层数，并保留当前放置。每个故障场景使用当前 M 和含 commit lag 的预测 N；不支持稀疏画像时按完整 demand。只有仍必须执行的计算能隐藏传输。L、K 不必每增加一个 token 都变大：数量可固定而块身份变化，也允许 L=0。

三层位置与 Peer 选择联合评估：新冷块可直接进入 DRAM/storage；Peer 淘汰移到 DRAM，DRAM 淘汰移到 storage。目的层满时先级联腾挪，最后 storage 副本删除须为所有受影响 manifest 发布较旧 checkpoint 或输入／日志 replay fallback。共享块仍只有一个 owner，不同 Agent 的 takeover target 不能都算本地 Peer 命中；远程读取和重定位成本进入方案。声明保护的 source failure 必须不破坏这些 owner；唯一 owner 丢失时走 fallback，不能假设隐含副本。

#### 3.5.4 Renewable Credit and Online Management

**需求持续变化时，如何准入、保留和淘汰？** 多轮工具调用让需求跨请求存在，共享前缀又会获得新 Agent 的使用。一次打分不能跟上这些变化，每次 checkpoint 都续租又会保留陈旧状态。因此，仅在 DRAM 和 storage 使用受 Landlord／GreedyDual-Size 启发的可续租信用，Peer 使用上一节的直接收益重估。

下层 pool j 有独立压力租金 ρ_j；对象 x 大小 b_x，Agent 的当前授信 g_{a,x,j} 与已付租金 d_{a,x,j} 给出：

`C_{x,j} = Σ_a max(0, g_{a,x,j} − d_{a,x,j})`，`H_{x,j} = ρ_j + C_{x,j}/b_x`。

租金从零开始。时钟增加 δ 时，每个该 pool 中已提交驻留对象支付 min(C,bδ)，按正份额比例分摊；pin 不停止计租，可移除性另判。它表示容量竞争，不是经过多少墙钟时间。

**真实使用才续租，估值更新和搬迁都不续租。** 新 use ID 只重置使用 Agent 的已付金额；价值刷新保留已付租金，旧 prefix 不因 checkpoint 扩展而续租。对象离开某个下层 pool 后停止在该 pool 计租，但按 pool 保存的已付金额继续存在，返回时不能清零；经过 Peer 也不能洗掉旧租金。真实新使用才重置该 Agent 的金额。工具等待保留预测 interest，需求过期删除 grant。

![仅在下层使用的信用账本](figures/preview/renewable-credit.png)

**Figure 10：区分压力扣减、价值刷新和真实复用。** 一个 DRAM 单位对象由 A/B 共享，初始份额 3/2；扣租 2 后为 1.8/1.2。A 的 grant 3→4，但保留已付 1.2，所以其余额为 2.8；A 再次真正使用才续到 4。B 始终为 1.2。数字是构造的账本核对，不是 WCT 测量；Peer 没有此账本。

**准入与受害者搜索。** 下层在共同工作预算内刷新 q≥2 个低 key 对象和 q 个轮转替代候选；受害者组合须释放真实字节并保持有效恢复路径。释放集合 Y 时，将所在 pool 的试算时钟提升到至少 max H_Y，新进入字节在同样试算扣租后还要有正信用。已有对象不重复授信。Peer 受害者按当前恢复损失／字节筛选，同样通过合法方案与 ΔJ 检查；有界 bundle 可一起处理共享 owner 或并列 join 分支。

普通竞争尊重运行中请求的 Peer logical pin；请求结束／工具切换解 pin，本请求热集更新和强制容量回收可覆盖 logical pin，但不能覆盖实际 read/copy lease。每份方案都预留目的层和临时双份空间，并递归选择下层受害者。可选方案要求下层 incoming 的残余信用为正且 ΔJ<−ε；强制回收跳过正信用门槛，选择检查过的合法方案中损失最小者。无法完成安全级联则等后续事件，不能把缩 quota 当成已释放 HBM。

**在线闭环。** Prefill 提供新封闭状态；decode 按配置且对齐 block 的 Z 触发检查，结束／tool handoff 再提交最终 snapshot，覆盖短轮次。真实使用、价值变化、预算、故障与传输完成也触发 Algorithm 2。候选包括扩展 checkpoint、提升／降级、有效最后副本删除和 Peer 热集替换；周期有界刷新重访旧 key。无法提交扩展时 M 不变，copy lag 可使 N>Z。

**Algorithm 2：Online three-tier placement**

```text
Reconcile(e); SettleLowerResidents(e)
if NewUse(e): RenewAgent(e)
S ← RevalueAndSnapshot(e)
h ← ShrinkRequired(S); (best, cost) ← (∅, +∞)
for c in Candidates(S, h), while WorkLeft():
    for P in LegalPlans(S, c, h):
        if not h and not LowerRentOK(P): continue
        d ← ΔJ(P; S)
        if d < cost: (best, cost) ← (P, d)
if best = ∅: Defer(e); return
if not h and cost ≥ −ε: return
if not ReserveIfCurrent(S, best):
    Requeue(e); return
Submit(best)                 # completion / failure emits a new event
```

Connector 按“复制→目的端确认→目录换 owner→旧读者排空→释放源”执行；迁移期间两份物理容量都计入。预留前检查版本、lease 和 pool 时钟，拒绝的试算不改变真实租金／owner；容量交接时才提交相应租金，新对象保留试算后的余额。交接前中止复制保留旧位置，交接后的失败不能撤销已发生的迁移或退租。完整依赖就绪才推进 M，完成／失败事件再回到 Master，构成闭环。该有界扩展不继承经典租金算法的竞争比，也不声称搜索最优。

### 3.6 Adapter: Guarded AIMD for Peer Capacity

Master 在给定额度内选择内容，Adapter 根据正常推理压力调整总额度。采用压力下乘性减少、稳定窗口后加性增加，受物理上限约束：

`C = max(0, min(B_cap, B_pool − B_serve − B_reserve))`。

Pool 扣除模型与固定分配，serving watermark 不含 Peer，reserve 覆盖增长／workspace，避免重复扣 Peer；B_cap 可设为 pool 的一部分。当前额度 B 和稳定窗口计数 z 初始为零。分配 stall、预留突破、显存准入等待构成压力，B 乘以 0<γ<1；稳定要求无压力且等待低于较低阈值，连续 m 个稳定窗口且存在额度筛选前的正收益待处理需求时增加 Δ，允许从零增长。中间状态重置 z，缺失 telemetry 不增长。上限裁剪每次更新，紧急事件可窗口内减额，加额须等待稳定窗口完成；窗口和参数可配置。

**Algorithm 3：Windowed Peer quota**

```text
C ← SafeCeiling(); next ← B
if Pressure(): (next, z) ← (γB, 0)
else if Stable():
    z ← z + 1
    if z ≥ m:
        if PeerDemand(): next ← B + Δ
        z ← 0
else: z ← 0
B ← RoundDownPage(min(C, next))
PublishBudget(B); EmitCapacityEvent()
```

Adapter 调整总预算，Master 继续按固定 Z 和其他事件选择逐请求 L/K。当占用与预留超过缩减后的额度时，Master 暂停 Peer 准入并选择对象迁往 DRAM，必要时先把 DRAM 对象下放 storage；迁移与旧读者完成后才能重新使用 HBM。额度是授权目标，不等于即时空闲空间。

## 4. Evaluation

**最新互斥三层设计的证据界限。** 现有 DRAM／storage 结果来自较早的完整 checkpoint、Peer-disabled 策略，不验证本版互斥三层控制器。独立 layer model 是 I/O 机制分析。Figure 9 复用既有 MiniCPM4-8B 校准和声明 H2D 假设，改为相同唯一覆盖下将对象由 DRAM 移到 Peer 的容量核算；没有新增实测或将旧模型重新标成集成结果。


本节按“主结果—因果解释—真实 trace—完整消融—代价与边界”组织，正文保留 **8 张必要的单栏图**，同时完整保留 17 个实验小节；其他图像继续保存在实验包中。证据分为解析模型、真实 trace 的描述统计、trace-driven model、待执行物理实验；没有把理论曲线写成已完成的系统测量。完整逐项执行规格在 [EXPERIMENT_MATRIX.md](../experiments/eurosys27/EXPERIMENT_MATRIX.md)，逐图说明在 [FIGURE_CATALOG.md](../experiments/eurosys27/FIGURE_CATALOG.md)。

### 4.1 实验契约、基线和统计对象

物理系统至少需要两个故障分离的 serving replicas 和故障后仍可访问的 backing store。TP2 的 host failure 需要两台各有两张兼容 GPU 的 host。GPU process、整个 replica、host、storage host 失效是不同实验；同 host 的 SSD 不能支持 host-loss 保护声明。DP=2/4/8 与 TP=1/2 分开测，记录真实剩余容量、执行 KV、activation 和 staging HBM。

工作负载包括 coding agents、FanOutQA 和受控 sequential / balanced fork-join / heterogeneous fork-join，每 family 至少 30 个独立 workflow。原始 DAG 只运行一次，首调用也进入完整 prompt 分母；主实验冻结工具响应，live tools 单独验证外部有效性。覆盖 dense/native-sparse 模型和受支持的 32K/128K/512K/1.01M 长度；不支持/OOM 的 cell 不伪造数据。

Recompute 对照说明可靠 checkpoint 的作用；同样完整覆盖、同样 DRAM/storage 预算、同样 manifest/lease/transfer 的 LRU 与 reuse-only，才隔离工作流价值的贡献。All-DRAM 是放宽容量的参考；小实例 oracle 仅在同候选集合与同目标内有效。外部系统必须运行真实 artifact 或标注 reimplementation，不能给 DéjàVu/GhostServe/LUMEN 编造理论性能。

每个策略各有 healthy mate，定义 D=WCT_fault−WCT_healthy，策略比较用同 ID 的 D_LRU−D_Aegis。并列报告绝对 WCT、completion、deadline goodput 和 p50/p95/p99。分三类 cohort：直接 interrupted、未被 kill 但共享 reader/NIC/GPU、资源独立。10 个独立 paired campaigns 是一级重复单位；workflow、request、token/层/块是其下级，不能混充独立重复。

### 4.2 一次故障：系统收益有多大

主 cell 在固定 workflow/Agent/request 达到冻结总 token progress 80% 时 kill source replica，包含该 source 上全部受影响请求。Mechanism attribution 固定故障前路由、committed coverage、transfer scheduler；full-system 比较允许真实路由和 achieved frontier 变化，但固定原 arrival cohort 做 intent-to-treat，不能按各策略自身“幸存样本”筛选。

理论基例有四个分支：state=4/8/12/16GiB，remaining=12/10/5/1s；DRAM16GiB、storage160GiB，DRAM/storage/NIC/H2D=20/4/12/20GiB/s，两恢复目标，floor0.25s、replay0.4s。0.25GiB chunks 通过共享 reader、NIC 和目标 H2D 调度。所有 rates 都是声明的模型假设，未标成某种 SSD/GPU 的校准。

36 个 size×slack×storage-rate 配置中，workflow value 对 LRU 为17优、19平。LRU 与 reuse-only 在此构造顺序下恰好选同对象，不能外推所有复用策略等价。基例 penalty：storage-only5.5583s，LRU3.6208s，workflow value1.6125s；相对 LRU 减少2.0083s，即 **failure penalty 减少55.5%**。这是 residual join 从15.6208s降到13.6125s，不能宣传为完整 WCT 降55.5%。

![workflow-outcomes](figures/preview/eval-workflow-outcomes.png)

### 4.3 一次故障：优势来自哪里

四分支 join slack 为0/2/7/11s。LRU 把最大、最近的 A3 保留在 DRAM；workflow value 保留 A0/A1。前者加速的 A3 大部分恢复本可隐藏在 Slack 内，后者优先消除 A0 的暴露延迟。WCT penalty 应直接计算 max(d_i+R_i)−max(d_i)，不是把所有单请求 positive-part penalty 相加。

![branch-exposure](figures/preview/eval-branch-exposure.png)

固定 placement 后，按 floor→read→NIC→H2D→replay 顺序恢复资源成本，逐次计算最终 join 的差，得到可以望远镜相加的 counterfactual 分解。交互项归属依赖顺序；它不是唯一“因果贡献”。实测还应沿 parent event 链抽取真实关键路径，只累加路径上不重叠的时间。总 SSD+NIC+H2D+GPU work 必须另列，不能当成恢复 wall time。

重要反例是：workflow value 从 storage 读28GiB，高于 LRU 的24GiB；整个恢复池占用7.6833s，也高于6.6833s。它改善当前 workflow 的 join，但没有减少所有资源成本。正文保留这些资源成本，逐项分解图保存在补充图包中。

### 4.4 一次故障：是否把延迟转嫁给其他 workflow

实验交叉变化 simultaneously interrupted workflows=1/2/4/8、targets=1/2/4、固定前台负载30/60/85%；增加 reader/NIC 独立的对照。记录 direct/collateral/isolated cohort 的 WCT、retry queue、backlog、恢复到预设 latency band 的时间。共享拓扑不存在时，不声称跨目标 cascade。

FIFO 模型中一个四分支恢复独占两目标 pool 直到最后一个 ready，n 个同刻恢复的均值为 D+(n−1)S/2。n=8 时，workflow value28.5042s，反而差于 LRU27.0125s。单次收益不能直接外推成 burst 收益；完整 load-aware router 是否纠正这种问题，仍需真实实验。

![burst-interference](figures/preview/eval-burst-interference.png)

补充流体 backlog 模型固定正常 I/O 使用70%的4GiB/s reader，以剩余带宽消化恢复字节，说明更大的 bytes 会拖长清空。它是 I/O backlog，不是 TTFT 或未失败 workflow 的实测 WCT。

### 4.5 故障阶段、Z 与实际提交滞后

同 ID 重复20/50/80/95%逻辑进度，另外测 prefill/decode/tool wait/迁移 commit 边界。当前 phase 模型只改变历史 state 大小，固定 remaining 与预算，用来隔离增长效应；物理实验必须同时记录实际 DAG、原生需求与 committed frontier。

Z=64/256/1024 的理想平均应枚举所有 phase，同 Z 同 phase 配对后再平均。实际日志保存 trigger/attempt/start/commit/frontier/ack，tail N 可以超过 Z。短 Z 可能增加 write contention 与失败提交，不能把 Z 当 durability 上界。

### 4.6 真实 failure trace：先核对语义

LANL 官方数据定义是带 node/system、start/end、cause 的历史节点 interruption。原始 FTP 当前不可达；本次取得版本钉住的公开原格式 CSV redistribution，共23,739行，而官网描述23,741行；**差异未解决，不能声称与原始archive字节一致**。清洗保留 purpose=compute，排除非compute1,648行、零时长122行，同节点相交/相接区间合并231，得到21,738 intervals、22 systems、3,542 observed nodes。所有原因都保留，包括可能的 maintenance，不能改称 hardware-only crashes。

分钟分辨率下，19,561个同系统 start groups 中568个多节点，最大45节点；时间相同不证明同一物理原因。不同系统不叠成一个集群。历史 CPU/HPC trace 用于检验时间聚簇，不是2027 GPU failure rate或fleet availability 的估计。

现代 Reflex/ByteDance 数据有98个训练 job、344,175条 alerts、144个 faulty node/job labels，其中108个 label 没有该节点 alert；各 job 又独立平移时间且无repair times。因此只做 label 分布，不拿first alert当fail-stop，不拼接跨job日历。

### 4.7 原始日历重放：平均收益与尾部必须同时看

当前条件模型把每个 cleaned node start 映射成一个假设的四分支 workflow 恢复；每 original system 有独立 FIFO spare pool。placement 在 trace 前固定，保留原始 start 间隔，以 node ID打破同刻顺序。递推 q_i=max(0,q_(i−1)+S−Δa)，penalty=q_i+D。原始数据提供到达日历，服务时间来自字节与速率模型。

这个模型假设恢复池一直可用，没重放健康服务、有限spare、真实GPU修复、第二次target失败，所以只能称 **trace-driven recovery-load model**。不能因为 input trace真实就把输出称物理WCT实测。

![trace-penalty](figures/preview/eval-trace-penalty.png)

原速下 LRU mean10.4533s、workflow value9.4673s，改善9.4%；但queue wait6.8324→7.8548s，p95 37.0375→40.0292s，p99 204.1208→232.1125s。补充逐 system 图采用紧凑竖柱，保留全部 22 个 system ID；纵轴为 LRU 减去 workflow value 的平均 penalty，负值完整保留。均值改善支持条件结论，尾部变差否定“所有尾部均更好”的声明。

同分钟事件按node ID均匀展开到59秒的分辨率敏感性下，LRU/价值模型mean为8.0997/7.0224s、p99为163.8936/191.8852s，负尾部仍在；构造的秒级时间不是推断出的真实时间。even-spacing对照保留每系统事件数量和首末时间，去掉聚簇；10/100/1000倍time compression明确是压力测试，只有1倍保留原速。完整campaign必须：固定workload/domain mapping并公开seed；按down/up真实减少/返还capacity；保留故障簇、recovery期间再次失败、所有open-loop arrivals、未完成workflow；不同spare fraction和storage-domain另列。事件簇大于机器规模时明确unsupported或按声明规模仿真，不能偷偷串行化45节点事件。

### 4.8 完整价值消融与四格交互

消融矩阵包括：无DAG/Slack、joint source-event改为isolated sum、无normal reuse、无failure value、frozen placement、direct revaluation去掉租金、主策略无renewal、主策略无value refresh、主策略无hysteresis、recency替代causal sparse history、serial替代bounded layer overlap、locality-only替代load-aware router，以及singleton与bounded-pair候选。每项保留同样安全覆盖、预算与原生attention。

![value-ablation](figures/preview/eval-value-ablation.png)

当前合并消融图将六种策略的 failure penalty 与 normal next-use cost 并排，使用 storage=4GiB/s 下同一组12个size/slack配置（36配置CDF的一个子集）；两类成本不能相加，均值口径不能混用。该图只评价static value，其余机制不能借这两个图声称已被完整验证。共同失败反例显示候选存在互补性，必须整方案revalue；增加pairs时同时报告oracle regret和控制成本。

四组2×2交互：DAG×joint-fault、sparse rank×overlap、rental screening×hysteresis、load-aware route×shared-link contention。四个cell同campaign配对，interaction=(Y11−Y10)−(Y01−Y00)，不能把独立speedup相加。安全协议不做“关闭后更快”的有效性能基线。

### 4.9 稀疏需求与layer overlap的解构

八层模型，每层full selected payload的SSD4ms、H2D1ms、compute3ms；DRAM同样容纳两层payload，staging最多当前+下一层。early/late placement与serial/pipeline四格保持同需求。改变selected-density时所有策略一起变，不允许为了cache策略更好而改变native attention。

![layer-factorial](figures/preview/eval-layer-factorial.png)

full demand下两个serial都56ms，late-pipeline34ms、early-pipeline32ms；所有case required compute都24ms，差别来自exposedwait。错误prefetch消耗额外读、真实需求等reveal才读；当前correct-prefetch比例是人为输入，正确位置按层序指定，不是学习器准确率。

原生实验捕获held-out retry的per-layer demand union与reveal时刻，用此前历史预测；按workflow/document分训练验证，不按blocks拆分。equal physical bytes、mandatory sink/window和coverage保持一致，报告all-layer coverage、unused/miss bytes、reveal-to-ready、GPU stall、workspacepeak、total replay和WCT。早期层100%命中不等于全部层100%。

**新增三层配对实验（待执行）。** 固定三层并集的完整覆盖、fault ID、原生 demand 和恢复调度，比较 Peer=0、同容量 recency/frequency、固定 L、逐请求 L/K，并做 Peer 位置×overlap 四格。使用同一物理 HBM pool，记录被 Peer 挤出的正常服务、跨 DP 复制、实际 Peer→DRAM→storage 迁移和所有临时容量；另做同物理预算的互斥／重复后备对照；扫描 M、真实 N、Z、热集漂移和 target rebind，联合报告增量 WCT、正常吞吐和传输字节。本地 HBM reuse 微基准不能替代该实验。

### 4.10 租金问题诊断与直接重估对照

当前提出的主策略是“下层真实复用续租＋保留已付租金的价值更新＋Peer 直接重估＋完整计划检查”。原 8 slots、24 等大小对象、512 个确定性候选机会的简化模型保留为反例：它只在 candidate revisit 续租，scored next-use hit 不续租，并且只检查一个最低信用受害者。模型没有多 Agent 份额、prefix 依赖、三层降级、物理 lease 或 serving scheduler，不能代表新控制器。

![历史租金反例，未改动其数值](figures/preview/eval-rental-cost.png)

Direct 与旧 trial rent 的总 miss＋movement 成本仍为 **462.96／506.39**，迁移 108／106 次，均为 396 次 scalar 替换检查；去 hysteresis 迁移 121 次，去 renewal 迁移 77 次但总成本 526.05。原轨迹有 104 次拒绝时存在另一个满足当前收益门槛的对象，这只是诊断计数，不能把它当作成本差额的因果分解。

同样输入、成本参数下，仅增加 scored-hit 续租反而为 **512.67**；价值更新且不退租降到 **477.86**，再检查两个低信用受害者降到 **466.76**，缩小原差距 91.26%，仍比 direct 高 0.82%。4 个起始 phase×3 个变化周期×3 个容量的 36 格中，最后修正全部优于旧租金，但对 direct 仅 9 优、27 差。它也付出 747 次替换检查＋4,088 次 key 更新，不能声称控制成本更低。该修正诊断不等于新版完整控制器性能验证。

下一步比较必须在相同价值模型、候选机会、安全协议、物理资源和控制工作预算下，对照 direct、旧 screening 与新算法；分别消融真实续租、当前价值更新、多 Agent 信用、备选受害者搜索。覆盖多轮工具等待、上下文增长、同角色共享前缀、突变、下层存满、Adapter shrink，以及跨层往返不清空已付租金。记录 grant／已付租金／trial 与 committed rent／版本失效／DAG pass／CPU／迁移／实际 M／miss／WCT。保留上述反例作为回归，而非删除或解释成已验证的新算法收益。

### 4.11 容量、I/O和有限可靠覆盖

DRAM/unique-working-set为0/0.1/0.25/0.5/1，storage为0.5/1/2；shared物理对象按actual replica计费，reserved/retiring/metadata也计入。小storage要真实触发last-copy eviction，不能靠无限SSD假设掩盖fallback。All-DRAM只有参考地位。

![capacity-frontier](figures/preview/eval-capacity-frontier.png)

容量曲线中fault-only penalty可以不单调：oracle在16→28GiB时，joint score从0.15049降至0.14383s，但fault penalty从1.6125升至1.9458s，因为normal reuse也进入目标，且传输共享资源。对应resident对象和两个目标保存在capacity-objectives.csv，不能混称“oracle变差”。

测read/write/同时读写、不同IO粒度、并发、NIC/H2D、client与server cache。Direct IO只控制client路径；DPC或sharedFS server cache未知就保留未知。加storage slowdown/loss，对比真实可恢复coverage，不将低预测latency当状态可用性的证明。

### 4.12 预测、stale profile与fallback

既有诊断包含 170 workflow、1,443 个 request-2 Agent，标签是整个 Agent 剩余时间。五折 workflow-disjoint MAE 为 median/basic/history 438.6/406.7/407.1 秒；basic−median 的配对区间 [−80.9,4.9] 秒跨零，六个特征相关区间也跨零。这不能证明均值改善或 residual-segment Slack 准确。原始预测、全部误差尾部和诊断图保留在外部实验材料；Design Algorithm 1 只定义预测与 Slack 计算流程，不宣称预测精度。

剩余时间学习器用causal landmarks，按完整workflow做时间划分；报告remaining error、falseSlack、criticalrank、fallback率和推理成本。不能从相关系数/WAPE反推raw CDF。对照median、zeroSlack和oracle duration。

当前alternating−25%扰动使workflow value penalty4.5583s，差于LRU3.6208s。实验扫描独立/相关±10/25/50/100%、缺边、coldstart、模型shift、带宽profile过期和failureprobability误校准；重新运行策略决策，再对真实结果计regret。

### 4.13 正常服务与保护值不值得

F0使用原DAG一次，首调用和全部requests计入。报告WCT、TTFT、ITL、SLOgoodput、GPU/CPU成本和分tier request/tokenhit，区分potential prefixsharing与runtime命中。当前M/D/1只说明I/O干扰，不是TTFT。

同horizon、同单位的摊销模型是 p_f×ΔD−C_h。基例ΔD2.0083s、健康成本0.05s时，需要p_f>0.0249。该概率与健康成本均为敏感性输入，不是trace估计；真实低故障率可能让总体净收益为负，即使条件恢复更快。

### 4.14 正确性、故障交错与pressure

覆盖reservation、partialcopy、checksum、COMMITTED、redirect、tokenack、lease drain前后注入；增加duplicatecallback、staleepoch、targetloss、missingTP/selector、timeout和fulltiers。PENDING不可读、manifest必须闭合、accepted output不重复、tokenlog生存、greedy-next-token和all-layer状态在声明精度下匹配。工具副作用的idempotency另查。

24→16GiB target不代表物理内存立即释放；当前模型5.5s才在commit/redirect/drain后释放8GiB。真实测试包括reversepressure、leaseoverlap、copyfailure和lastcopyfallback；逐事件核对物理/预留/提交/retiring/free。小状态机穷举并对每类交错至少100次随机执行，不能只用静态assert代替协议运行。

### 4.15 扩展性与控制成本

DP2/4/8，DAG10/100/1000，groups10²/10³/10⁴，候选16/64/256；独立扫描sourceconcurrency和targetcount。测decisionp50/p95/p99、profilecalls、nodes/edges visits、lock、metadata、planage、foregroundstall和actualWCT。

补充扩展性模型只是声明per-node cost的操作投影，没有校准CPU，也没有把复杂profile与候选枚举成本藏进O(V+E)。oracle只在小集合可行，不能把大规模无oracle写成gap=0。

### 4.16 统计、复现与执行顺序

一级单位为独立pairedcampaign，先算同workflow的各策略F1−F0，再算策略差，campaign内聚合后bootstrap campaigns（10,000 resamples，固定分析seed）。trace要同时给event-weighted与system/window-weighted结果，整簇/整非重叠window重采样，不将同一次事故的节点数当独立运行数。所有当前解析/trace模型图physicalruns=0，不制造CI。

统一观察τ，所有输入workflow进入completion/deadlinegoodput；complete-case latency需要共同eligiblecohort和排除计数。使用RMST须声明估计器与删失假设，timeout不能填假的完成时间。原始日志、manifest、sourcehash、数据转换和绘图命令必须可追溯。

执行顺序：正确性/后端校准 → 单次故障主结果及关键路径/队列分解 → 正常开销 → 关键四格消融 → 连续真实trace → 压力/预测/扩展性。当前两个必须面对的研究问题是 **静态workflow优先级的队列尾部回归** 与 **可续租信用与当前价值更新在完整在线控制器中的成本与效果**；后续实验应解决或缩小这些主张。

### 4.17 图像配置与数据替换

图像宽3.33465in，固定物理字体和边距，PDF/SVG/PNG三种导出；输入CSV与独立visual spec。数据换成实测后，保留同坐标、单位和layout；负值、timeout和尾部不能删。`prepare_measured_figures.py`检查原始物理日志hash、aggregationcommand、campaignunit及sampleaccounting，支持只替换已有实测的图；未测图继续保留原证据标签。理论结果解释与caption不会因换了CSV而自动获得实测含义。

## 5. Related Work

DéjàVu、GhostServe 和 RaidServe 已分别研究 KV 复制／编码及 TP 故障恢复；LUMEN 已研究 load-aware checkpoint 与恢复分配。Mooncake、CachedAttention、Strata 和 HCache 已研究分层复用、传算重叠、存储布局或其他状态表示。Parrot、KVFlow、Pythia、Cortex 与 TOPAS 已使用工作流信息优化正常执行。特别是 TOPAS 已结合 remaining service path、reuse 和 movement cost，因此“Slack 加缓存”不足以支持新颖性。

本稿把拟议差异限定为：共同故障域对多个请求的联合影响，正常复用与恢复保护共存，Peer 加速、逐对象跨层迁移与 last-copy deletion 的不同后果，以及异步迁移时有效 checkpoint 的保持。完整原始来源和对应实验要求见 [RELATED_WORK.md](../experiments/eurosys27/RELATED_WORK.md)。这些差异需要实现与消融证明，而非由命名或架构图自动成立。

## 6. Conclusion

AegisKV 将 KV 保护视为有限 Peer HBM、DRAM 与共享存储中的在线工作流资源管理：三层独占 owner 的并集提供完整恢复路径，逐请求 Peer L/K 提供快速访问。它保留普通复用，按依赖评估共同故障，并将期望放置与实际提交状态分开。理论分析给出了可能有价值的区域和明确限制：DRAM 容量充裕、storage 较快、预测偏差或共享队列都可能使收益变小。新版完整论文、模型与图像已经形成可复算的研究草稿；能否成为有竞争力的 EuroSys 系统论文，仍取决于协议实现、强基线和真实配对实验。

## 附录 A. Motivation 测量协议

**配置与测量层次。** Figure 1(c) 与 Figure 2 使用同一固定版本的 Qwen2.5-7B-Instruct-1M 权重、SGLang 0.5.10rc0、PyTorch 2.9.1/CUDA 12.8、BF16、TP2、batch 1，以及相同型号的两张 A100 PCIe 40 GB。Figure 1(c) 来自一次分配，Figure 2 来自另两次分配；正文“同配置”不表示同一个节点或同一次运行。MInference vertical/slash 参数、模型/注意力源文件与 SM80 内核哈希匹配。GQA 共享 K/V，前缀每组最多两个 query heads，单 query 合并全部 heads；这属于带适配与计时的 worker 微基准，不是未经修改的 serving 前端吞吐实验。

**统一终点。** C=M+1。Full Prefill 从空 KV 按至多 8,192 tokens 分块计算 M，再单独处理一个 token；复用路径使用相同稀疏生成的历史（含不完整页）。同步 wall time 取两个 TP rank 的最大值，终点为模型主体完成、全部 C-token KV 驻留，输出词表投影在外。模型加载、备份创建及校验不计时，也没有检测、路由、服务排队和故障注入。

**恢复路径与缓存。** DRAM 先把所有历史层从 pinned buffer 拷到 HBM，再计算。共享存储先打开、读取并关闭计算节点 DPC 文件系统上的逐 rank KV 文件，再执行相同 H2D 与计算；三个阶段串行，无压缩或选择性加载。1.01M 历史为 57,917,382,656 个逻辑字节，文件另有记录的对齐填充。O_DIRECT 与 mincore 检查排除 Linux 文件页命中；DPC 服务端/内部缓存不可控，不能称为冷 SSD 或纯介质延迟。共享 KV 已在测量后清理，本次 Figure 2 补测不创建存储 KV 文件。

**样本与预热。** Figure 1(c) 的作业 1517208 测四个长度：8,192、65,536、262,144、1,010,000。HBM/DRAM 预热一次、正式计时三次；Full Prefill 和 Shared storage 各一次。计时前有短 forward 与算子检查，64K 另有完整原生 all-head 稀疏参考；256K/1.01M 没有重复完整 Prefill 预热，共享存储没有读取预热。因此后两条曲线是单次运行结果，不是稳定延迟分布。Figure 2 在作业 1517915 中完成前三个长度；最后一个长度收到提前终止信号后，在作业 1517917 单独补齐。每个绘图点均取一次完整 Prefill 预热后的三次计时。中断点的部分计时完整保留但整组不用于绘图。重复的是同一输入的计时，不是独立工作流；min–max 不表示置信区间。

**校验与映射边界。** 检查完整历史哈希、最终 hidden、各层新 KV 和 greedy 输出，额外比较重复 Full Prefill 输出，并用 CUDA timeline 检查串行拷贝。它们证明被比较的稀疏路径状态匹配，不证明 dense 等价或长上下文任务质量。Figure 2 的长度是 active request 的 hash-block 代理，不是原模型准确 token 数或故障时已完成的 KV frontier；将其完整 Prefill 时间作为额外暂停插入原时序是一项明确假设。原例按四个分支、gap 约 100 s 选取，不能据此估计总体故障收益。

数据入口：[Figure 1(c) 原始实测](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1517208/measured.json)；[Figure 2 前三个长度](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1517915/measured.json)；[最后一个长度](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1517917/measured.json)；[分支映射与同配置核对](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/motivation-compact-cc/recovery-costs-measured.json)；[共享存储协议](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/SHAREDFS_PROTOCOL.md)；[共享 KV 清理记录](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1517208/sharedfs-terminal-cleanup.json)。

## 设计补充说明（仅供实现与实验复核，不进入英文正文）

以下记录实现与实验复核需要的细则；正文按研究问题解释机制作用，相关定义在决策或恢复过程真正用到时介绍。

- **故障与状态约定：** 保护停止工作的 compute worker，依赖兼容存活 DP；位置目录、有序 token log 与已公布后备须在对应故障域之外。应用提供已知依赖及已接受输入；外部工具操作的 exactly-once 不由 KV 恢复保证。存储对象是封闭后不可变、版本兼容的某层某 TP shard 的 token block。完整 checkpoint 包括所有层、TP、原生 selector 等辅助状态及匹配日志前缀，依赖通过三层 owner 的并集完整覆盖；只有完整提交才推进 M。执行侧工作 KV 不属于这三个受管层；稳定态独占、迁移期双份计费，目的端确认且旧 reader 排空后才释放源。受保护的 source failure 必须不丢失所公布 owner；额外 owner loss 要重绑定或退回有效旧 checkpoint／日志重放。短轮次最终 partial block 以有效长度及 copy-on-write 保存，接受的复制持有源 lease。

- **对象与训练口径：** 对象身份还包含模型／权重版本、布局、精度、位置和前缀语义。只有辅助状态有效的前沿才能拆分 extent，否则相邻 extent 作为一组。GBDT 的标签是快照到 segment 结束的剩余时间，不能用跨嵌套 fork 的 whole-Agent 标签代替，也不能从 remaining-time 预测再次扣 elapsed；任务／工具描述仅在应用确实提供时用作特征。
- **需求与信用：** 未支持的复用预测不能凭空增加未来调用；真实使用按 Agent 和 request/use-event 去重。过期、不活跃的 interest 可删除，只有新观察到的使用才能重建，价值刷新本身不能重授初始信用。所有对象已存在时可以只关联 manifest，不复制，也不续租未变前缀。
- **跨层信用：** 仅 D/S 有压力时钟和按 Agent 保存的已付金额。离开 pool 时先结算并停计，返回时保留已付金额，首访该 pool 从零已付金额开始。真实新 use 重置该 Agent 的各 pool 已付金额（可按 use epoch 懒更新）；其他 Agent 不重置。临时副本计容量但不重复授信，换 owner 时切换计租 pool。Peer 不计租；逻辑对象的下层历史账目仍保留，避免往返洗租。
- **有界竞争：** incoming 在真实当前租金处建立试算份额，尝试下一受害者时不重新授信。纯 metadata 修改不经过新字节准入门槛。每次 grant 计算、扫描、候选与 DAG pass 都计入同一工作预算；低 key 与轮转候选避免首次替换失败就结束。Owner bundle 与并列瓶颈 bundle 同样有明确大小上限。
- **异步提交：** 不相交 pool 可并行，共享资源通过版本化预留串行化。已准备的容量交接再次检查版本、lease 和 fallback，发布后先撤销受害者的新读资格，再等待旧读者排空。交接前失败丢弃试算；交接后失败保留已发生的租金和淘汰。Storage 的 buffered write ACK 不等于达到后端持久化契约。Prefill 故障也从最近完整 M（可能为零）恢复，执行工作区不足时排队或重绑定。
