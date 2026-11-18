# AegisKV：面向工作流的 Peer HBM／DRAM／共享存储 KV 管理

英文完整稿与编译入口为 [main.tex](main.tex)，当前 PDF 为 [main.pdf](main.pdf)。本稿按最新决定恢复 **Peer HBM＋共享 DRAM＋Shared storage** 三层：Peer 为每个请求保存选定 L 层、每层 K 个热块；DRAM 中已准入的 checkpoint 保持完整，容量不足时可整份降到 Shared storage。直接价值重估继续作为主策略，Z 固定配置，Adapter 只调整 Peer 总容量。既有 Evaluation 是明确标注的旧配置／子机制分析，不能据此声称新版三层控制器已经实测。

按 2026-09-21 最新要求，当前阶段取消 12 页压缩，以内容完整为先。Evaluation 保留 17 个完整小节，正文精简为 8 张必要单栏图，另外 26 张补充/备用图保存在实验包中；逐项实验规格、完整消融矩阵、trace 数据来源与可替换 CSV/绘图代码全部保留。图号以当前 `main.pdf` 为准。

## 1. Introduction

多 Agent 应用的用户等待的是整个任务完成，而不是某个请求单独完成。代码修改、并行检索和综合报告包含串行依赖、并行分支与汇合点；同样长的请求延迟，发生在不同分支上，对最终结果的影响可能完全不同。正常运行下的工作流调度和 prefix caching 已经利用这类信息，但故障提出了另一个问题：一个 worker 同时中断若干请求后，有限的快速恢复资源应该保护哪些上下文？

Agent 的多轮调用不断积累推理、代码和工具输出。失去 KV 后，重建长历史可能远比设备中断本身昂贵。KV checkpoint 可以避免这部分计算，但全部历史不能无限留在 DRAM。SSD 或共享存储提供更大容量，代价是读取、网络传输和排队。普通 LRU、单请求恢复速度、甚至单独的关键路径优先级，都不能完整描述这些权衡。

AegisKV 将共享缓存与故障恢复状态统一管理：**大 Slack 不禁止正常缓存；DRAM 降级与最后副本删除分别估值；同一故障域中断的请求共同经过 DAG 计算其影响。** KV Master 选择有限容量内的保留和迁移方案，引擎接口与传输路径在版本化 manifest、空间预留和 reader lease 约束下安全执行。Router 在请求到来时绑定故障域分离的 takeover／Peer DP，故障后激活；目标失效时退回完整 DRAM／存储恢复。

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

本节采用三层保护：Peer HBM 为恢复加速副本，DRAM 为完整 checkpoint，Shared storage 为完整 checkpoint 的容量后备。普通执行 HBM、Peer 区域和临时恢复工作区分别计费。元数据、token log、takeover DP 和后备必须在被保护的故障后存活，同机内存／SSD 不自动保护整机失效。新图是设计示意或可复算分析，不是端到端实测。

叙述顺序为：WCT 和正常复用决定价值 → 完整 checkpoint 决定可恢复性 → Peer L/K 与层间重叠决定额外加速 → 直接重估选择完整计划 → Adapter 提供容量约束 → Connector 安全执行。

### 3.1 Design Insights

第一段承接 Motivation：故障恢复越快并不必然让 WCT 越短，需要看依赖和 Slack。但 Slack 较大的 Agent 仍会在工具返回后复用自己的历史。因而把“保留可复用副本”和“占用更快一层容量”分开；正常复用价值不会因为故障概率低或 Slack 大而消失。

第二段介绍稀疏访问的机会与边界。原有稀疏模型发布概览说明适用背景；原生轨迹实验说明过去的访问能够预测部分未来需求，同时模型间差别明显。40% 预算下过去频率预测的覆盖率：NOSA 77.8%、MiniCPM4 53.6%、实验性 Seer 路径 43.0%。它们不是故障恢复加速比，也不足以支持删除未预测的 KV。

![原生稀疏模型样本](figures/preview/sparse-models.png)

![未来历史 KV 需求的预测覆盖](figures/preview/retry-kv-prediction.png)

**正文 Figure 3 保留预测覆盖图；发布概览作为详稿素材。** 模型样本不是部署占比；预测实验为每模型三篇 PG19 文档的原生采集，历史 32K，以前 512 个查询预测后 64 个查询；物理评估单元是 layer/64-token block，含全部 KV heads，预算包括必需块。误差条为文档范围，不是置信区间。新增菱形为同预算、同必需块条件的离线 oracle 均值：93.7%、59.0%、43.3%。Seer 的频率策略 43.0% 已接近该上界，其低覆盖主要受这组未来查询需求并集下的容量限制；不能直接将其解释为预测器很差。三篇文档只支撑这些样本中的观察，不能替代大样本、长上下文 Agent 故障恢复验证。

第三段引出 Peer 的增量价值：完整 DRAM 已经避免历史重建，Peer 进一步省去选中块的 H2D；只有没有被剩余回放计算隐藏的传输才直接影响恢复时间。L 取决于请求当前 M、未知故障尾部 N 的分布／界、需求揭示、队列和工作区，不能统一给所有请求一个窗口 L。

### 3.2 System Overview

![三层保护架构](figures/preview/system-overview.png)

**本图紧随架构描述，保持单栏和 Application／Controller／Engine 三条横向分区。** Application 暴露 Agent 请求、依赖和进度。Controller 负责策略与存活元数据；Engine 显示两个能力对称的 DP、独立 Local KV 和 Peer KV、Adapter 和 Connector，以及边界之外的完整 DRAM 和 Shared storage。

- **Workflow Tracker**：GBDT 估计剩余时长，CPM 给出版本化 Slack。
- **Recovery-aware Router**：正常负载／亲和路由；请求到来时绑定 takeover DP，也确定 Peer 位置；故障时 fencing 并激活 retry。
- **KV Master**：决定完整 checkpoint 的 D/S 位置、Peer 的 L/K/热块集合，并直接重估来者和受害者构成的完整 DAG 计划。
- **Adapter**：每个时间窗口给出该 DP 可供 Peer 使用的总容量，不决定 L/K，不改变配置 Z。
- **Connector**：按预留与版本执行复制、提交、恢复和释放。
- **Directory**：维护对象身份、完整 manifest、位置代际、绑定与 lease，并配合存活 token log。

蓝色实线为 KV 通路，深色虚线为控制／元数据，红色虚线为 retry；图中两 DP 都可作为另一 DP 的 Peer。Engine 分区是职责归属，不是单一物理故障域。共享 DRAM／storage 和控制状态必须在声明的 source 故障后可访问。

物理对象包含某层某 TP shard 的封闭 token block。对象身份包括模型／权重、前缀与位置语义、布局等；共享物理字节只计一次。64-token 只是现有轨迹实验粒度，稀疏选择单位、kernel tile 和存储 block 不必相同。

Prefill 封闭块后提出完整 checkpoint 扩展；decode 每配置 Z 复核，另响应到达、工具切换、显著需求／Slack 改变和压力。M 为最近完整提交前沿，有复制滞后时 N 可超过 Z。DRAM manifest 的**全部**历史层／TP shard／selector／log 依赖都在 DRAM 中；Shared storage 的 manifest 同样完整。增量复制和不可变共享可以省字节，但不能将“部分热块在 DRAM、其余在 storage”称为完整 DRAM checkpoint。迁移中旧完整副本保持权威，直到新完整副本提交。

### 3.3 Workflow Tracker: Remaining Time and Slack

**先介绍 GBDT 预测什么、能看到什么，再把预测传到 DAG。** 预测目标是剩余执行时长，不能对已预测的剩余量再次扣除 elapsed time。输入分为三组：角色／模型和当前输入长度；已运行时间与完成调用数；完成调用的输出长度、API 时长、上下文增长及调用间隔。任务语义和工具类型可由 orchestrator 额外提供，但当前 trace 并没有这些字段，不能画成已有实证。未来调用数、当前调用的最终输出长度和未返回的工具结果都不可用。

![可观测因素与 Agent 剩余运行时间的相关性](figures/preview/tracker-correlations.png)

**本图放在 GBDT 特征定义之后，展示观测依据和局限。** 现有 CC/Weka 数据中，1,443 个 Agent、170 个 workflow，每个 Agent 仅在第 2 次请求到来、第一次调用已完成时取一个样本；目标为整个 Agent 从此时到结束的剩余秒数，包含后续调用和间隔。横轴为 Spearman 相关系数，误差条为 2,000 次完整 workflow bootstrap 的 95% 百分位区间。输入长度与上下文增长使用 64-token hash-prefix 代理。六项相关性分别约为：elapsed +0.060、当前输入长度 −0.081、上下文增长 −0.121、前次输出长度 +0.066、前次 API 时长 +0.084、前次调用后间隔 +0.056。全部区间跨过零；保留这一弱结果。单变量相关不是 GBDT 的 feature importance，也不代表准确率，更不能据此验证在线 residual-segment 的预测目标。

**下半增加既有按 workflow 分开的五折预测的绝对秒数误差 CDF，保留全部尾部，横轴 1 秒以上为对数刻度。** Median baseline、basic GBDT、history GBDT 的 MAE 分别为 438.6、406.7、407.1 秒，P50 APE 分别为 76.2%、67.1%、69.3%。配对整 workflow bootstrap 中，basic 减 median 的 MAE 差值 95% 区间为 [−80.9, 4.9] 秒；仍不能确立可靠的平均误差改善。Basic GBDT 只有 36.5% 的样本误差在真实剩余时间的 50% 以内。增加历史特征没有稳定改善，不能把“存在多个特征”写成“GBDT 已经准确”。本轮仅复核和重绘既有预测，没有重新训练或新增 GPU 实测；区间也没有包含重新训练的不确定性。

当前标签包含 Agent 之后的全部调用与间隔，少数样本跨越数小时，仍保留在 CDF 中；数据只覆盖已经完成的 subagent，不是在线 residual segment 的有效性验证。未来验证须按完整 workflow 和时间隔离，同时报告错误预测正 Slack 的比例。没有经过验证的 segment 预测时使用零 Slack fallback，不能把本 pilot 的点预测直接当成安全降级余量。引用的 trajectory 预测论文是方法背景，不能替代 AegisKV 的秒数预测证据。

父任务按 fork/join 切成执行段，避免把子任务执行和父任务等待重复计算。CPM 的正反向遍历产生 segment Slack，同段多个请求共享该余量。缺失依赖或无效预测采用零 Slack，并按恢复代价及正常复用保守排序；DAG 更新发布新版本，使旧估值快照失效。正文唯一的 Algorithm 1 属于后面的 KV Master；这里用文字和相关性图解释预测，不引用不存在的 Tracker 算法列表。

### 3.4 Recovery-aware Router

正常路由考虑 Agent 前缀亲和和负载。请求到来时，Router 绑定处于独立故障域、布局兼容的 takeover DP，KV Master 在这个目标上放置 Peer 热块。故障后 fencing 旧 epoch，读取完整 manifest 并激活绑定目标；目标不可用时选其他兼容 DP，通过完整后备恢复，不把原目标 Peer 字节算成新目标本地命中。重绑定使用新版本，可以先以 Peer coverage=0 发布完整后备路径，再逐步建立新 Peer 副本。

请求结束或进入工具调用时，释放执行引用与该请求的逻辑 Peer pin；完整缓存历史仍保留正常复用价值，Peer 副本进入可淘汰候选，并不立即删除。

![同 Agent 与跨 Agent 前缀复用](figures/preview/agent-prefix-reuse.png)

**本图已恢复到 PDF 的正常路由段，保持单栏，解释为什么保留 Agent 亲和有价值。** 98,827 个请求、2,090 个 Agent、393 个 workflow 的前缀分析中，同 Agent 可覆盖 97.90%，其他 Agent 为 10.06%；二者重叠，其他 Agent 的额外覆盖仅 0.37%。这是相同 workflow／模型下更早完成请求的潜在 token 前缀复用，不是实际缓存命中率，也不能泛化为跨 workflow 共享比例。

正确恢复还要求确认输出前保留存活 token log，恢复 prompt 与工具输入，防止旧 epoch 回调和重复输出；外部工具副作用的 exactly-once 由 orchestrator 负责。

### 3.5 KV Master: Three-Tier Placement and Direct Revaluation

#### 3.5.1 Full-checkpoint placement and Peer admission：完整后备与额外加速分别决策

不再给一个请求永久赋予 R/D/P 三选一标签，而是分开三个后果：**完整 checkpoint 在 DRAM 还是 storage；哪些块值得额外放入 Peer；最后一份可恢复副本是否必须删除并回退。** 大 Slack 不禁止正常缓存。新封闭状态优先提出完整 DRAM 扩展，放不下考虑完整 storage 扩展；可复用依赖只引用／增量写入。两层都无法安全接收时，旧 M 仍有效，N 继续增长。

Peer 是可选加速副本。只有已经属于完整、已提交后备 manifest 的对象，才能作为 Peer backup 对外发布。后备可以在 DRAM，也可以整份降到 Shared storage；降级后必须按真实 storage miss 路径重新估计 Peer 收益，不能沿用旧 DRAM 成本。

完整计划代价变化为：迁移及暂时占用对正常服务的影响，加上声明时间范围内正常复用／共同故障情景的 WCT 变化。各情景权重是概率或期望次数，而非无时间范围的 failure rate。共同 source 故障影响的请求一起传播到 DAG：两个必要分支都晚 10 秒，只把一个加速到 2 秒，join 仍晚 10 秒，不能把单块收益相加。逻辑 owner 的成本都计算，物理副本的容量只计一次。单独撤销不能释放物理字节的 manifest 不作为腾挪对象，除非合法地联合撤销相关 owner。

![Slack 优先级为什么不够](figures/preview/retention-value.png)

**此图用于解释价值／容量的必要性，参数保持原构造。** 独立故障下，A 占两单位、恢复 4→2 秒、Slack=0，收益密度为 1；B 占一单位、恢复 18→8 秒、Slack=6，收益密度为 10。只按 Slack 排序会反转选择。正常复用暂设为零，不能将此例解释为硬件结果或最优性证明。

#### 3.5.2 Choosing per-request layers and hot blocks：L/K 如何随请求变化

**L_r 是该请求在 Peer 中覆盖的前缀层数，K_{r,l} 是其第 l 层实际复制的引擎 token block 数，每个 block 包含所需的全部 TP shard 对象。** L/K 只描述 Peer，不表示 DRAM 中只保留这些块；DRAM checkpoint 完整。热集包括该候选所需的原生必需块与选择器状态，其他位置按因果访问摘要排序，模型的原生 attention 选择不改变。

KV Master 在配置的决策预算内枚举若干前缀 L、逐层 K／热集，包括 L=0 和当前方案。对每个候选，按当前 M、未知 N 的声明分布或界、需求揭示、H2D／storage、回放计算和有限工作区估算真正暴露的等待，再与其全部受害者共同进行 DAG 价值重估。有限候选及跨分支小束只能覆盖部分互补关系，不保证全局最优。

上下文增长不意味着每个 token 都必须调整 L/K。固定 sparse budget 可以使 K 不变而具体块身份变化；比例预算可能使 K 增长，但 Peer 准入仍可截断数量。每个 Z 的复核和重要事件触发重新决策；未完成的热集替换是 pending，不能被算作已经驻留。即使 Slack=0，当传输已经完全被遮盖时也可以选择 L=0。

![完整 checkpoint 与选择性 Peer 副本](figures/preview/sparse-recovery.png)

**本图直接解释三层容量语义。** 三层历史 B0–B3 全在 DRAM，虚线尾部尚未提交；Peer 仅存前两层 B0/B3（L=2、每层 K=2）。Layer 1 实际需要 B0/B2 时，B0 使用本地 Peer，B2 从完整后备补取；B3 是未用预测。完整 DRAM 可整份降到 storage，不改变原生选择，也不把热集当作完整历史。

![Peer 相对于完整 DRAM 的层位置收益](figures/preview/recovery-pipeline.png)

**本图为匹配条件的增量分析。** 同样四层需求、同样完整 DRAM，每层一个等大小需求组，H2D=4 ms／组、仍需计算=3 ms／层，time 0 准确知道全部需求，独立临时工作区可容纳四组。无 Peer 为 19 ms；相同一个组的 Peer 容量给第 4 层为 18 ms，给第 1 层为 15 ms。晚层是分析反事实，不是 Master 的前缀层策略。条内数字为层号；这些是构造的速率和调度，不是实测，不包含准入干扰。

![请求画像决定 Peer L 的边际收益](figures/preview/overlap-frontier.png)

**本图回答为什么 L 按请求调整。** 每层 K=1，计算分别固定为 1/3/6 ms；每条曲线的 L=0 都是自己的完整 DRAM 对照。更长剩余计算能掩盖更多后续传输，因此有用 L 可能更小，但总恢复时间可能更大。平坦区表示继续占 Peer 没有额外时间收益；这不表示故障相位分布，也不推出 Z 与 L 的普遍单调规律。

#### 3.5.3 Online admission, direct revaluation, and eviction：完整算法流程

每次用一个带版本的 DAG、绑定、M、需求、有效副本、队列、lease 和容量快照。缓存估值仅在依赖未变化时可复用。当前主策略没有 rent level、credit 或 renewal；租金的负结果保留为替代方案，不改名成主策略的证据。

准入与淘汰的粒度按层区分：DRAM／storage 以完整 checkpoint manifest 为候选和受害者；Peer 以合法层／热块束为候选。共享 checkpoint 被淘汰后，只能释放其他保留 manifest 不再依赖的物理对象。运行中请求的 Peer 热集带逻辑 pin，普通其他请求不能抢占；自己热集替换和 Adapter 容量回收可解除该限制，但始终不能跨越实际 reader／copy lease。

对一个候选，从按稳定身份轮转扫描的有限安全受害者集合中，逐步挑当前完整计划额外损失／实际释放字节最小者；每加一个受害者就重新估值，直到腾出候选和工作区所需空间或工作预算耗尽。DRAM 降级需要 storage 空间；若下层也满，连同下层受害者和有效 fallback 一起规划。最后仍用完整候选＋全部受害者通过 DAG 比较，不能把评分比例当成可加收益。

![直接重估完整 Peer 替换计划](figures/preview/placement-competition.png)

**图中 x、y、z 可解释为同大小且有完整后备的 Peer 束，y/z 没有运行逻辑 pin。** x 收益 6、y/z 损失 2/5、迁移代价 1，完整变化为 −3/0。Reader lease 的对象不可用。该可加示例仅解释候选比较，真正共同故障需要完整 DAG。

**Algorithm 1 与英文稿一致：**

1. 事件到来，取得版本、复制、队列与物理字节快照。
2. 更新 M/N、因果需求和价值，复用已有对象。
3. 读取 Adapter 容量；需缩容时构造安全的当前损失最小回收计划。
4. 否则在预算内构造完整 checkpoint 与 Peer L/K 候选。
5. 为每个候选逐次重估受害者，纳入下层腾挪与 fallback；不可行则跳过。
6. 用完整 DAG 比较，保留改善超过不确定性余量和迁移滞回门槛的最低代价方案。
7. 没有合格方案则保留完整后备，压力下暂停新准入。
8. 重验版本，预留可立即执行的空间，依赖执行复制／提交／重定向／排空／释放。
9. 成功或失败回调更新真实状态，再触发新快照。

门槛未单独校准时只是启发式 guard，不是统计置信界。强制回收可以接受正代价；画像失效时冻结可选提升，必要回收使用同安全协议下的有界 LRU。工作预算包含候选、受害者、画像、DAG 遍历，不拿旧实验的 scalar check 充当实际 CPU 时间。

### 3.6 Adapter: Windowed Peer Capacity

Adapter 观察正常执行需求、预留工作区和近期压力，为下一时间窗口设定 Peer 总预算：取“配置上限”与“受管理 HBM pool 扣除正常推理分配和 headroom”中较小者，再截断为非负。正常推理分配包括活跃状态与近期需求，不再次扣掉 Peer 造成双重记账。上限可以用 pool 的配置比例表达；**不固定窗口秒数，不调整 L/K，Z 仍是系统配置。**

目标缩小时，先停止超预算的 Peer 准入，由 Master 按当前完整方案损失选择回收。允许回收运行请求逻辑 pin 的 Peer 加速副本；其完整后备必须仍有效。逻辑 pin 不等于物理 read lease：旧读者和复制必须排空才真能释放。已经有有效不可变 DRAM／storage 副本时，无需重复 D2H；后备失效则先修复或发布合法 fallback。新目标不是已释放容量，紧急压力可在窗口内触发同样回收；lease 阻止立即释放时须 backpressure。

### 3.7 Connector: Committed Copies and Layered Recovery

Connector 依据 Master 计划管理真实预留、带宽份额和有界复制队列；需求恢复优先于同份额内推测预取。新封闭状态先推进完整后备，Peer 只发布已有完整后备覆盖的对象。复制、Peer 占用及重绑定的前台成本必须计入，不声称零开销。

![完整提交、整份降级与 Peer 回收](figures/preview/checkpoint-lifecycle.png)

**此图放在执行协议中，区别三种状态。** (a) 复制 129–192 未完成时 M 仍为 128；所有层／TP／selector／log 依赖提交后才到 192。(b) DRAM 整份降级遵守 copy→verify/commit→redirect→drain→free，部分写入不能使源 checkpoint 可回收。(c) Peer 释放先确认完整下层后备，再重定向并排空读者，不需重复写已存在的块。图说明顺序，不是故障注入实测。

存储最后一份 checkpoint 删除必须另行发布完整旧 checkpoint 或 prompt＋token-log 的重算路径；不再由完整后备覆盖的 Peer 副本必须在同一转换中撤销并退役，剩余热块不能冒充完整 checkpoint。迁移中的重复副本、保留字节和工作区都计费；写完成不自动等于后端持久化。重复回调、旧 epoch、复制失败不能推进 frontier。

恢复先取得完整 manifest／绑定／lease。目标本地 Peer 命中免 H2D；被执行接管的对象从 Peer 转入执行字节账本，不重复计费也不释放实际地址。缺失块从 DRAM 获取，若后备已降级则 storage→H2D；逐层预取与仍需计算的尾部重放重叠。真实原生选择 miss 必须补齐，dense 层用完整需求，缺失 selector 先恢复／重建。TP collective 和 batching 不改变原生语义；prefill 失败也从最近完整前沿（可能为 0）恢复。

### System Design 图像的证据分工

| 图像 | 支撑什么 | 不能据此声称什么 |
|---|---|---|
| 原生预测覆盖 | 因果历史预测部分未来原生需求 | Peer 故障恢复／WCT 实测收益 |
| System Overview | 三条职责层与三种保护介质、复制端点 | 完成实现或贡献充分 |
| Tracker 相关性与误差 | 已有弱关联及大误差，需保守 fallback | segment Slack 已准确 |
| Agent 前缀复用 | 同 Agent 潜在复用很高 | 实际 runtime hit rate |
| Retention value | Slack 单独不足以排价值／容量 | 最优或直接重估实测优势 |
| Sparse recovery | 完整后备与 Peer 子集的关系 | 预测总是准确 |
| Recovery pipeline | 同完整 DRAM 下 Peer 层位置效应 | 实际队列／带宽收益大小 |
| Overlap frontier | 固定画像下不同有用 L 与饱和 | 未知故障相位下统一最优 L |
| Placement competition | 完整候选与受害者比较 | 通用可加性或全局最优 |
| Checkpoint lifecycle | 完整提交、迁移和释放顺序 | 已经过真实故障注入 |

## 4. Evaluation

**三层恢复后的证据界限。** 现有 DRAM／storage 结果保留为 Peer-disabled 配置；独立 layer model 中部分 DRAM payload 驻留是 I/O 机制反事实，不符合本版“完整 DRAM checkpoint”放置粒度，不能当成完整主策略结果。新增 Design 曲线为匹配完整 DRAM 的 Peer 分析。17 小节／8 核心图的旧数据没有改写成新控制器验证。


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

消融矩阵包括：无DAG/Slack、joint source-event改为isolated sum、无normal reuse、无failure value、frozen placement、租金替代direct revaluation、租金变体无renewal、主策略无hysteresis、recency替代causal sparse history、serial替代bounded layer overlap、locality-only替代load-aware router，以及singleton与bounded-pair候选。每项保留同样安全覆盖、预算与原生attention。

![value-ablation](figures/preview/eval-value-ablation.png)

当前合并消融图将六种策略的 failure penalty 与 normal next-use cost 并排，使用 storage=4GiB/s 下同一组12个size/slack配置（36配置CDF的一个子集）；两类成本不能相加，均值口径不能混用。该图只评价static value，其余机制不能借这两个图声称已被完整验证。共同失败反例显示候选存在互补性，必须整方案revalue；增加pairs时同时报告oracle regret和控制成本。

四组2×2交互：DAG×joint-fault、sparse rank×overlap、租金替代方案×hysteresis、load-aware route×shared-link contention。四个cell同campaign配对，interaction=(Y11−Y10)−(Y01−Y00)，不能把独立speedup相加。安全协议不做“关闭后更快”的有效性能基线。

### 4.9 稀疏需求与layer overlap的解构

八层模型，每层full selected payload的SSD4ms、H2D1ms、compute3ms；DRAM同样容纳两层payload，staging最多当前+下一层。early/late placement与serial/pipeline四格保持同需求。改变selected-density时所有策略一起变，不允许为了cache策略更好而改变native attention。

![layer-factorial](figures/preview/eval-layer-factorial.png)

full demand下两个serial都56ms，late-pipeline34ms、early-pipeline32ms；所有case required compute都24ms，差别来自exposedwait。错误prefetch消耗额外读、真实需求等reveal才读；当前correct-prefetch比例是人为输入，正确位置按层序指定，不是学习器准确率。

原生实验捕获held-out retry的per-layer demand union与reveal时刻，用此前历史预测；按workflow/document分训练验证，不按blocks拆分。equal physical bytes、mandatory sink/window和coverage保持一致，报告all-layer coverage、unused/miss bytes、reveal-to-ready、GPU stall、workspacepeak、total replay和WCT。早期层100%命中不等于全部层100%。

**新增三层配对实验（待执行）。** 固定完整 DRAM/storage 覆盖、fault ID、原生 demand 和恢复调度，比较 Peer=0、同容量 recency/frequency、固定 L、逐请求 L/K，并做 Peer 位置×overlap 四格。使用同一物理 HBM pool，记录被 Peer 挤出的正常服务、跨 DP 复制和所有临时容量；扫描 M、真实 N、Z、热集漂移和 target rebind，联合报告增量 WCT、正常吞吐和传输字节。本地 HBM reuse 微基准不能替代该实验。

### 4.10 直接价值重估与租金替代方案

当前选择直接价值重估为在线策略，租金保留为被比较的替代方案。独立 tier 模型含 8 slots、24 个等大小对象、512 次确定性机会，所有策略共用时变价值与 visit/next-use 序列。Direct value 按当前价值选受害者，trial rent 按历史 credit 选受害者；之后都做当前替换收益比较，使用相同迁移门槛。该比较是可加模型里的 scalar difference，不是完整 workflow DAG 计算。

![rental-cost](figures/preview/eval-rental-cost.png)

Direct 迁移 108 次、trial rent 106 次；两者均进行 396 次替换价值比较。累计未命中＋迁移代价分别为 462.96 与 506.39 个抽象 cost units，不能解释为实测秒数、扣租总额或 CPU 时间。去 hysteresis 的租金变体迁移 121 次；去 renewal 的变体虽然只迁移 77 次，代价升到 526.05。保留这些负结果，但它们没有验证新直接重估控制器的端到端收益。

真实验证需要重放上下文增长、平滑漂移／突变、tool handoff、容量压力与 lease；对主策略记录版本失效、候选和受害者评估、完整 DAG 遍历、拒绝计划、预留／释放字节、迁移、CPU 和 WCT。对租金对照额外记录 trial/committed rent 与 renewal；这些字段不是当前主控制器状态。全部策略保持相同安全协议和工作预算。

### 4.11 容量、I/O和有限可靠覆盖

DRAM/unique-working-set为0/0.1/0.25/0.5/1，storage为0.5/1/2；shared物理对象按actual replica计费，reserved/retiring/metadata也计入。小storage要真实触发last-copy eviction，不能靠无限SSD假设掩盖fallback。All-DRAM只有参考地位。

![capacity-frontier](figures/preview/eval-capacity-frontier.png)

容量曲线中fault-only penalty可以不单调：oracle在16→28GiB时，joint score从0.15049降至0.14383s，但fault penalty从1.6125升至1.9458s，因为normal reuse也进入目标，且传输共享资源。对应resident对象和两个目标保存在capacity-objectives.csv，不能混称“oracle变差”。

测read/write/同时读写、不同IO粒度、并发、NIC/H2D、client与server cache。Direct IO只控制client路径；DPC或sharedFS server cache未知就保留未知。加storage slowdown/loss，对比真实可恢复coverage，不将低预测latency当状态可用性的证明。

### 4.12 预测、stale profile与fallback

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

执行顺序：正确性/后端校准 → 单次故障主结果及关键路径/队列分解 → 正常开销 → 关键四格消融 → 连续真实trace → 压力/预测/扩展性。当前两个必须面对的研究问题是 **静态workflow优先级的队列尾部回归** 与 **直接重估在完整在线控制器中的成本与效果**；后续实验应解决或缩小这些主张。

### 4.17 图像配置与数据替换

图像宽3.33465in，固定物理字体和边距，PDF/SVG/PNG三种导出；输入CSV与独立visual spec。数据换成实测后，保留同坐标、单位和layout；负值、timeout和尾部不能删。`prepare_measured_figures.py`检查原始物理日志hash、aggregationcommand、campaignunit及sampleaccounting，支持只替换已有实测的图；未测图继续保留原证据标签。理论结果解释与caption不会因换了CSV而自动获得实测含义。

## 5. Related Work

DéjàVu、GhostServe 和 RaidServe 已分别研究 KV 复制／编码及 TP 故障恢复；LUMEN 已研究 load-aware checkpoint 与恢复分配。Mooncake、CachedAttention、Strata 和 HCache 已研究分层复用、传算重叠、存储布局或其他状态表示。Parrot、KVFlow、Pythia、Cortex 与 TOPAS 已使用工作流信息优化正常执行。特别是 TOPAS 已结合 remaining service path、reuse 和 movement cost，因此“Slack 加缓存”不足以支持新颖性。

本稿把拟议差异限定为：共同故障域对多个请求的联合影响，正常复用与恢复保护共存，Peer 加速、完整 DRAM demotion 与 last-copy deletion 的不同后果，以及异步迁移时有效 checkpoint 的保持。完整原始来源和对应实验要求见 [RELATED_WORK.md](../experiments/eurosys27/RELATED_WORK.md)。这些差异需要实现与消融证明，而非由命名或架构图自动成立。

## 6. Conclusion

AegisKV 将 KV 保护视为有限 Peer HBM、DRAM 与共享存储中的在线工作流资源管理：完整后备保证恢复路径，逐请求 Peer L/K 提供额外加速。它保留普通复用，按依赖评估共同故障，并将期望放置与实际提交状态分开。理论分析给出了可能有价值的区域和明确限制：DRAM 容量充裕、storage 较快、预测偏差或共享队列都可能使收益变小。新版完整论文、模型与图像已经形成可复算的研究草稿；能否成为有竞争力的 EuroSys 系统论文，仍取决于协议实现、强基线和真实配对实验。

## 附录 A. Motivation 测量协议

**配置与测量层次。** Figure 1(c) 与 Figure 2 使用同一固定版本的 Qwen2.5-7B-Instruct-1M 权重、SGLang 0.5.10rc0、PyTorch 2.9.1/CUDA 12.8、BF16、TP2、batch 1，以及相同型号的两张 A100 PCIe 40 GB。Figure 1(c) 来自一次分配，Figure 2 来自另两次分配；正文“同配置”不表示同一个节点或同一次运行。MInference vertical/slash 参数、模型/注意力源文件与 SM80 内核哈希匹配。GQA 共享 K/V，前缀每组最多两个 query heads，单 query 合并全部 heads；这属于带适配与计时的 worker 微基准，不是未经修改的 serving 前端吞吐实验。

**统一终点。** C=M+1。Full Prefill 从空 KV 按至多 8,192 tokens 分块计算 M，再单独处理一个 token；复用路径使用相同稀疏生成的历史（含不完整页）。同步 wall time 取两个 TP rank 的最大值，终点为模型主体完成、全部 C-token KV 驻留，输出词表投影在外。模型加载、备份创建及校验不计时，也没有检测、路由、服务排队和故障注入。

**恢复路径与缓存。** DRAM 先把所有历史层从 pinned buffer 拷到 HBM，再计算。共享存储先打开、读取并关闭计算节点 DPC 文件系统上的逐 rank KV 文件，再执行相同 H2D 与计算；三个阶段串行，无压缩或选择性加载。1.01M 历史为 57,917,382,656 个逻辑字节，文件另有记录的对齐填充。O_DIRECT 与 mincore 检查排除 Linux 文件页命中；DPC 服务端/内部缓存不可控，不能称为冷 SSD 或纯介质延迟。共享 KV 已在测量后清理，本次 Figure 2 补测不创建存储 KV 文件。

**样本与预热。** Figure 1(c) 的作业 1517208 测四个长度：8,192、65,536、262,144、1,010,000。HBM/DRAM 预热一次、正式计时三次；Full Prefill 和 Shared storage 各一次。计时前有短 forward 与算子检查，64K 另有完整原生 all-head 稀疏参考；256K/1.01M 没有重复完整 Prefill 预热，共享存储没有读取预热。因此后两条曲线是单次运行结果，不是稳定延迟分布。Figure 2 在作业 1517915 中完成前三个长度；最后一个长度收到提前终止信号后，在作业 1517917 单独补齐。每个绘图点均取一次完整 Prefill 预热后的三次计时。中断点的部分计时完整保留但整组不用于绘图。重复的是同一输入的计时，不是独立工作流；min–max 不表示置信区间。

**校验与映射边界。** 检查完整历史哈希、最终 hidden、各层新 KV 和 greedy 输出，额外比较重复 Full Prefill 输出，并用 CUDA timeline 检查串行拷贝。它们证明被比较的稀疏路径状态匹配，不证明 dense 等价或长上下文任务质量。Figure 2 的长度是 active request 的 hash-block 代理，不是原模型准确 token 数或故障时已完成的 KV frontier；将其完整 Prefill 时间作为额外暂停插入原时序是一项明确假设。原例按四个分支、gap 约 100 s 选取，不能据此估计总体故障收益。

数据入口：[Figure 1(c) 原始实测](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1517208/measured.json)；[Figure 2 前三个长度](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1517915/measured.json)；[最后一个长度](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1517917/measured.json)；[分支映射与同配置核对](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/motivation-compact-cc/recovery-costs-measured.json)；[共享存储协议](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/SHAREDFS_PROTOCOL.md)；[共享 KV 清理记录](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1517208/sharedfs-terminal-cleanup.json)。
