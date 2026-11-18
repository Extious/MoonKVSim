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

本节围绕一个原则组织：**完整 checkpoint 保证可恢复，Peer 热块减少暴露等待，有限容量按正常复用和工作流恢复价值分配。** 保留 3.1–3.7 七个小节，以及七张各有独立论证作用的图。下面与英文正文保持相同机制和证据范围。

假设为 fail-stop compute-worker 故障，有兼容存活 DP；目录、token log 和完整后备位于被保护故障域之外。应用暴露已知 fork/join 依赖与已接受输入。普通执行 HBM、Peer 及恢复工作区分别计费；本机 SSD 不能自动覆盖整机丢失。模型原生 attention 和 replay 语义不变，外部工具副作用的 exactly-once 不由 KV 缓存提供。

### 3.1 Design Insights

**工作流价值与正常复用。** 恢复快不一定使 WCT 变短，需要看其影响的必要路径；但大 Slack 的 Agent 仍可能在工具返回后立即复用历史。因此区分“保留一份完整可用副本”和“额外支付快速介质的容量成本”，不把高 Slack 请求永久分配为重算。

**稀疏性提供加速机会，不提供完整性。** 原生稀疏注意力对历史 KV 的重复访问集中在部分逐层块上，为选择性 Peer 驻留提供机会。但窗口内集中不等于可以准确预测后续 Query，热集仍可能改变，因此未驻留块必须有完整后备和按需补取路径。

![三个模型在 32K 上下文、512-Query 窗口中的逐层 KV 访问集中度](figures/preview/kv-access-concentration.png)

**Figure 3 展示少量逐层热块承载较多重复访问，但集中程度因模型而异。** 使用 NOSA-8B、NSA-8B（实际 checkpoint 为 MiniCPM-4-8B-NSA）及 MiniCPM4.1-8B 的现有原生选择轨迹；每个模型包含相同三篇 PG19 文本。名义 32K 上下文统一为 32,704 tokens：前 32,192 tokens 是历史，最后 512 个 Query 是统计窗口；每层共有 503 个历史 64-token 块，块包含全部 KV heads。保持各模型原生 selector 及 sink/local 规则，不修改注意力选择。

每个 Query 对同一历史块跨 heads 去重，不同 Query 的重复访问分别计数。在同一文档、同一层的窗口内按频率回顾性排序，先计算该层累计访问占比，再平均全部 32 层，最后对三篇文本等权平均；阴影是文档 min–max，不是置信区间。约 20% 的历史块（向上取整为 101 块）分别承载 **87.64%、74.76%、56.54%** 的访问；约 40%（202 块）分别为 **99.31%、94.96%、83.01%**。虚线对角线表示均匀访问参考。

该图衡量的是**同窗口访问频次集中度**，不是以前一窗口预测下一窗口的命中率，也不是 attention mass、实际 HBM 流量或恢复加速。统计仅覆盖原始历史 KV 块，不含压缩 KV／selector 辅助状态；三篇长文本的 causal prefill 轨迹也不能替代多智能体工作负载验证。它支持“选择性 Peer 副本存在机会”的 insight；在线预测、热集变化和按需 miss 的代价仍需另行验证。原有预测覆盖率与 64K 对照数据保留在论文上传目录之外。

**层间重叠决定 Peer 的边际收益。** DRAM 已避免历史重建；Peer 进一步减少 H2D，但后层传输可能被仍需执行的回放计算隐藏。M、未知 N、需求揭示与队列决定请求自己的 L/K，Adapter 只给 Peer 总预算。

### 3.2 System Overview

![带黑色组件序号的紧凑三层架构](figures/preview/system-overview.png)

**Figure 4 用横向并列的 Controller 模块降低整体高度，恢复黑色编号。** 三条归属层仍为 Application、Controller、Engine。序号与正文对应：① Workflow Tracker，② Recovery-aware Router，③ KV Master，④ Adapter，⑤ Connector；DP1 与 DP0 有相同能力，不必重复编号。

Tracker 提供 GBDT→CPM／Slack；Router 在请求到来时绑定执行与 takeover／Peer DP；Master 负责完整 D/S checkpoint 与 Peer L/K 的联合估值。目录维护 manifest、token log、lease 和绑定。每个 DP 的 Local KV 与 Peer HBM 分区并存，橙色块示意未封闭尾部；Connector 连接对端和共享 DRAM／storage。蓝色为 KV 通路、深色虚线为控制、红色虚线为 retry。资源图是部署与职责示意，不是容量比例测量。

物理对象包含一个封闭 token block 的某层某 TP shard，身份含模型／权重、布局、精度、位置与前缀语义；原生稀疏选择、存储块、kernel tile 不一定相同。完整 checkpoint 要求所有历史层、TP shard、selector 与 token-log 前沿匹配。DRAM manifest 的全部依赖在 DRAM；storage manifest 同样完整。增量写入和共享对象只省重复字节，不降低完整性要求。

Prefill 封闭状态后提议扩展；decode 每固定、块对齐的 Z 复核，并响应到达、工具切换、显著需求／Slack 变化及压力。复制落后时尾部 N 可以超过 Z。只有已有完整、已提交后备覆盖的对象才能发布为 Peer backup；pending 不能推进 M。

### 3.3 Workflow Tracker: Remaining Time and Slack

**预测对象。** Segment 是 Agent 在已暴露的 fork/join 边界或完成之间的顺序执行段，可以包含多次 LLM 调用和工具等待。父 Agent 等待子任务的时间由子路径承担，不能再次算进父节点；已完成工作删除，尚未释放的执行段保留前驱约束，未知未来分叉不伪装成已知依赖。

GBDT 预测“从当前快照到本 segment 结束的剩余秒数”。特征为角色／模型、当前输入长度、segment 已耗时、已完成调用数以及此前输出长度、API 时间、上下文增长和间隔；缺失值有 mask。未来输出、工具结果和调用总数不进入特征。训练标签来自快照到记录的 segment 终点的时间，训练／校准／测试按完整 workflow 隔离；跨嵌套 fork 的整个 Agent 完成时间不是同一个标签。预测 remaining 后不再减 elapsed。

**从时间到 Slack。** CPM 前向计算 earliest finish，反向从预计 workflow 终点计算 latest finish，两者非负差为 nominal Slack。一个 segment 的多次请求共享同一余量；Master 用整个 DAG 比较计划，不能把这些 Slack 独立相加。

![剩余执行段预测、Slack 推导与更新](figures/preview/tracker-slack.png)

**Figure 5 解释机制，不宣称预测精度。** 构造例子中 B/C 剩余 6/10 秒，汇合后 D 为 2 秒，workflow 预计 12 秒结束，因此 B/C 的 nominal Slack 是 4/0 秒。将 B 预测刷新为 11 秒后，B 成为关键分支，C 留 1 秒余量。粗边框表示初始关键路径。新 graph/model 版本使旧放置估值失效；数字不是实测预测输出。

**误差处理。** 模型 bundle 包含支持范围、版本、最大有效时长与校准 guard。Guard 取隔离校准集上 Slack 正向高估的上分位数，nominal Slack 减 guard 后裁到零；它是经验调度余量，不是逐请求概率保证。Master 接收原始剩余时间和 guard 来做联合评估，不能把裁剪后的 Slack 再计一次延迟。缺少有效依赖、校准或输入支持，或者预测过期时，标记无效，Master 改用正常请求／恢复请求代价，不赋予正 Slack 收益。

请求到达／完成、工具返回和依赖变化触发刷新，长调用通过周期刷新限制估计年龄。两遍 DAG 传播为 O(|V|+|E|)，另加 GBDT 推理；错误预测影响效率，不决定 checkpoint 完整性。实际精度、false-positive Slack 和 fallback 比例在 4.12 验证，旧相关性／误差结果移入该节说明与外部诊断材料，未删除或美化。

### 3.4 Recovery-aware Router

正常路由同时考虑负载与前缀亲和。请求到来时绑定布局兼容且故障域分离的 takeover DP，也是 Peer 对应 TP shard 的位置。工具切换释放执行引用及该请求逻辑 Peer pin，但不删除可复用的完整历史。

![同 Agent 与跨 Agent 潜在复用](figures/preview/agent-prefix-reuse.png)

**Figure 6 支撑保留 Agent 亲和。** 98,827 请求、2,090 Agent、393 workflow 的 prefix-hash 分析：同 Agent 潜在覆盖 97.90%，其他 Agent 的额外覆盖 0.37%。交叉覆盖本身有重叠，首个 subagent 调用也可能受益；不是 runtime cache-hit rate，也不禁止跨 Agent 共享。

故障时 fencing 旧 epoch，解析完整 manifest，按准入与工作区约束激活绑定 DP。目标失效可重新绑定并先发布 Peer coverage=0 的完整后备路径；原 DP 的 Peer 字节不能算成新 DP 本地命中。确认输出前存活日志记录 request、token position/value 和 epoch，prompt 与工具输入也可恢复；重放抑制重复输出与旧回调。重绑定在新路径有效前保留旧权威路径。

### 3.5 KV Master: Three-Tier Placement and Direct Revaluation

#### 3.5.1 Full-checkpoint placement and Peer admission

决策区分完整历史的驻留层和额外 Peer 加速。Checkpoint 事件先提议完整 DRAM 扩展，不可准入时考虑 storage；必要时降级或淘汰旧 manifest，只复制缺少的不可变物理对象。两层都不能接收完整扩展时 M 保持、N 增长。候选还包括 storage→DRAM 提升、整份 DRAM→storage 降级、带重建 fallback 的最后副本删除、Peer 热集替换和保持当前状态；大 Slack 不禁止正常复用，强制容量回收另行处理。

完整计划比较为各 continuation 场景中 workflow 剩余完成时间变化的加权和：ΔJ = Σ p_e Σ_w [T_w(P′,e) − T_w(P,e)]。场景表给出无故障正常延续，或同一延续中某 source-domain 在指定偏移发生一次故障；概率和为 1。场景、时间范围和从可见历史预测的 reuse 事件在候选间冻结，不把 failure rate 直接当概率。

所有候选从同一队列与 coverage 快照开始，以 Connector 的服务顺序、带宽／计算画像和有限工作区推演复制及执行；完整提交才能推进模拟 M，故障时刻决定模拟 N。资源模型得到相对普通执行参考的增量延迟，再进入 residual DAG 的 max-join 计算，已包含在预测里的正常计算不能重复加入。**复制干扰和暂时占用已影响这些完成时间，不再额外加一个缺少定义的字节价格或迁移项。**

每个故障场景向每个受影响 segment 只加一次 guard，再做联合 DAG pass；两个候选使用同样 guard，不按块／请求重复累加。单分支时相当于减少可用 Slack，多分支由完整图决定。Timing model 无效则同一资源调度改为比较正常请求和恢复请求的完成延迟之和；资源画像本身无效则冻结可选提升。

共同故障影响的全部请求一起估值。两个必要分支都晚 10 秒，仅把一个缩到 2 秒，join 仍晚 10 秒，单块收益不能相加。DRAM 降级对比真实 storage miss，Peer 对比完整下层路径仍暴露的 H2D，最后副本删除对比旧 checkpoint／重算。后备降级还要重新估计其 Peer miss 成本。

![Slack 与单位容量收益](figures/preview/retention-value.png)

**Figure 7 删除图内标题并压低画布，保留论证最需要的反例。** A 用两单位容量使恢复 4→2 秒，Slack=0 时每单位节省 1 秒；B 用一单位使恢复 18→8 秒，Slack=6 时仍节省 10 秒／单位。正常复用暂置零；构造参数只说明 Slack 排序不足，不是硬件或策略实测。

#### 3.5.2 Choosing per-request layers and hot blocks

L_r 是 Peer 前缀层数；K_{r,l} 是第 l 层复制的引擎 token blocks 数，包含所需 TP 对象。热集先满足原生 mandatory 依赖，再按固定历史窗口内已完成 Query 的选择频率排序。同一 Query 多个头选到一个物理块只记一次，并列先按最近访问再按 block ID；小于 mandatory 集合的预算不可行。完整后备仍覆盖其他块与 selector，预测 miss 不改变模型原生选择。

![完整后备、不同层 K 与实际补取路径](figures/preview/sparse-recovery.png)

**Figure 8 增加具体层内预算和数据路径。** (a) DRAM 所有层含历史 B0–B3，尾部未提交；(b) 绑定 Peer 上 L=2，第 1/2 层分别 K=2/3，第 3 层无 Peer；(c) 第 1 层实际 demand=B0/B2，B0 命中 Peer，B2 沿明确的下层路径补取，B3 未用。底部注明完整 manifest 包含所有层和 selector，正文补充 TP／log 依赖；完整 DRAM 降级后，同一个 miss 经 storage 读取再 H2D。

候选由有限 budget templates 生成：每模板为每层指定固定块数或历史比例，遍历 L=0 到模型深度，剔除 mandatory 不可满足者；复杂度按“深度×模板数”增长，不枚举所有层 K 的笛卡尔积。当前方案始终加入。对 join 上并列瓶颈分支，还构造同模板下所有瓶颈分支同时增加到下一深度的小束，超过请求数上限则跳过；每次尝试计入共同预算。

使用当前 M，由每个故障偏移场景单独推导将来的 N，包括复制滞后超过 Z。因果选择统计给出预取与 miss 需求，稀疏画像不支持时用完整历史需求。只用仍需执行的计算覆盖传输；这是有界完整计划启发式，不声称全局最优。

![恢复删除 Peer 前的四阶段流水线](figures/preview/recovery-pipeline.png)

**Figure 9 恢复原始图及原始数值。** MiniCPM4-8B，32 层，32K history、64-token tail；每层 replay 2.870 ms 来自既有测量，H2D 有效带宽 6.25 GB/s 是模型假设，每层完整 KV 5.369 ms。既有 native 统计经文档／层均值得 preload=0.6584、preload+miss=0.7748。四路径 completion/wait 分别为 264/172、175/83、136/44、112/20 ms，最后在前 7 层放置 147.5 MiB Peer 热集。

(a) 明确使用等待整个历史装入的 bulk barrier；不能声称所有 token-block engine 都必然如此。(b) 全层传输与计算重叠；(c) 热块预取＋实际 miss；(d) 增加 Peer。**匹配增量是 (c)→(d)**：完整 DRAM 和尾部计算不变，约减少 24 ms 暴露等待，而非省去全部 44 ms。图是均质层、理想可抢占复制流的分析，没有有限 staging 或共享队列竞争，cold KV 在 tail 完成后继续搬；不是端到端测量，不是新的 1M 实测。

K 不一定随每个 token 增加：固定 sparse budget 可以维持数量而改变身份，比例预算可能增大，但 Peer 准入有容量上限。每 Z 或重要事件才复核，pending 热集不算已驻留。L=0 对零 Slack 请求也可能合理；前七层达到该例 demand-only floor 不代表通用 L。

#### 3.5.3 Online admission, direct revaluation, and eviction

快照包括 DAG／binding 版本、因果需求、完整 manifest、队列、lease 和物理字节账本。DRAM/storage 以完整 manifest 为候选／受害者，Peer 用合法层／块束。Safe set 排除 physical reader/copy lease；普通 Peer 竞争还排除其他运行请求的 logical pin。请求完成／工具 handoff 解 pin；自身热集替换及 Adapter 压力可以覆盖逻辑 pin，但不能越过物理 lease。

对每个候选，在按稳定 ID 轮转的有界集合中，选择“当前完整计划额外损失／实际释放字节”最小的可执行移除，逐步重估直到容量可行或工作预算耗尽。单独不能释放字节的共享 manifest 跳过，除非合法 owner bundle 能释放。DRAM 降级需纳入 storage 腾挪、复制和 fallback，不能假设下层无限。

最终比较整个候选＋所有受害者的 DAG 代价；比例只构造计划，不使收益变可加。可选计划要求 ΔJ < −ε，ε 是抑制抖动的秒数门槛，迁移成本已计入资源调度。强制回收没有 incoming candidate，在检查过的可行计划中选择成本增加最小者，允许正代价。无安全计划则暂停准入并保留 coverage。

**Algorithm 1：**

1. 快照 DAG／binding、manifest、需求、队列与容量，更新受影响成本，无效画像走 fallback。
2. 强制缩容则枚举安全回收计划；否则枚举完整 checkpoint／Peer L/K 候选。
3. 逐次加入并重估受害者，直至容量可行或工作预算耗尽；纳入下层回收、工作区和完整复制依赖链。
4. 用相同场景评估完整计划。强制回收选检查过的最低成本方案；可选优化仅接受 ΔJ < −ε 的最佳方案。
5. 无方案则保持原状，容量不足时暂停准入。
6. 重验版本，预留下一步真实可执行空间，版本改变或空间不足则重新规划。
7. 执行 copy→commit→redirect→drain→release，完成／失败后核实并刷新相关决策。

估值仅在依赖版本有效时复用，画像、victim 比较、DAG pass 都计入预算。资源画像过期则冻结可选提升，必要回收用同安全协议下有界 recency。主策略无 rent/credit/renewal，租金负结果留在 Evaluation。

### 3.6 Adapter: Windowed Peer Capacity

每窗口依据受管理 HBM pool、预计 serving 分配与 headroom，给出非负且不超过配置 cap 的下一窗口 Peer 预算。Serving 分配含执行状态与近期需求，不再次扣掉 Peer 造成双重记账。窗口／cap 可配置，Z 独立固定，Adapter 不设每请求 L/K。

缩容后在实际＋预留占用超标时暂停 Peer 新准入，Master 可按当前损失回收 logical pin 的加速副本。完整不可变后备有效时不重复 D2H；physical reader/copy 排空后才能释放。紧急前台压力可窗口内触发同协议；未释放地址不能重复使用，必要时 backpressure。

### 3.7 Connector: Committed Copies and Layered Recovery

Connector 实施预留及前台复用／需求恢复／checkpoint 的有界传输队列。配置份额和 quanta 限制干扰，恢复份额内实际 miss 优先于推测预取；复制与 Peer 占用仍是正常服务成本。

完整扩展需全层、TP、selector、log 同版本提交；完整 DRAM→storage 顺序为复制、后端持久化、manifest 提交、重定向、读者排空、源释放。部分写入、重复／旧 epoch 回调不能推进 M 或提前回收。临时重复副本和工作区也计容量，buffered write acknowledgement 不是持久化证明。

最后副本删除先发布完整旧 checkpoint 或 prompt＋token-log fallback，同时撤销失去完整 backing 的 Peer 声明。复制失败保留旧权威位置并核销失败预留；pending 不等于保护。

恢复取得 manifest、binding、lease；本地 Peer 命中免 H2D，缺失从 DRAM 或 storage→H2D 补取，与实际剩余计算逐层重叠。原生选择 miss 须齐备才执行，dense 层按全需求，selector 缺失先恢复，TP collective 与 replay batching 保持语义。被执行接管的 Peer 字节只转账，不双重计费；prefill 故障也从最近完整 M（可能为 0）开始。

**一次完整的三层恢复。** DP0 在新 checkpoint 复制途中失效，Router fencing 旧 epoch 并激活绑定 DP1；未完成副本忽略，Connector 对最后完整 manifest 和位置加 lease。完整 checkpoint 在 DRAM 时，Peer miss 走 H2D；若已整份提交到 storage，则先读取再 H2D；有效 Peer 热块仍可直接用。随后重放 M 后已确认 token、抑制重复输出并恢复 decode。DP1 工作区不足时排队或重绑定，新目标不能假设命中旧 Peer。

**正确性不依赖预测精度。** 三条不变量是：已公布 checkpoint 的 KV／selector／TP／log 完整且版本兼容；新权威 manifest 提交后才撤旧副本，删除最后副本先发布日志重建路径；物理内存必须等读者与复制依赖排空后释放。初始 log-only 状态满足它们，pending 不改变 coverage，验证后的 commit 推进前沿，重定向／排空维持回收安全，失败则保持旧权威状态。因此，在目录／日志存活的假设下，这些状态转换不会因为 Slack 或热集预测错误而接受缺失 KV。错误可以增加等待／重算，进展还需兼容目标和最终可用的计算／I/O 容量。

**图像取舍。** 原 Figure 10 层数曲线与恢复流水线重叠；原 Figure 11 替换算例与 Algorithm 1／价值反例重叠；原 Figure 12 生命周期由明确的提交协议文字覆盖。三图从上传目录移出并保留在归档，不再占正文或中文稿空间。Tracker 的弱结果和租金负结果未删除，也未伪造新数据填补证据。


## 4. Evaluation

**三层恢复后的证据界限。** 现有 DRAM／storage 结果保留为 Peer-disabled 配置；独立 layer model 中部分 DRAM payload 驻留是 I/O 机制反事实，不符合本版“完整 DRAM checkpoint”放置粒度，不能当成完整主策略结果。Design 恢复了原来使用 MiniCPM4-8B 校准和声明 H2D 速率的四阶段 Peer 分析图。17 小节／8 核心图的旧数据没有改写成新控制器验证。


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

既有诊断包含 170 workflow、1,443 个 request-2 Agent，标签是整个 Agent 剩余时间。五折 workflow-disjoint MAE 为 median/basic/history 438.6/406.7/407.1 秒；basic−median 的配对区间 [−80.9,4.9] 秒跨零，六个特征相关区间也跨零。这不能证明均值改善或 residual-segment Slack 准确。原始预测、全部误差尾部和诊断图保留在外部实验材料；Design Figure 5 只解释机制。

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
