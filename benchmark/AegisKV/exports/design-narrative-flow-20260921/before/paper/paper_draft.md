# AegisKV：面向工作流的 Peer HBM／DRAM／共享存储 KV 管理

英文完整稿与编译入口为 [main.tex](main.tex)，当前 PDF 为 [main.pdf](main.pdf)。本稿按最新决定恢复 **Peer HBM＋共享 DRAM＋Shared storage** 三层：Peer 为每个请求保存选定 L 层、每层 K 个热块；DRAM 中已准入的 checkpoint 保持完整，容量不足时可整份降到 Shared storage。主策略更新为**分层可续租信用＋当前完整计划检查**；Z 固定配置，Adapter 用有物理上限的 AIMD 只调整 Peer 总容量。既有 Evaluation 是明确标注的旧配置／子机制分析，不能据此声称新版三层控制器已经实测。

按 2026-09-21 最新要求，当前阶段取消 12 页压缩，以内容完整为先。Evaluation 保留 17 个完整小节，正文精简为 8 张必要单栏图，另外 26 张补充/备用图保存在实验包中；逐项实验规格、完整消融矩阵、trace 数据来源与可替换 CSV/绘图代码全部保留。图号以当前 `main.pdf` 为准。

## 1. Introduction

多 Agent 应用的用户等待的是整个任务完成，而不是某个请求单独完成。代码修改、并行检索和综合报告包含串行依赖、并行分支与汇合点；同样长的请求延迟，发生在不同分支上，对最终结果的影响可能完全不同。正常运行下的工作流调度和 prefix caching 已经利用这类信息，但故障提出了另一个问题：一个 worker 同时中断若干请求后，有限的快速恢复资源应该保护哪些上下文？

Agent 的多轮调用不断积累推理、代码和工具输出。失去 KV 后，重建长历史可能远比设备中断本身昂贵。KV checkpoint 可以避免这部分计算，但全部历史不能无限留在 DRAM。SSD 或共享存储提供更大容量，代价是读取、网络传输和排队。普通 LRU、单请求恢复速度、甚至单独的关键路径优先级，都不能完整描述这些权衡。

AegisKV 将共享缓存与故障恢复状态统一管理：**大 Slack 不禁止正常缓存；DRAM 降级与最后副本删除分别估值；同一故障域中断的请求共同经过 DAG 计算其影响。** KV Master 按真实复用续租、按竞争消耗信用，并在当前价值与完整计划检查下选择有限容量内的保留和迁移方案，引擎接口与传输路径在版本化 manifest、空间预留和 reader lease 约束下安全执行。Router 在请求到来时绑定故障域分离的 takeover／Peer DP，故障后激活；目标失效时退回完整 DRAM／存储恢复。

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

核心区分是：**完整 checkpoint 保证可恢复，Peer 热块减少暴露等待，有限容量同时考虑正常复用和工作流恢复价值。** 本节与英文正文保持七个小节、三个算法和八张设计图。假设为 fail-stop compute-worker 故障，有兼容存活 DP；目录、token log 和完整后备须在被保护故障域之外。应用提供已知依赖和已接受输入，外部工具副作用不属于 KV 恢复契约。

### 3.1 Observations

**Observation 1：恢复紧迫性与复用价值不同。** 更快恢复只有推进必要路径才缩短 WCT，但大 Slack 的 Agent 在工具返回后仍可能复用历史；反复重算会占用共享算力。因此，“是否保留完整历史”与“是否支付快速介质成本”是两个决策。

**Observation 2：稀疏访问提供选择性驻留机会。** Figure 3 展示采用 block、token 或 compressed-entry 选择的长上下文模型实例；Figure 4 进一步展示原生 KV 访问集中度。集中度不等于未来 Query 的预测准确率，Peer miss 仍需完整后备。

![稀疏／混合注意力模型的发布时间与报告上下文长度](figures/preview/sparse-models.png)

**Figure 3：长上下文模型中的稀疏访问形式。** 编号依次为 MiniCPM4、MiniCPM4.1、DeepSeek-V3.2-Exp、DeepSeek-V3.2、GLM-5、MiniCPM-SALA、DeepSeek-V4 preview、MiniMax-M3、GLM-5.2、LongCat-Flash-Lite-Sparse。横轴为公告日期或首次官方仓库日期（5、9、10），纵轴为报告的上下文档位；标记描述稀疏分支的选择单位，非全模型统一预算。它是选定模型的调查，不是采用率或稀疏率增长曲线；英文图注保留逐项来源。

![三个模型的原生历史 KV 访问集中度](figures/preview/kv-access-concentration.png)

**Figure 4：少量逐层块承载较多重复访问。** NOSA-8B、NSA-8B（MiniCPM-4-8B-NSA）和 MiniCPM4.1-8B 使用相同三篇 PG19 文本、32,704-token 前缀末尾的 512 个 Query。每个 Query 跨 heads 去重，对每层 503 个历史 64-token 块按窗口频次排序，先平均 32 层再平均文本；阴影为文本 min–max。约 20% 的块分别承载 87.64%、74.76%、56.54% 的访问。不含压缩／selector 状态，也不代表预测命中率或恢复加速。

**Observation 3：Peer 只值得消除仍暴露的传输。** DRAM 避免历史重建，Peer 进一步减少读取／H2D；后层传输可能已经被必须执行的计算隐藏。因此 L/K 取决于各请求的 M、N 和队列状态。

**Observation 4：复用价值跨请求延续，但会变化。** 工具等待后的调用应续租对应 Agent 的信用，共享前缀可叠加不同 Agent 的贡献；周期 checkpoint 仅重估价值，不能退还已付租金。租金承担容量竞争，完整计划重估处理依赖与迁移，不继承经典 Landlord 的竞争比保证。

### 3.2 System Overview

![Application／Controller／Engine 三层架构](figures/preview/system-overview.png)

**Figure 5：模块归属、物理资源和数据路径。** 保留单栏三层结构、黑色序号及对称 DP。① Tracker 预测时间与 Slack；② Router 绑定执行和 takeover DP；③ KV Master 选择完整后备、Peer 层／热块并管理信用；④ Adapter 控制 Peer 总额；⑤ Connector 执行传输。蓝色是 KV 通路，深色虚线为控制，红色虚线为 retry。Shared DRAM／storage 都保存完整 manifest，资源形状不表示容量比例。

物理对象是某层、某 TP shard 的不可变版本化 token block。完整 checkpoint 要求所有历史层、shard、selector 与日志前沿 M 匹配，完整依赖位于 DRAM 或 storage；共享对象在每个实际副本所在层只计一次容量。稀疏选择单位、物理块和 kernel tile 不必相同，64-token 仅是上述测量口径。

Prefill 封闭状态后提议扩展；decode 每固定、块对齐的 Z 复核，并响应到达、工具切换、需求／Slack 变化和压力。短轮次结束前封闭带有效长度及 copy-on-write 的最终 partial block，已接受复制持有源 lease 到完成。完整提交才推进 M，复制滞后时 N 可超过 Z；Peer 必须有完整已提交后备。

### 3.3 Workflow Tracker: Remaining Time and Slack

Segment 是 Agent 在已暴露 fork/join 边界之间的顺序执行段，可含多轮调用和工具等待；子任务耗时归入子路径，不重复计入父节点。GBDT 以当前角色／模型、输入长度、已耗时、调用数及此前调用的长度、时间和上下文增长预测 segment 剩余秒数。缺失值有 mask，未来结果不作特征；训练／校准／测试按完整 workflow 隔离。

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

G 是残余 DAG，d／g／s 是逐 segment 的时长、guard 和建议 Slack。Guard 取校准集上 Slack 正向高估的上分位数，是经验余量而非概率保证。Supported 检查输入、依赖、校准和时效；无效估计不提供正 Slack。进度事件和周期刷新使旧估值失效。两遍 DAG 传播为 O(|V|+|E|)；一个 segment 内请求共享余量，Master 联合计算其影响。预测验证留在 Evaluation。

### 3.4 Recovery-aware Router

正常路由兼顾负载与前缀亲和。请求到来时绑定故障域分离、布局兼容的 takeover DP，其对应 TP shards 也是 Peer 位置；故障时 fencing 旧 epoch 并按工作区／准入条件激活目标。重绑定保持有效完整后备，新目标默认 Peer coverage=0。

![同 Agent 与跨 Agent 潜在前缀复用](figures/preview/agent-prefix-reuse.png)

**Figure 6：Agent 亲和的依据。** 98,827 请求、2,090 Agent、393 CC/Weka workflow 的历史前缀分析中，同 Agent 潜在 token 覆盖为 97.90%，额外跨 Agent 覆盖为 0.37%。这是潜在复用，不是实际 cache hit；首个 subagent 调用仍可能受益于共享前缀。

工具切换解除执行引用与逻辑 Peer pin，完整历史继续参与缓存管理。确认输出前存活日志记录请求、token 位置／值和 epoch；prompt 与工具输入可恢复，重放抑制重复输出及旧回调。

### 3.5 KV Master: Three-Tier Renewable Credit

#### 3.5.1 Valuing complete backing and Peer acceleration

Checkpoint 优先提出完整 DRAM 扩展，不能准入时考虑 storage；候选包括整份提升／降级、带旧 checkpoint 或日志 fallback 的删除、Peer 替换及保持现状。两层均不可接收时 M 不变。大 Slack 本身不取消正常复用价值。

**分层条件收益。** Storage 相对重算／旧 checkpoint 提供保留；已有完整 storage 时，DRAM 只增加访问加速；Peer 只增加完整后备之上的暴露读取／H2D 等待节省。没有 storage 时 DRAM 也承担保留，降级须先解决有限 storage 空间。后备改变会使 Peer 估值失效，不给临时重复副本重复保留收益。

**沿前缀分配信用。** 固定已知历史终点和 tail，从实际 fallback 逐步加入合法配置：后备每步是含全部层、TP 和辅助状态的 token extent，Peer 每步是合法层／热块组。每步仍可沿用此前恢复路径，保证局部增益非负；获得概率加权的“正常服务时间下降＋超过 guarded Slack 的恢复延迟下降”，按新物理对象字节分配。正常复用不受 Slack 截断，但须考虑路由和现存本地命中。不同 Agent 贡献独立份额，同 Agent 的重复引用不重复授信。

例如，同一恢复终点下完整前沿的恢复时间为 12→7→5 秒，Slack=6 秒，则增量故障收益为 5、1 秒，而非把 6 秒全给尾块。这是可解释的信用分配约定，不保证每个前缀块都比每个尾块重要。

![Slack 与单位容量收益的反例](figures/preview/retention-value.png)

**Figure 7：Slack 不能单独决定保留价值。** 构造例中 A 两单位容量使恢复 4→2 秒，Slack=0；B 一单位容量使恢复 18→8 秒，Slack=6。单位收益分别 1 与 10 秒，正常复用价值置零。图支持比较成本／容量，不宣称策略加速。

**完整计划检查。** 对当前 P 与含候选、受害者和迁移的 P′，计算：

`ΔJ = Σ_e p_e Σ_w [T_w(P′,e) − T_w(P,e)]`。

固定有限场景表包含正常延续及特定源故障域在不同偏移发生故障，概率之和为一。相同队列、服务画像、有限 workspace 和 Connector 调度下，实际复制完成决定 M／N，延迟相对相同正常执行参考进入残余 DAG，join 取最大值。复制干扰与临时占用不另计第二遍。Guard 每个受影响 segment 只加一次；workflow 预测失效则不计 Slack，改比正常／恢复请求完成延迟；资源画像无效则暂停可选提升，强制回收按有界 recency 次序执行安全计划。共同故障下局部信用不能简单相加当作 WCT。

#### 3.5.2 Choosing per-request layers and hot blocks

L_r 是请求 Peer 前缀层数，K_r,l 是该层物理 token block 数（含 TP 对象）。先满足原生 mandatory 集合，其余按已完成 Query 的选择频次排序；跨 heads 同块只计一次，并列按最近访问和 block ID。预算不足 mandatory 状态时不可行；miss 从完整后备补取，不改变注意力选择。

![完整后备、逐层 Peer 热块和实际 miss](figures/preview/sparse-recovery.png)

**Figure 8：状态与缺失路径。** 完整 DRAM 覆盖每层 B0–B3；Peer 的 L=2、K₁=2、K₂=3。实际 layer 1 需 B0/B2，B0 命中、B2 补取，B3 未用。完整性也包含 TP 和 selector；整份降到 storage 后，miss 多经过 storage read。

候选使用有限 block-count／fraction 模板与 0 到模型深度的 L，并保留当前方案；不枚举所有层预算的笛卡尔积。并列瓶颈分支可组成有界联合候选；所有扫描与估值共享工作预算。每个场景由当前 M 推出自身的 N，包含 commit lag；缺少稀疏画像时用全需求。仅仍须执行的计算可以隐藏传输。

![相同回放任务下的逐层恢复流水线](figures/preview/recovery-pipeline.png)

**Figure 9：Peer 只消除剩余暴露等待。** MiniCPM4-8B、32 层、32K 历史、64-token tail；回放校准为 2.870 ms/层，假设有效 H2D=6.25 GB/s，trace-derived preload／含 miss 比例为 0.6584／0.7748。匹配的 (c)/(d) 保持完整 DRAM 和相同计算，(d) 在前七层多放 147.5 MiB Peer，减少 24 ms 等待。理想可抢占传输、均质层成本未覆盖有限 workspace／排队；这是分析模型，不是端到端故障实测。

L/K 不必每 token 增加；固定 K 可以仅更换块身份，没有暴露等待收益时 L=0 合法。新集合在提交前不算当前保护。

#### 3.5.3 Online renewal, admission, and eviction

**信用状态。** 副本 x 保存大小 b、各 Agent 的当前 grant g 和已付租金 d；各 pool 有独立累计租金 ρ，初始为零：

`C_x = Σ_a max(g_a,x − d_a,x, 0)`，`H_x = ρ + C_x / b_x`。

租金前进 δ 时，每个已提交副本支付 min(C_x, b_xδ)，按正信用份额比例计入各 Agent 的 d。Pinned／leased 对象也收租，是否可移除另行判断，支持惰性结算。租金代表容量竞争而非墙钟计费。

- **真实复用：** 先结算，仅刷新实际使用 Agent 的 g、令其 d=0；request/use ID 去重。
- **价值变化：** 更新 g、保留 d；新 checkpoint 不续租未变前缀，需求过期仅去除相应 grant。

![共享对象的收租、价值更新与续租](figures/preview/renewable-credit.png)

**Figure 10：两种更新的区别。** 单位大小共享对象初始份额 A/B=3/2，扣租 2 后为 1.8/1.2；A 的 grant 更新至 4 后保留已付 1.2，余 2.8；A 实际新一轮复用才恢复至 4。B 仍为 1.2。这是构造的信用算例，不是 WCT 测量。

**合法竞争。** 受害者是完整 checkpoint 降级／回退或合法 Peer 缩减；仍有其他 manifest 引用的字节不能算已释放。普通竞争尊重运行请求 logical pin，结束／tool handoff 解 pin；自身热集更新和强制回收可覆盖逻辑 pin，不能越过 physical lease。

RentPlans 在共同预算内刷新 q≥2 个低 key 候选和 q 个轮转候选，尝试不同受害者链；真正释放 Y 时，试算租金至少升到 max(H_x, x∈Y)。新物理字节组须仍有正信用：`G_in > b_in(ρ_trial−ρ)`，扣租按 incoming grant 分配；已存在对象不重授信用。各层分别竞争，计划包含临时空间和 DRAM 降级所需的有限 storage 空间；Peer 已有完整后备时无需冗余 D2H。这是有界搜索，不保证全局最优。

**Algorithm 2：Three-tier rental event loop**

```text
Reconcile(e); SettleAffected(e)
if NewUse(e): RenewAgent(e)
MarkChangedValues(e); S ← Snapshot()
h ← ShrinkRequired(S); (best, cost) ← (∅, +∞)
for m in Candidates(S, h), while WorkLeft():
    for P in RentPlans(S, m, h):
        d ← ΔJ(P; S)
        if d < cost: (best, cost) ← (P, d)
if best = ∅: Defer(e); return
if not h and cost ≥ −ε: return
if not ReserveIfCurrent(S, best):
    Requeue(e); return
Submit(best)                 # completion / failure emits a new event
```

事件包括复用、checkpoint、价值、请求结束、预算、故障和复制回调。可选计划同时通过租金筛选和 ΔJ<−ε；强制回收跳过正信用准入门槛，选择已检查的损失最小合法计划，仍计收租金。无安全方案则暂停准入，后续事件合并重试最新 frontier；周期预算刷新重估旧 key。Tool wait 保留 interest，终结去除 failure demand，过期不活跃份额清理。

预留重新检查版本、lease、字节和租金。试算失败不改真实状态；发布 fallback 后的容量交接才推进租金，新副本提交时安装试算后的残余信用。交接前失败丢弃试算，交接后失败不能倒退时钟或恢复已释放受害者。完成／失败再产生事件，闭合在线流程。

### 3.6 Adapter: Guarded AIMD for Peer Capacity

Adapter 沿用压力下乘性减少、稳定窗口后加性增加，受总额度上限约束：

`C = max(0, min(B_cap, B_pool − B_serve − B_reserve))`。

Pool 扣除模型和固定开销，serving watermark 不含 Peer，reserve 覆盖增长和 workspace，避免重复扣 Peer；B_cap 可配置为 pool 的一部分。

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

初始 B=z=0。分配 stall、预留突破、显存准入等待构成压力；稳定需无压力且等待低于较低阈值，连续 m 个稳定窗口且有正收益待处理需求才增加 Δ。PeerDemand 在当前额度筛选前检查需求，允许从零额度增长；中间状态重置 z。缺失 telemetry 不增长，紧急事件可窗口内减额。窗口与参数可配置，Z 固定；Adapter 不选 L/K。占用＋预留超过新额度时，Master 暂停准入并安全回收，物理 lease 排空前不能把目标额度当作已释放容量。

### 3.7 Connector: Committed Copies and Layered Recovery

Connector 用有界队列和份额限制前台复用、恢复和 checkpoint 的干扰，恢复份额内实际 miss 优先于推测预取。三个不变量统一约束所有迁移：**完整兼容后发布；先发布替代／fallback 再撤旧；读者和复制排空后再释放物理内存。** 因此 DRAM→storage 须完整持久化并提交 manifest 后才重定向、回收；最后副本删除先提供旧 checkpoint／日志重建路径，并撤销失去完整后备的 Peer 声明。部分／旧回调不能推进 M，失败保留有效旧路径。

恢复取得最后完整 manifest 和 lease，Peer 命中直接用，miss 从 DRAM 或 storage→H2D 补取，与仍需执行的计算逐层重叠。实际 KV／selector／TP 依赖齐备后执行，重放 M 之后已确认 token、抑制重复输出并恢复 decode。接管的 Peer 字节转到执行账本，不释放或双算。预测影响性能，但不能授权缺失状态；进展仍需兼容目标和可用资源。


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

消融矩阵包括：无DAG/Slack、joint source-event改为isolated sum、无normal reuse、无failure value、frozen placement、direct revaluation去掉租金、主策略无renewal、主策略无value refresh、主策略无hysteresis、recency替代causal sparse history、serial替代bounded layer overlap、locality-only替代load-aware router，以及singleton与bounded-pair候选。每项保留同样安全覆盖、预算与原生attention。

![value-ablation](figures/preview/eval-value-ablation.png)

当前合并消融图将六种策略的 failure penalty 与 normal next-use cost 并排，使用 storage=4GiB/s 下同一组12个size/slack配置（36配置CDF的一个子集）；两类成本不能相加，均值口径不能混用。该图只评价static value，其余机制不能借这两个图声称已被完整验证。共同失败反例显示候选存在互补性，必须整方案revalue；增加pairs时同时报告oracle regret和控制成本。

四组2×2交互：DAG×joint-fault、sparse rank×overlap、rental screening×hysteresis、load-aware route×shared-link contention。四个cell同campaign配对，interaction=(Y11−Y10)−(Y01−Y00)，不能把独立speedup相加。安全协议不做“关闭后更快”的有效性能基线。

### 4.9 稀疏需求与layer overlap的解构

八层模型，每层full selected payload的SSD4ms、H2D1ms、compute3ms；DRAM同样容纳两层payload，staging最多当前+下一层。early/late placement与serial/pipeline四格保持同需求。改变selected-density时所有策略一起变，不允许为了cache策略更好而改变native attention。

![layer-factorial](figures/preview/eval-layer-factorial.png)

full demand下两个serial都56ms，late-pipeline34ms、early-pipeline32ms；所有case required compute都24ms，差别来自exposedwait。错误prefetch消耗额外读、真实需求等reveal才读；当前correct-prefetch比例是人为输入，正确位置按层序指定，不是学习器准确率。

原生实验捕获held-out retry的per-layer demand union与reveal时刻，用此前历史预测；按workflow/document分训练验证，不按blocks拆分。equal physical bytes、mandatory sink/window和coverage保持一致，报告all-layer coverage、unused/miss bytes、reveal-to-ready、GPU stall、workspacepeak、total replay和WCT。早期层100%命中不等于全部层100%。

**新增三层配对实验（待执行）。** 固定完整 DRAM/storage 覆盖、fault ID、原生 demand 和恢复调度，比较 Peer=0、同容量 recency/frequency、固定 L、逐请求 L/K，并做 Peer 位置×overlap 四格。使用同一物理 HBM pool，记录被 Peer 挤出的正常服务、跨 DP 复制和所有临时容量；扫描 M、真实 N、Z、热集漂移和 target rebind，联合报告增量 WCT、正常吞吐和传输字节。本地 HBM reuse 微基准不能替代该实验。

### 4.10 租金问题诊断与直接重估对照

当前提出的主策略是“真实复用续租＋保留已付租金的价值更新＋完整计划检查”。原 8 slots、24 等大小对象、512 个确定性候选机会的简化模型保留为反例：它只在 candidate revisit 续租，scored next-use hit 不续租，并且只检查一个最低信用受害者。模型没有多 Agent 份额、prefix 依赖、三层降级、物理 lease 或 serving scheduler，不能代表新控制器。

![历史租金反例，未改动其数值](figures/preview/eval-rental-cost.png)

Direct 与旧 trial rent 的总 miss＋movement 成本仍为 **462.96／506.39**，迁移 108／106 次，均为 396 次 scalar 替换检查；去 hysteresis 迁移 121 次，去 renewal 迁移 77 次但总成本 526.05。原轨迹有 104 次拒绝时存在另一个满足当前收益门槛的对象，这只是诊断计数，不能把它当作成本差额的因果分解。

同样输入、成本参数下，仅增加 scored-hit 续租反而为 **512.67**；价值更新且不退租降到 **477.86**，再检查两个低信用受害者降到 **466.76**，缩小原差距 91.26%，仍比 direct 高 0.82%。4 个起始 phase×3 个变化周期×3 个容量的 36 格中，最后修正全部优于旧租金，但对 direct 仅 9 优、27 差。它也付出 747 次替换检查＋4,088 次 key 更新，不能声称控制成本更低。该修正诊断不等于新版完整控制器性能验证。

下一步比较必须在相同价值模型、候选机会、安全协议、物理资源和控制工作预算下，对照 direct、旧 screening 与新算法；分别消融真实续租、当前价值更新、多 Agent 信用、备选受害者搜索。覆盖多轮工具等待、上下文增长、同角色共享前缀、突变、下层存满、Adapter shrink。记录 grant／已付租金／trial 与 committed rent／版本失效／DAG pass／CPU／迁移／实际 M／miss／WCT。保留上述反例作为回归，而非删除或解释成已验证的新算法收益。

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

## 设计补充说明（仅供实现与实验复核，不进入英文正文）

以下保留本轮从 System Design 展开叙述中移出的细则；不是新增机制。正文聚焦决策依据、算法和三个提交不变量。

- **对象与训练口径：** 对象身份还包含模型／权重版本、布局、精度、位置和前缀语义。只有辅助状态有效的前沿才能拆分 extent，否则相邻 extent 作为一组。GBDT 的标签是快照到 segment 结束的剩余时间，不能用跨嵌套 fork 的 whole-Agent 标签代替，也不能从 remaining-time 预测再次扣 elapsed；任务／工具描述仅在应用确实提供时用作特征。
- **需求与信用：** 未支持的复用预测不能凭空增加未来调用；真实使用按 Agent 和 request/use-event 去重。过期、不活跃的 interest 可删除，只有新观察到的使用才能重建，价值刷新本身不能重授初始信用。所有对象已存在时可以只关联 manifest，不复制，也不续租未变前缀。
- **有界竞争：** incoming 在真实当前租金处建立试算份额，尝试下一受害者时不重新授信。纯 metadata 修改不经过新字节准入门槛。每次 grant 计算、扫描、候选与 DAG pass 都计入同一工作预算；低 key 与轮转候选避免首次替换失败就结束。Owner bundle 与并列瓶颈 bundle 同样有明确大小上限。
- **异步提交：** 不相交 pool 可并行，共享资源通过版本化预留串行化。已准备的容量交接再次检查版本、lease 和 fallback，发布后先撤销受害者的新读资格，再等待旧读者排空。交接前失败丢弃试算；交接后失败保留已发生的租金和淘汰。Storage 的 buffered write ACK 不等于达到后端持久化契约。Prefill 故障也从最近完整 M（可能为零）恢复，执行工作区不足时排队或重绑定。
