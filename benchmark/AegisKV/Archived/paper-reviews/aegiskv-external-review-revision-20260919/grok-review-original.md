**EuroSys 审稿意见（AegisKV，仅摘要 + §2 + §3 + 参考文献，9 页 baseline）**

**1. 核心贡献与总体判断**

AegisKV 提出面向多 agent 工作流的 KV 容错框架：从 DAG 依赖与剩余执行时间估计请求 slack，结合恢复成本选择保护层级（R/D/P），并在稀疏注意力访问模式与层执行顺序指导下做 hot-block / 层深放置与恢复。目标是在有限备份容量与带宽下，优先降低真正影响 workflow completion time（WCT）的恢复延迟。

**总体判断（与当前范围相符）**：动机问题真实且重要（多 agent 长上下文 + 故障恢复对 WCT 的差异化影响），设计意图清晰，算法框架（GBDT-CPM slack、预分配 takeover、per-request tier/depth/hot-set、windowed Peer budget）有系统味道。但目前内容**未达到 EuroSys 可接受水平**。核心缺口是：几乎所有关键数字与“效果”均来自静态估计、文献提取或反事实替换，而非系统实测；假设与接口自洽性、并发争用、正确性、缩容语义均存在未闭合的漏洞；§3 末尾作者自己列出的大量“待验证”直接削弱了可证伪性。EuroSys 要求新颖性 + 严格评估 + 清晰正确性；当前稿件在“问题重要”上够格，在“系统正确性与评估严格性”上远不够。

**最强 3 点**  
1. 明确把“恢复成本 ≠ WCT 延迟”作为一等公民，并用 CC/Weka 轨迹给出 branch-duration gap 与反事实 WCT 暴露的动机证据（图 1）。  
2. 将稀疏注意力的实际 selector 输出转化为保护对象（layer/block），并尝试用历史频率做 hot-set，比“所有 KV 字节平等”更贴近现代 LLM。  
3. 把 slack、tier、depth、Peer budget 分层决策，并预分配 takeover 目标，避免故障时再做全局调度。

**最可能导致拒稿的 5 个原因**  
1. **关键效果几乎全部是静态/文献/反事实估计**，无端到端系统在真实故障、真实并发、真实容量约束下的 WCT 测量。  
2. Slack 预测（GBDT + CPM）的运行时误差、DAG 不完整、工具调用不确定性对保护决策的影响未被量化，存在“错误 slack 导致错误保护”的正确性风险。  
3. 保护层级与 depth 选择的代价模型、hysteresis、score 函数高度启发式，缺乏可证伪的正确性/最优性论证与争用下的退化分析。  
4. 并发恢复、带宽争用、Peer 缩容时“referenced copies 不立即释放”的语义与正确性未闭合，容易出现活锁或容量泄漏。  
5. 与既有系统（DéjàVu、GhostServe、LUMEN、Mooncake 等）的增量不够锐利，相关工作对比停留在“它们没考虑 workflow slack”，未量化在相同故障模型下的差距。

---

**2. 按严重性排列的高价值问题（编号唯一）**

**P0-1**  
位置：§2.2、图 1(c)、第 2 页反事实描述  
问题：用 trace 时长差 + 静态 Qwen3-14B 重算时间替换真实故障影响，并声称“A2 虽重算成本最低却 WCT 惩罚最大”。这是**动机证据的选择偏差**——未验证 fan-in 真实依赖、未重放真实 serving 队列/批处理/争用、未考虑故障时刻的实际 commit frontier。  
机制/反例：若真实依赖只消费部分 branch，或故障发生在不同重叠区间，slack 排序完全改变。  
可执行修改：明确标注“推断 fan-in + 静态替换”，补充至少一组真实依赖标注的子集，或给出敏感性（不同故障时刻、不同 tail）。  
验证通过标准：读者能复现图 1(c) 的计算，并看到依赖推断错误时的结果变化幅度。  
负责范围：动机。

**P0-2**  
位置：§3.3 Algorithm 1、Insight 1（图 3a 来自 Heddle）  
问题：GBDT 预测 remaining time 后直接做 CPM slack。文献相关性（0.72–0.94）是 trajectory length，不是运行时 WCT 误差；未说明预测偏差如何传播到 tier 决策。  
机制/反例：若某关键路径预测低估 30%，系统会错误地给它高保护，浪费容量；高估则让零-slack 请求走 recompute，直接拉长 WCT。  
可执行修改：给出预测误差对 final tier/depth 的敏感性分析框架；明确“unknown DAG → zero slack”的保守策略在工具调用/外部 agent 下是否过于悲观。  
验证通过标准：至少报告预测 MAPE 与 tier 翻转率的关系（即使是模拟）。  
负责范围：算法 + 跨章节。

**P0-3**  
位置：§3.5 公式 (1)、tier 选择、20% hysteresis  
问题：𝑅base = 𝑅floor + 𝑇rp，𝑅𝑅 = 𝑅base + 𝑇rc，𝑅𝐷 = 𝑅base + 𝑊0。所有成本为“profiled jointly”，但未给出 profile 方法、并发假设、是否包含检测/队列。Hysteresis 与 score 函数（含 source-failure probability）高度启发式。  
机制/反例：若 profile 用 batch=1 而实际连续批处理，𝑊0 被严重低估 → 过多请求被标为 tier-P，Peer 预算瞬间耗尽。  
可执行修改：公开 profile 生成流程与代表并发；给出 score 的数学形式与失败概率模型；证明 hysteresis 不会导致振荡。  
验证通过标准：在固定 profile 下，tier 决策可复现；改变并发参数后决策变化可解释。  
负责范围：算法。

**P0-4**  
位置：§3.4 Recovery Manager + §3.5 “Retries enter independently… Manager never waits”  
问题：预分配 𝑝𝑟，但恢复时各请求独立推进、共享 compute/copy 带宽。无机制防止高 slack 请求抢占低 slack 请求的恢复资源，或低 slack 请求被饿死。  
机制/反例：多个零-slack 请求同时故障，Peer 带宽被低优先级 copy 占用，WCT 被拉长；或高 slack 请求的 hot-set copy 占用 HBM，导致零-slack 无法获得 Peer。  
可执行修改：明确恢复调度策略（是否按 slack 加权、是否 preemption、带宽份额）。  
验证通过标准：至少两个并发故障场景下的恢复完成时间与 WCT 关系可被论证。  
负责范围：跨组件接口。

**P0-5**  
位置：§3.6 Adapter + Algorithm 3 + “reducing 𝐿𝑟 does not revoke pins”  
问题：预算缩小时只停新分配 + 回收 zero-reference；referenced copies 继续占用，物理用量可超过新 𝐵𝑝。无硬上限与超时回收。  
机制/反例：大量长生命周期请求（工具调用挂起）导致 Peer 区域长期超支，foreground KV 被挤出 → 正常服务 OOM 或 admission stall。  
可执行修改：引入 soft/hard watermark、referenced 超时强制降级、或 foreground 优先抢占语义。  
验证通过标准：在预算突然减半 + 长生命周期请求存在时，系统最终能回到目标预算且不饿死 foreground。  
负责范围：算法 + 跨组件。

**P0-6**  
位置：§3.5 “Placement changes neither selector outputs nor known replay tokens… reconstruct the same logical KV state”  
问题：声称正确性，但稀疏 selector 状态、RoPE、MLA latents、FP8 indexer 的恢复顺序与 commit frontier 一致性未形式化。  
机制/反例：hot-block 只覆盖部分层，miss 后补算时若 selector 状态与原始不一致，后续 decode 产生不同注意力结果。  
可执行修改：给出恢复时的精确状态机（哪些必须在 layer 前 ready、miss 如何强制 dense/full reload）。  
验证通过标准：同一 prompt + 同一故障点，恢复后 decode 输出与无故障路径在确定性设置下 bit-identical（或明确随机性边界）。  
负责范围：正确性。

**P1-7**  
位置：§2.3 图 2、HYBRID 估计  
问题：所有恢复时间曲线是静态估计（含外推、假设 64 GB/s、无 overlap、无 contention）。作者自己承认“cannot establish WCT gains under limited backup capacity”。  
可执行修改：把图 2 明确标为“static cost model”，并说明它只用于 tier 阈值，不用于性能声明。  
验证通过标准：正文任何地方不再用这些数字暗示系统加速。  
负责范围：动机/表达。

**P1-8**  
位置：§3.1 Insight 3、图 3(c) PG19 book-text  
问题：用 held-out book-text 后缀的历史频率覆盖率论证 hot-set 有效。Agent 工作流的访问模式（代码、工具输出、跨 agent 中间结果）与 book 完全不同。  
可执行修改：至少用 CC/Weka 或类似 agent trace 的 KV 访问 trace 重做覆盖率，或诚实声明“仅作为稀疏模型存在性证据”。  
验证通过标准：读者不会误以为 40% 字节能覆盖 77% agent 需求。  
负责范围：动机。

**P1-9**  
位置：§3.5 Algorithm 2、depth 选择 score  
问题：score = recovery delay beyond slack + weighted foreground delay from backup work。是 local heuristic，非全局 makespan。多个请求竞争同一 target 时，顺序依赖可能导致次优。  
可执行修改：说明为什么 local + slack-order 足够，或给出近似比/最坏情况。  
验证通过标准：至少在小规模合成 DAG 上对比 local vs 全局 ILP 的差距。  
负责范围：算法。

**P1-10**  
位置：§2.1 故障模型 + §3.2  
问题：仅 fail-stop 单 GPU/worker；whole-host、网络分区、静默错误明确排除。对多 agent 生产环境是否足够现实？控制平面与 backup DRAM 的存活假设过强。  
可执行修改：明确此模型的覆盖率，或讨论控制平面自身容错。  
负责范围：动机。

**P1-11**  
位置：§3.5 “hot-block statistics use the preceding 512 decoding steps” + 可选 block 离开 top-set 规则  
问题：统计窗口与 checkpoint 窗口独立，但未分析窗口大小对覆盖率与抖动的影响。  
可执行修改：给出窗口敏感性。  
负责范围：算法。

**P1-12**  
位置：全文术语  
问题：“slack”“exposed recovery waiting”“Peer”“tier-P without Peer grant”等混用，部分地方“protection”与“residency”混淆。  
可执行修改：统一术语表。  
负责范围：表达。

**P2-13**  
位置：图 1、图 2、图 3、图 5  
问题：图注过长、部分数字挤在一起；图 5 的 pipeline 是 homogeneous 模型，容易被误读为实测。灰度印刷下颜色区分弱。  
可执行修改：拆分图注、统一字体 ≥10pt、增加“modeled”标注。  
负责范围：图表。

**P2-14**  
位置：§3.2 图 4 徽章与文字  
问题：徽章编号与正文机制对应关系清晰，但“memory proportions are schematic”需要更早出现。  
负责范围：表达。

**P2-15**  
位置：参考文献 [1][6][20] 等  
问题：部分 arXiv 编号与会议信息需核验是否最终版；LUMEN、GhostServe 的对比点过于笼统。  
负责范围：相关工作（待核验）。

**P2-16**  
位置：§2.4 设计目标 R1–R5  
问题：目标写得漂亮，但后续机制对 R3（无序列化）与 R4（overhead 从属）的支持主要靠声明。  
负责范围：结构。

---

**3. 跨组件接口与假设自洽性（至少两个具体失败/退化场景）**

接口关键点：Tracker 输出 slack → Master 用 slack 排序做 tier/depth → Adapter 只提供 window budget → Recovery Manager 只负责目标绑定与独立推进。

**场景 A（slack 错误 + 并发恢复）**  
假设 Tracker 对某零-slack 关键路径低估 remaining time → 被标为 tier-D 或低 depth。同时多个请求故障，Peer 带宽被高 slack 请求的 speculative copy 占用。结果：真正决定 WCT 的请求走慢路径，系统“按设计工作”却让用户看到更长的 completion time。作者已声明“prediction errors remain to be validated”，但未说明此错误如何被检测或回退。

**场景 B（预算缩容 + 长生命周期引用）**  
Adapter 因 foreground 需求上升而降低 𝐵𝑝。大量请求处于“工具调用挂起”状态，Peer 副本仍被引用。物理占用长期超过目标，foreground KV 被挤，admission stall 增加。正常服务开销从“negligible”变成可见。作者已说“physical usage can therefore exceed”，但未给出最终回到预算的保证与时间界。

这两个场景都不是作者已声明的“局限列表”的简单重复，而是直接威胁 R1（WCT）与 R4（overhead）的系统级后果。

---

**4. 最小但有说服力的评估矩阵**

| 维度 | 建议内容 | 是否可无新硬件修订 | 是否必须新实验 | 是否需重大设计决策 |
|------|----------|---------------------|----------------|---------------------|
| 基线 | 无保护 recompute、全 DRAM、全 HBM（容量允许时）、简单 recency/frequency、LUMEN/GhostServe/DéjàVu 风格 | 部分可模拟 | 是（端到端） | 否 |
| 消融 | 无 slack（纯成本）、无 hot-set（全层）、固定 depth、无 hysteresis、无 window budget | 可模拟 | 是 | 否 |
| 负载 | CC/Weka 真实 trace 重放 + 合成多 branch DAG + 不同上下文长度分布 | 可 | 是 | 否 |
| 故障 | 单 GPU fail-stop、多请求同时故障、故障时刻在不同 slack 区间、预算突然变化 | 可 | 是 | 是（恢复调度） |
| 指标 | WCT、单请求 recovery latency、Peer 占用、正常服务 throughput/latency 开销、tier 翻转率、预测误差敏感度 | 可 | 是 | 否 |
| 正确性 | 确定性 decode 一致性、miss 后补算正确性 | 可 | 是 | 是（状态机） |

当前稿件几乎所有数字都落在“静态估计/文献”列，必须补齐“系统实测”列才能过 EuroSys 严格评估关。

---

**5. 五个最有价值的英文句子/图表重构建议（避免无证据性能承诺）**

1. 原摘要末句 → “Experiments on static cost models and public agent traces show that prioritizing low-slack requests can reduce estimated workflow exposure; end-to-end measurements under real failures and capacity limits remain future work.”  
2. 图 1(c) 标题/注 → 明确加 “Counterfactual substitution using static prefill times; not a measured failure replay.”  
3. §2.3 图 2 注 → “All curves are static AIConfigurator estimates under idealized bandwidth and no contention; they motivate tier thresholds, not claimed system speedups.”  
4. §3.5 tier 描述 → “A request is assigned tier P when its estimated recovery cost exceeds its current slack estimate; the actual Peer residency is subject to the target Adapter’s window budget and may be partial.”  
5. 图 5 重构建议：拆成“modeled pipeline stages”与“illustrative numbers only”，删除任何可能被读成“系统实测 20 ms”的暗示，统一用灰度可区分的填充纹理。

---

**总结给作者的修改优先级**  
P0 正确性与证据问题必须先闭合（尤其是 slack 误差传播、并发恢复调度、缩容语义、恢复状态一致性）。动机部分可保留并诚实标注估计性质。只有补齐最小评估矩阵中的端到端故障与消融后，才值得冲击 EuroSys。当前 9 页内容作为 design sketch 有价值，作为完整系统论文仍不完整。
