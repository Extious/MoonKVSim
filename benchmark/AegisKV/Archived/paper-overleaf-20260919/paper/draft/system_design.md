## 3 AegisKV Design

AegisKV 结合工作流的延迟容忍度与单请求的 KV 恢复需求：Tracker 估计 Slack；Recovery Manager 在请求到达时绑定接管目标；KV Master 在固定 checkpoint 间隔及策略事件中决定保护层级、逐请求目标层数和候选热块；Adapter 在每个时间窗口边界只更新各目标 DP 的 Peer 容量预算。下面先说明设计依据，再按模块给出决策与执行过程。

### 3.1 Insights 与设计启示

**Insight 1：执行上下文使 Agent 剩余工作量具有可预测性。** 已有方法利用任务语义与运行进度估计多轮 Agent 的剩余工作。[Heddle](https://arxiv.org/abs/2603.28101v1) 在第二步后，对 Coding、Search、Math Agent 剩余轨迹长度的预测相关系数约为 0.72、0.88、0.94，均优于第一步后的预测（图 3(a)）。[AgentDecarbonizer](https://arxiv.org/abs/2608.20566v1) 进一步展示了任务级执行时长估计与基于进度的剩余时间更新。AegisKV 使用这些已有能力，将剩余时间估计经 CPM 转换为工作流 Slack，驱动 KV 保护；预测器本身不是本系统的新贡献。图中的轨迹长度相关性支持可预测性，秒级时长仍需与具体模型、工具及部署条件匹配。

**Insight 2：稀疏注意力改变恢复时需要保护的对象。** 长上下文模型已采用 InfLLMv2、DSA 以及压缩/混合注意力。图 3(b) 的十个发布实例说明适用模型的存在，不代表市场采用率，也不意味着每层都使用相同的 Top-k。KV Master 接收真实的逐层选择与模型特定恢复状态，而不将所有历史 KV 字节视为等价。

**Insight 3：过去的选择能预测 retry 尾部所需历史 KV 的一部分。** 图 3(c) 中，两个策略均使用各模型历史 KV 字节数的 40%，历史频次覆盖 NOSA-3B、MiniCPM4-8B、SeerAttention-Qwen3-8B 所需 KV 的 77.8%、53.6%、43.0%，最近优先为 59.7%、50.9%、42.0%。Seer 在跨 head 取并集后需要约 92.5% 的历史块，该预算下即使预知需求的最优放置也只能覆盖约 43.3%。收益依赖模型与放置粒度且存在未命中，因此提前放置必须配合确切需求的补取。这些留出的书籍文本后缀不是 agentic 故障恢复实验。

<figure class="paper-figure">

[<img src="../figures/agent-time-literature/figure3-row.png" width="1008" alt="图 3 时间估计、稀疏模型与 retry KV 预测">](../figures/agent-time-literature/figure3-row.pdf)

**图 3：设计依据。** (a) 改绘自 Heddle Figure 13（arXiv:2603.28101v1，第 10 页），展示 Qwen3-14B 在第一、第二个 Agent 步骤之后预测剩余轨迹长度的 Pearson 相关系数。数值从原始矢量图读取，属于文献报告结果；不是 AegisKV 的秒级时长误差或复现实验。数据来源见[预测能力说明](../figures/agent-time-literature/README.md)。(b) 发布/模型仓库日期与原生上下文；编号 1–10 对应 MiniCPM4、MiniCPM4.1、DeepSeek-V3.2-Exp、DeepSeek-V3.2、GLM-5、MiniCPM-SALA、DeepSeek-V4 preview、MiniMax-M3、GLM-5.2、LongCat-Flash-Lite-Sparse。灰线仅为入选版本的最大上下文，marker 表示稀疏分支中块、token 或压缩项的 Top-k 选择。(c) 每模型 3 份原生 PG19 捕获，32K 历史；Query 32,257–32,768 预测 32,769–32,832 的去重历史需求。对象为包含所有 KV heads 的逐层 64-token 块，强制块包含在 40% 预算内；Seer 为 Qwen3-8B 加载[公开的实验性 Prefill gate](https://huggingface.co/jiwonsong/SeerAttention-Qwen3-8B-AttnGates)，阈值为 0.001，关闭末尾 Query 块强制 dense 的可选配置。柱与误差线为文档均值与范围。完整来源见[图像说明](../figures/design-insights/README.md)。

</figure>

### 3.2 System Overview

图 4 分为应用、控制面和推理引擎。应用上报 request/workflow 标识与 DAG 更新；Router 按负载及 KV 局部性分发；AegisKV Controller 维护 Slack、恢复目标和备份策略。DP0 与 DP1 各有 Adapter、Connector、Local KV 和较小的 Peer 区。KV Master 决定备份策略及各请求的目标层数，各 Adapter 控制本地 Peer 预算，并调用 Connector 执行复制；KV 直接在引擎与存储间传输。黑底编号只索引下文模块，不表示执行顺序。

<figure class="paper-figure">

[<img src="../figures/system-overview-v11.drawio.png" width="480" alt="图 4 AegisKV 三层架构">](../figures/system-overview-v11.drawio.pdf)

**图 4：AegisKV Overview。** ① Tracker、② Recovery Manager、③ KV Master、④ Adapter 各标一次；到达时绑定恢复目标，备份策略下发至 Adapter，Peer 容量逐窗口调整，层数由 KV Master 按请求分别决策；两侧 DP 能力相同。Peer 与 DRAM 路径独立提交，内存比例和块布局为示意。图源：[Draw.io](../figures/system-overview-v11.drawio)。

</figure>

Recovery Manager 在请求到达时记录 retry 目标及 Peer DP rank（§3.4）；KV Master 在请求/KV/Slack 事件及控制窗口更新备份策略（§3.5）；Adapter 在每个时间窗口边界只更新目标 Peer 容量（§3.6）；checkpoint 间隔为固定系统配置，层数由 Master 逐请求更新。目录与提交元数据保存在源故障域之外。

### 3.3 Workflow Tracker：GBDT 与 CPM ①

Tracker 先用 GBDT 预测 agent 剩余执行时间，再用关键路径法（CPM）计算 Slack，过程见算法 1。 GBDT 是可替换的预测器实例；图 3(a) 展示的是 Heddle 预测器的文献结果。在时刻 $t$，残余 DAG $G_t=(V_t,E_t)$ 的节点是尚未完成的 **agent 执行段**：每段包含依赖屏障之间的连续多轮请求；父 agent 在分叉/汇合处拆段，避免将子 agent 的执行时间重复计为父 agent 的等待时间。已完成的段移除，每个活跃请求 $r$ 映射至所属执行段 $a(r)$。

**预测剩余时间。** GBDT $f_\theta$ 的特征包括角色/模型、已运行时间、已知 prompt 长度，以及已完成请求的数量、输出长度和延迟。历史运行快照的训练标签为 $t_a^{\mathrm{finish}}-t$；入口快照的标签为执行段总时长，并遮蔽启动前不可知的元数据。因此，未启动段预测的是依赖就绪后的执行时长。未来请求、未来输出和最终完成时刻不作为输入特征。模型直接输出剩余时长，不再减一次已运行时间。

**算法 1：GBDT–CPM Slack 估计**

```text
Input: residual DAG Gt, visible features x(t), trained GBDT fθ,
       live requests Rt, request-to-segment map a(r)
Output: request Slack σ
1  σr ← 0 for all r ∈ Rt
2  if DAG structure incomplete: return σ
3  za ← fθ(xa(t)) for all a ∈ Vt
4  if any prediction unavailable or invalid: return σ
5  d̂a ← max(ε, za) for all a; π ← Topo(Gt)
6  for a in π:
7      EFa ← d̂a + max{EFb : b ∈ P(a)}
8  T ← max({0} ∪ {EFa : a ∈ Vt})
9  for a in reverse π:
10     LFa ← min{LFb − d̂b : b ∈ S(a)}
11 for r ∈ Rt:
12     σr ← max(0, LFa(r) − EFa(r))
13 return σ
```

$P(a)$/$S(a)$ 为前驱/后继集合；无前驱时取最大值 0，无后继时取最小值 $T$；$\varepsilon>0$ 为剩余时长下限。EF 是相对当前时刻的最早完成时间，LF 是不推迟预测工作流完成时间 $T$ 的最晚完成时间。

**传播并更新 Slack。** 活跃请求继承所属执行段的 $\sigma_r=\max(0,\mathrm{LF}_{a(r)}-\mathrm{EF}_{a(r)})$；同段请求共享这份余量，不能将其视为每个请求可独立累加的延迟预算。请求到达/完成、DAG 更新和放置窗口触发重算，CPM 的复杂度为 $O(|V_t|+|E_t|)$。若依赖结构尚不明确或预测不可用，该 workflow 的 Slack 取零；已知但尚未完成的前驱正常参与 CPM。这是规划估计，不是延迟保证；系统评估需计入所选预测器的时间误差与在线开销。

Tracker 的 DAG 完整性由 orchestrator 声明：剩余 fork/join 已展开且所有 live request 映射已知；新分支或未解析依赖使声明失效并回到零 Slack。CPM 本身不模拟未来资源排队。训练测试按 workflow 与时间隔离，不能混合同轨迹 snapshots；需报告秒级误差、false-safe Slack、关键路径排序、零 Slack fallback 比例与 regret。Heddle 的相关性不代替这些验证。

### 3.4 Recovery Manager：预定接管与并发恢复

请求到达时记录 source DP 与不同的 retry/Peer DP；固定目标不意味着已分配 HBM。故障后先确认并隔离失效源，再从存活的控制状态获取 token 日志、提交前沿、模型/布局/分片信息和副本位置，提交到已记录的目标。若目标也不可用，则重新分配，不能把旧目标的副本视作新目标本地数据。

恢复请求按各自的逐层就绪事件推进，不等待更高备份优先级的请求先恢复完成。引擎为物理上可运行的恢复任务保留正的调度份额，同时继续前台 continuous batching；恢复份额内按有限 prefill chunk 或 decode step 轮转，待准入请求按年龄处理并核对真实显存，阻塞层主动让出执行机会。这是需要实现的接口，不是未经修改的引擎已经具备的保证。

正常备份复制受配置的总带宽上限约束（默认链路容量 20%）。故障补取与必要降级回写分别获得正的服务份额，前台保有自己的份额；每条共享链路及目标 HBM 都要计账，份额之和不超过可用能力，空闲份额可借用。恢复中实际 miss 优先于推测预取，各请求按字节 deficit round robin 共享补取份额并限制在途数量。DMA/内核只能在真实支持的边界让出。有限竞争者、有限操作粒度和正的可用服务量支持进展，不等于过载下仍有延迟保证；这些条件必须进入恢复 profile。

**批处理边界。** retry 依次处于等空间、等数据、ready 和 running；执行 chunk 前预留激活/KV 工作集和传输缓冲。TP 各 rank 使用相同 batch、layer、collective 顺序。缺块只能在合法 kernel 边界暂停；只有后端支持时才拆批，否则整批等待并计入 profile。保留的激活仍收费，不允许逐层任意乱序；先预留内存再取 I/O lease，等待 DMA/collective 时不持目录或队列锁。

**最小恢复合同。** 存活控制端持有单调递增 source epoch；新副本提交、目录写入、输出 ACK 均拒绝失效 epoch。ACK 前持久化请求 ID、token 位置/值及 epoch，输入和已接纳 tool 结果也需可恢复；KV 可落后于日志，重放后按位置去重交付。工具外部副作用由 orchestrator 的幂等契约负责。checkpoint manifest 只有在同一 token 前缀对应的模型/权重/布局、全部层/TP 分片、密封区间、selector 状态和日志依赖闭包完整提交后发布；frontier 取最新合法公共 manifest，不能取独立对象位置的最大值。Peer/DRAM 独立提交可以任意先后；恢复再查存活副本与版本，不完整的新 manifest 不替代旧版本。

预绑定不预留计算、工作空间或准入资格；成本须包括目标前台批次、重试工作集、队列、共享链路和故障域。目标没有可行工作空间时排队或由 Manager 重新检查路由及放置，不把本地副本等同于能立即执行。20% 是流量 cap，不能声称正常推理开销 ≤20%。

### 3.5 KV Master：逐请求备份与迁移决策

Recovery Manager 决定接管目标，Adapter 提供窗口级容量。KV Master 决定 Recompute/DRAM/Peer 层级、请求自己的 $L_r$ 和各层热块，不使用窗口内统一 L。

**触发与 Z。** 到达时建立策略，prefill 完成后提供密封状态，此后每增加固定配置的 Z 个生成 token 复核该请求。显著 Slack、预算、上下文和复制状态变化可提前触发。Z 与物理块对齐，不由 Adapter 调整。决策并非提交：复制排队使实际尾部 N 可能超过 Z。块密封只更新候选资格。热度统计使用此前 512 个 decode step，独立于 checkpoint 和容量窗口。复制队列设字节与操作数上限；合并被替代且尚未开始的计划，不丢弃在途/已提交版本的依赖，无法预留时跳过本次备份并报告 commit lag。

**保护层级。** 对同一组条件故障状态样本求恢复代价的加权均值：
$R_R=R_{\mathrm{floor}}+T_{\mathrm{rp}}+T_{\mathrm{rc}}$，
$R_D=R_{\mathrm{floor}}+T_{\mathrm{rp}}+W_0$。
Slack 能覆盖 $R_R$ 时允许 R；否则仅当 $R_D<R_R$ 且 Slack 能覆盖 $R_D$ 时取 D，其余为竞争 Peer 的 P。不假设 DRAM 比重算快；Peer 未获准入后选择更便宜的可行非 Peer 路径，代价相同取 R。DRAM 必须独立预留/提交，失败时退回旧合法 frontier 加尾部重放，或从日志重算。缺 profile 时尝试保守 DRAM 准入，不声称更快；实际恢复重新检查代价和可用性，区间重叠时保持可行当前路径，只有明确支配才切换。这些均为计划启发式，不是 deadline 保证。

**K 的含义。** $H_{r,l}$ 是请求 r 在第 l 层已发布、已提交的 Peer 副本集合，$K_{r,l}=|H_{r,l}|$。K 仅表示每请求每层实际 Peer 驻留 Block 数；原生 selector 的 top-k、候选配额、复制预留和池的总物理占用另行计量。正在退休的缓冲区在释放前仍占物理空间，不能算作可用空闲。共享物理副本在池中只计一次。

候选数量由单独声明的 quota rule 决定：固定块数上限，或按密封历史块数使用 $\lceil h_l n_r\rceil$。一次比较固定该规则，本文不声称已找到最优 K。强制 sink/window 块必须容纳在 quota 内；若超额，显式申请并计费更大的配额，否则拒绝该层 Peer 准入，不能删减原生要求。其余按原生选块频次、最近性、稳定 Block ID 排序。可选块连续两个统计窗口离开目标才退出。必需 selector/压缩状态另计。多 token 重放需求是跨 query 与 KV group 的块并集，不把单次 top-k 直接乘 N。不足 512 步时使用已有观测；零观测先排必需块，再按最近性与稳定 ID，尚无冷启动准确率证据。

**同请求热集更新。** 前 d 层只是受限候选族，不声称任意层放置不能更优。深度候选 d 提供前 d 层目标集合：保留交集，降级退出的自有块，换入新块。普通请求竞争不能抢占其他请求的引用。一个请求退出共享块，只释放自身引用；旧块若仍被别人保护，不能释放物理空间。增加空间仍需准入，回写和迁移临时空间计入预演。降低 L 可退出自身深层块；L 不变也能更新块身份。实际部分准入通过 $H_{r,l}$ 和 K 报告。

**深度评分。** 每个请求的候选都从相同快照 S 开始，使用相同时间范围 H、条件故障状态样本及权重。样本包含未来 M、N、故障发生前可复制时间与前台/重试负载，并记录提交落后；既不固定 N=Z，也不默认 checkpoint phase 均匀。当前 Slack 在一次局部比较中固定。同源请求使用共同故障事件样本及目标资源竞争；$p_r$ 保留表示目标 DP，故障概率另用 $\pi_r$。若选用 Poisson 模型，$\pi_r=1-\exp(-\lambda_r H)$；其他风险模型须给出同一 H 内的概率。

预演产生迁移计划 $G_d$。$A_r(d)$ 是该计划相对保持现状引起的前台请求延迟变化之和，单位秒，可为负。影响集合是当前活跃请求及 H 内到达请求；使用匹配到达轨迹和固定策略，跟踪至完成（包括 H 之后的完成）；包含复制、脏块回写、临时显存及准入压力变化。$R_r(d,j)$ 是样本 j 的故障至状态就绪时间，只计故障发生前预计已提交的副本。评分为

$$J_r(d)=A_r(d)+\pi_r\sum_j w_j\max(0,R_r(d,j)-\sigma_r).$$

这是 Slack 顺序下的局部保护启发式，不是各工作流 WCT 之和或全局最优。候选网格包含 0、当前深度以及保留现有块身份的 keep 计划；比较后仅胜出计划推进虚拟快照，再处理下一请求。同源的两条等长关键分支各需 10 秒恢复，只保护一条可把局部罚项之和从 20 降到 10 秒，工作流仍延迟 10 秒；需共同事件的 DAG replay、小 DAG 可行 oracle/regret 验证这一局限。

**Profile 接口与回退。** 输入模型/权重/selector 版本、布局与块大小、硬件/链路、快照、迁移计划、条件样本及共享资源调度配置。输出 A、各样本 R、误差区间、generation、支持范围和过期时间。A 来自相同到达轨迹的成对正常执行估计，R 来自成对恢复轨迹或明确标注的校准事件模型。计算与传输只在同一时间轴上统计，不能将完整传输时长与完整计算时长直接相加。缺失项保持未知，不用 Figure 5 的单一例子填补所有请求的 profile。

先按均值评分选择候选，同分取较小深度和稳定计划 ID；仅当新方案的评分上界加切换余量仍低于 keep 下界时切换。不受支持的候选排除；generation 无效或 keep 的 profile 缺失、过期、漂移时冻结主动扩容/热集迁移，新请求尝试 DRAM 准入，失败再回退 R。已有驻留只能在仍满足预算与正确性时保持，不能阻止 Adapter 必要缩容。对同类可比操作连续出现相对误差超阈值时作废对应 profile generation；不把不可比观测当成验证。参数、条件样本、风险模型与校准版本必须作为配置记录。零故障概率时只剩 A，不能用恢复收益解释有正开销的扩容；零成本 keep 仍可保留。

算法 2：snapshot → 按 Slack 处理受影响请求 → 选 tier，仅为 D/P 申请 DRAM 并报告实际覆盖/失败 → 排热块 → 对每个 keep/depth 方案独立预演 → profile 与区间评分 → 稳定切换或可行回退 → 排保留/降级/换入计划 → 仅推进胜出快照 → 执行前原子核对预算与预留 → 发布真实提交与释放。预演不是物理预留，实际少于计划时报告并触发复核。

**正确性与证据。** 先恢复 selector 必需状态，保持原生选择不变；选择可指向 DRAM 中的历史 KV，也可包含已正确重建的尾部 KV。Connector 解析逻辑 ID、补取实际 miss 并返回就绪事件，attention 等齐全部必需输入才执行。预测影响传输/等待，不新增注意力近似。重放使用记录 token，不对已知尾部重新采样。批量 replay 只有在原生 selector 与状态演进满足逐 token 路径的声明数值契约时可用，否则采用原生逐 token 路径；prefill gate 或尚未解决的数值诊断不是该等价性的证明。Figure 5 的四条时间线与数值保持不变；它不校准本评分，不证明逐请求最优 L 或并发 WCT 收益。C 是 A100 80GB PCIe 上 batch=1、64-token forward 的 5 次中位数除以 32，并非逐层计时。6.25 GB/s 是 25 GB/s 链路被四路均分的假设；Peer 载荷为 7 × 0.65845 × 32 MiB = 147.49 MiB，未计辅助状态/临时缓冲。尾部就绪后仍有 38.69 ms 冷数据搬运，后续 TPOT 待测。

### 3.6 Adapter：窗口级容量与安全降级

Adapter 每个时间窗口发布目标 DP 的 Peer 总预算 Bp，窗口内目标不变但每次分配检查物理空间。预算为 KV pool 减去预测前台需求与准入余量，限制在 0 到 pool 一半之间。pool 排除了权重与固定运行时状态，包含现有 Peer 占用。Adapter 只调容量，不决定共同 L 或动态 Z。

**DRAM 也要准入。** 有限 backing pool 账本计入已提交对象、pending 预留、retiring 缓冲及必需元数据，共享对象只计一次。接纳 checkpoint 前先为缺失依赖闭包预留；活跃 checkpoint/reader 引用保护对象，零引用进入 LRU，等 I/O lease 归零才释放。新 manifest 提交前保留旧 manifest；完成或显式撤回备份承诺后可释放旧引用。分配/提交失败报告真实覆盖并使用旧 frontier 或 R，Peer 失败不代表 DRAM 自动成功。

**引用的权限。** 活跃请求引用防止其他请求抢占其 Peer 副本。所属请求可主动替换自己的热集或减小 L；请求结束（包括返回工具调用）释放自身引用。Adapter 为正常服务缩容时先回收无引用副本，仍不足则有权降级带请求引用的副本。I/O lease 则保护具体物理缓冲区，无论谁触发降级都不能越过正在进行的读写。

**提交与目录接口。** Connector/目录提供 reserve、commit、acquire/release lease、retire。Block ID 绑定模型/权重/布局、规范前缀身份、层、分片和密封区间；location generation 防止旧地址在复用后被误用。PENDING 不可读；只有所需层、分片、selector 状态和 token 日志在故障模型下可恢复时才推进 checkpoint frontier。Peer 与 DRAM 可以独立传输、独立提交，不声称跨路径原子提交。

每次退出 Peer 驻留的顺序固定为：

1. 确保同版本且可用于恢复的 DRAM 副本已经提交；已有有效副本则不重复回写。
2. 原子地把目录解析切换到 DRAM，并将旧 Peer generation 标为 retiring、关闭新 lease；持旧 lookup 的调用必须核对 generation 后重试。
3. 等待旧 generation 的读、写与 DMA lease 全部归零。
4. 释放物理 HBM 后才归还容量。

切换前若回写失败，保留旧 Peer；切换后新读走 DRAM，旧 lease 可以完成。请求逻辑 KV 没有被删除。元数据须在源故障后存活，失败源写入被 fencing；上述是实现契约而非已通过竞态验证的事实。

**缩容推进。** 超预算时停止新 Peer 预留。无引用安全副本不足时，由 Master 提供稳定的降级顺序：较大 Slack 优先，其次更深层、更低近期选中频次、稳定对象 ID；共享块按剩余 owner 的最小 Slack 保护。该顺序用于选 victim，不把独立迁移或 retry 串行化。降级后的覆盖与 K 返回 Master，不能马上把收回的额度填回。

缩容等待的是必要迁移和 I/O lease，而不是整个长 decode 结束。必要回写获得正的服务份额，但如果 DRAM 满、链路失效或显存余量耗尽，仍可能暂时超目标并阻塞前台物理准入，必须报告 pending bytes，不能宣称瞬时释放。窗口之间持续推进并核对未完成预留。

算法 3：窗口快照 → 估计前台需求 → Bp 截断 → 发布并限制新预留 → 先回收无引用 → 必要时选择带引用副本 → DRAM commit → 原子目录切换/关闭旧 lease → drain → 物理释放 → 发布实际覆盖与待处理字节。各对象异步推进，不等全体结束才允许其他 ready 请求运行。

**验证边界。** 尚需逐请求评分/profile 校准、故障风险与 Z 敏感性、真实 Agent Slack 误差、活跃热集迁移、并发公平性和前台干扰实验。必须覆盖迁移中故障、旧地址竞态、DRAM 容量不足、复制积压和共享带宽竞争。原生轨迹和单请求分析流水线不能代替这些实验；同源故障 DAG oracle、选择器重放等价性也需验证，保留零或负收益结果。


---

编辑记录（不进入论文）：本轮只压缩 System Design。旧完整正文、详细校准讨论及撤下的预算/足迹图引用保存在 [设计补充素材](supporting/design-full-20260918/README.md)，用于后续 Evaluation 或补充材料；本节原 Figure 6 顺次成为 Figure 5。两轮紧凑排版将 Figure 3 面板高度从 2.65 inch 经 2.05 inch 调为 1.85 inch，Figure 5 从 4.70 inch 经 3.40 inch 调为 3.05 inch；保留原宽度、字号与所有数据，分别继续采用三图跨双栏与单栏布局。

编辑记录（不进入论文）：原 3.4 与 3.5 合并为同一 KV Placement Planner 小节，按选块、确定层数、预算准入展开；Recovery Manager 和 Adapter 顺次成为 3.5、3.6。正文逐项引用 Figure 3(a)–(c)，流水线解释对应 Figure 5(a)–(d)。

编辑记录（不进入论文）：用户进一步澄清主要问题为 Figure 3/5 的图内字体过大；本轮改用与正文一致的 Linux Libertine，原生字号由 10.25/10.5 pt 调至 10.05 pt，Figure 5 仅面板字母加粗。图尺寸、数据、引用与小节结构保持上一轮结果。

编辑记录（不进入论文）：按用户确认，3.3 改为 GBDT 剩余时间预测与 CPM Slack 传播，并新增算法 1；原放置算法顺次成为算法 2。恢复代价与层级选择移入 3.4 Planner，角色 P90 不再作为当前 Tracker 的预测方法；图 3(a) 的 Median/P90 仍保留为原诊断基线。本轮补充的是论文算法规格，没有重新训练模型或验证端到端预测收益。

编辑记录（不进入论文，2026-09-18 最新职责调整）：3.4 Recovery Manager 在到达时绑定 retry 目标与 Peer DP rank；3.5 KV Master 决定备份触发、层级和候选热块；3.6 Adapter 按窗口控制总预算与实际层前缀。算法 2 改为备份策略输出，原整请求足迹全放或全不放改为 Adapter 按完整层前缀分配；Figure 5 的原有数据保留，仅将解释移入 Adapter。编号同步为 ① Tracker、② Recovery Manager、③ KV Master、④ Adapter。上述为论文设计规格更新，未将旧模拟器结果视为新策略验证。


编辑记录（不进入论文，2026-09-18 统一层数修订）：按用户确认，控制窗口设为 5 秒，所有 Agent 请求共用窗口内固定的 $L_t$；删除按请求求 $L_r(t)$ 并截短层前缀的分配。固定模型/稀疏方法预取比例 $h$，每层块数 $K_r(\tau)=\lceil h n_r(\tau)\rceil$ 随密封历史长度变化，块身份按热度替换。容量不足时按请求足迹准入或回退 DRAM。层数推导改为共享参考画像的窗口级选择，不保证各请求均达等待地板；本轮为论文规格更新，尚无对应端到端验证。

编辑记录（不进入论文，2026-09-18 故障风险驱动的 Adapter 修订）：§3.6 改为每 5 秒发布 checkpoint 间隔、统一层数和各目标预算的控制流程，新增算法 3，删除该节的闭式等待/字节/层数推导。故障风险来自较长统计周期，间隔调整受复制与前台开销约束；层数通过有限候选的画像比较选择。回收改为请求引用保护及零引用 LRU，预算下调逐步生效；§3.5 同步触发时机、候选与实际占用的区别。图 5 的原始文件和数字不变。本轮仅更新论文设计规格，尚未实现或验证新的控制器。

编辑记录（不进入论文，2026-09-19）：按用户要求，算法 3 及当前中英文正文统一使用“时间窗口”，不再将窗口长度固定为 5 秒；历史修订记录仅用于追溯。


编辑记录（2026-09-19 最新修订）：用户将层数改为逐请求调整，Adapter 仅调 Peer HBM 容量，并明确 Z 固定为系统配置。§3.5 和算法 2 由 KV Master 选择各自 L_r；§3.6 和算法 3 仅发布窗口级 B_p。撤回动态 Z 与统一 L 的控制职责；旧编辑记录保留历史含义。Figure 5 的单请求流水线移回 §3.5，数据不变。引用保护、零引用回收和 DRAM 回退继续适用。

编辑记录（2026-09-19 外部评审修订）：移除摘要未经验证的实验结论；K 改为逐层已提交 Peer 驻留块数，候选 quota 另行配置；允许 owner 热集更新和 Adapter 必要降级，明确 committed DRAM、目录 generation/lease 关闭、drain、物理释放顺序。补上深度评分、profile 接口与失效回退，明确并发恢复的公平服务与资源竞争。Figure 4 保留原生源和比例，改为本轮明确允许的双栏放置以达到 >=10 pt 普通标签；Figure 3/5 数据不变。尚未完成的实证不转写为已有结果。
