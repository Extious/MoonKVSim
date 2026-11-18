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

### 3.4 Recovery Manager：预定接管目标 ②

Recovery Manager 在故障前决定每个请求的恢复去向。请求 $r$ 到达、Router 选定源 DP rank $g_r$ 后，Manager 将目标 $p_r\ne g_r$ 记录到源故障域之外的控制状态。**同一个 $p_r$ 同时是故障后的 retry 目标和该请求 Peer HBM 所在的 DP rank**。例如 $n\ge2$ 个 DP 可采用 $p_r=(g_r+1)\bmod n$，也可以按请求将负载分散到多个预定目标。绑定目标本身不预留 HBM：是否申请 Peer 保护由 KV Master 决定，实际容量由目标 Adapter 控制。TP 组按兼容分片作为一个 DP 恢复。

**故障后激活既定路由。** Manager 综合成员状态、设备错误及 Adapter 上报的 GPU 进度，进程心跳不能独自证明 GPU 正常。确认并隔离失效源后，从存活控制状态取得 token 前缀、提交前沿、模型/布局标识及副本位置，向记录的目标提交 retry。目标可以直接读取本地已提交 Peer 副本，其余状态通过 DRAM 或重算恢复。控制状态存活、写隔离、故障域分离和重试去重是运行时契约。若预定目标本身失效，需建立新的有效绑定，不能把旧目标上的副本当作新目标的本地副本。

各请求独立进入恢复，仍受前台准入、连续批处理及共享计算/复制容量约束，并依据自身逐层就绪事件推进。放置优先级不产生请求级完成屏障，Manager 不因某请求 Slack 较小而等待它恢复完才提交下一个。

### 3.5 KV Master：逐请求备份与层数决策 ③

KV Master 在备份决策时选择请求的 Recompute/DRAM/Peer 保护层级、各自的目标层数 $L_r$ 和候选热块。Recovery Manager 已在请求到达时绑定 retry/Peer 目标；Adapter 只提供目标 DP 的窗口级容量预算（§3.6）。同一容量窗口内，不同请求的 $L_r$ 可以不同。

**何时决策。** 请求到达时建立策略，prefill 完成后提供首批密封状态，之后每增加 $Z$ 个生成 token 复核该请求。$Z$ 是与物理块大小对齐的固定系统配置，既不由 Adapter 调整，也不随故障率在线变化。显著 Slack/DAG 变化、预算更新，以及历史长度或复制条件的实质变化，可以提前触发策略复核；块密封只更新候选资格，不要求每生成一个 token 就重新求 $L_r$。请求结束后释放其 Peer 引用并保留其他请求的共享引用；策略不变则不重复传输。热块统计使用此前 512 个解码步，与 checkpoint 和容量控制窗口独立计量。

checkpoint 触发一次决策，不代表复制已经提交。实际尾部 $N_r$ 是已知 token 前沿超出最新有效提交前沿的部分；异步排队可使它超过 $Z$。Master 使用实际提交进度估计尾部；Tier R 可以不做 checkpoint。

**选择保护层级。** 设 $T_{\mathrm{rc}}$ 为历史重算代价，$T_{\mathrm{rp}}$ 为已知尾部重放计算代价，$W_0$ 为无 Peer 时暴露的 DRAM 等待；$R_{\mathrm{floor}}$ 包含检测、重路由与准入。Master 使用

$$R_{\mathrm{base}}=R_{\mathrm{floor}}+T_{\mathrm{rp}},\qquad R_R=R_{\mathrm{base}}+T_{\mathrm{rc}},\qquad R_D=R_{\mathrm{base}}+W_0.$$

代价按模型、已提交历史、尾长、设备与代表性并发联合建模。若 $\sigma_r\ge R_R$，请求为 **Tier R**，计划无需备份、故障后重算；否则若 $\sigma_r\ge R_D$，为 **Tier D**，保留 DRAM；其余为 **Tier P**，保留 DRAM 并申请 Peer 保护。层级切换在上述名义边界周围采用 20% 滞回。没有 Peer 准入的 Tier P 请求仍走 DRAM。Slack 决定竞争顺序，不缩放每层热集比例，也不规定串行 retry 顺序。

**定义与选择保护对象。** 对象为包含全部 KV heads 的 (layer, block)；当前画像使用 64-token 块。密封后才可复制，但故障可用前缀以提交前沿为准。未提交的密封块与活跃尾部使用已知 token ID 重放，不重新采样。

第 $l$ 层长度 $n$ 重放所需的历史块并集为 $U_l(n)=\bigcup_{q=1}^{n}\bigcup_g S_{l,q,g}$，$S$ 为原生选择器输出，重复读取只计一块。按模型及稀疏方式配置固定预取比例 $h$；它不等于每次选择的 Top-k 比例或保证命中率。时刻 $\tau$，请求 $r$ 每层有 $n_r(\tau)$ 个密封历史块，则每层热块候选数为

$$K_r(\tau)=\lceil h n_r(\tau)\rceil.$$

强制密封起始/窗口块计入该名额，配置须能容纳它们；剩余槽按实际选择频次填充，同频时最近优先。可选旧块连续两个解码统计窗口跌出热集后移出候选；仍被引用的旧副本不能仅因热度变化就复用物理槽，替换块需要新准入。

**为每个请求选择层数。** Master 在策略事件中根据该请求的已提交历史 $M_r$、生成进度、Slack 和恢复画像复核 $L_r$。传输字节与重放计算均随上下文变化，按需未命中也可随尾长变化。对于每个候选深度，使用相同的请求增长轨迹和可能故障状态，平均未来 checkpoint 阶段及提交滞后的代价；不把当前 $N_r$ 或 $N=Z$ 当成确定的未来故障状态。

请求按 Slack 排序逐个处理。对请求 $r$，比较包含零和当前深度的少量配置候选；所有候选从相同的目标状态快照预演增量准入，计入共享副本、已有引用、在途预留和复制限额。恢复估计只计预计能提交的覆盖，也计入仍然保留的旧副本。得分由候选的备份工作/内存占用引入的前台延迟，以及超出该请求 Slack 的恢复延迟组成，后者按配置风险模型中同一策略时间范围内的源故障概率加权。这是 Slack 优先级下的局部决策代理，不是全局最优，也不是可直接相加的 Workflow 完成时间。

选择最低得分，同分优先较小深度；已有目标只有在改善超过配置的不确定性余量时才改变。缺少适用画像时保留已有目标，新请求从零 Peer 深度和 DRAM 保护开始。仅将胜出候选的计划加入虚拟快照，再评估下一请求；实际分配仍需原子复核空间，可能少于预演覆盖。

同质层下，P 类请求的目标为前 $L_r$ 层热集，即 $L_rK_r(\tau)$ 个逻辑层块对象及必需状态；R/D 的目标深度为零。$L_r$ 在策略事件之间保持，候选块数随密封历史增长；D/P 都保留逐层热集用于恢复预取。实际 Peer 覆盖可以不完整，减小 $L_r$ 不撤销旧副本引用。

**算法 2：逐请求 KV 备份策略**

~~~text
Input: requests, Slack, profiles, targets, budgets, copy state
Output: desired DRAM set Ds, depths {Lr}, ordered Peer plans {Qp}
1  Ds, H ← ∅; Qp ← [] for each target p
2  snapshot retained copies and reserved capacity as S
3  for r in (Slack, stable request ID) order:
4      τr ← Tier(r, RR, RD, σr)
5      if τr = R: Lr ← 0; continue
6      add sealed(r) and state(r) to Ds
7      Hr,l ← HotSet(r, l, Kr) for each layer
8      if τr = D: Lr ← 0; continue
9      for each candidate depth d, including zero and current Lr:
10         Gd ← Preview(S, r, Hr,1:d)
11         score profiled costs; mark missing profiles unknown
12     Lr ← StableBest(r, {Gd})
13     append (r, Lr, Hr,1:Lr, GLr) to Qpr
14     update S with the chosen plan only
15 return Ds, H, {Lr}, {Qp}
~~~

算法展示全量刷新；token 间隔事件只更新受影响请求，保留其他策略和预留。Tier 对已有层级应用滞回；StableBest 实现切换余量和画像不足时的回退。虚拟快照不等于真实空间预留。排序为 $O(n\log n)$，随后进行有限候选扫描；物理分配去重共享对象，按策略执行差量复制并反馈实际驻留和提交进度。

**按实际就绪状态提交和恢复。** Peer 与故障域外 DRAM 独立提交，在传输完成并验证模型、布局和分片后发布可读副本。低优先级复制流默认限制在链路容量的 20%，同时核算目标 HBM 带宽。恢复只读已提交对象：逐层预取热块，新揭示的缺失块优先于推测性复制，选择器状态先于选择操作就绪；每层等待全部必需输入到齐。实际 DMA 粒度可能限制复制抢占，Tier R 重建历史。放置不改变选择器输出或已知重放 token；兼容权重、布局与算子恢复同一逻辑 KV，不引入新的注意力近似，但不保证不同浮点调度下后续随机采样逐 token 一致。

<figure class="paper-figure">

[<img src="../figures/design-single/design-layer-pipeline.png" width="480" alt="图 5 四种恢复流水线">](../figures/design-single/design-layer-pipeline.pdf)

**图 5：模型化恢复流水线。** MiniCPM4-8B，32 层、32K 历史、已知 64-token 尾部；每层 $C=2.87$ ms 来自测量，$D=5.37$ ms 对应假设的 6.25 GB/s 带宽。(d) 将 147 MiB 热集驻留 Peer；时间终点为尾部 KV 重建完成。模型采用同质层及理想可抢占复制流，不含检测、排队和干扰。

</figure>

图 5 在固定尾长下说明层数的作用：逐层流水线、热集预取和前七层热集驻留依次将暴露等待从 172 ms 降至 83、44 和 20 ms。这是一个校准画像，不能验证逐请求深度选择，也不能推出所有请求都应保护七层。

### 3.6 Adapter：逐窗口 Peer 容量控制 ④

Adapter 的自适应输出只有每个目标 DP 的 Peer HBM 总预算 $B_p$。它在**时间窗口边界**发布下一窗口预算，窗口内目标不变，每次实际分配仍检查即时空间。KV Master 负责固定 $Z$ 下的备份决策、请求层级和各自的 $L_r$；同一容量窗口内，不同请求的层数可以不同，也可在策略事件中更新。

**先为正常推理保留容量。** 从可管理 KV 池中扣除下一窗口的前台 KV 需求估计及准入余量，将剩余量作为 Peer 预算，最少为零、最多为 KV 池的一半。池已扣除模型权重和固定运行时开销，但包含现有 Peer 副本；$B_p$ 是总占用目标，不是新增空闲量。需求根据 KV 水位与内存不足造成的准入等待估计，不仅依赖 GPU 计算利用率。前台需求增加时缩减 Peer 目标，压力持续下降时允许扩张。Adapter 上报实际空闲、引用中、复制中及可回收字节，供 Master 评估各请求计划。

**算法 3：逐窗口更新 Peer 预算**

~~~text
Input: KV pool, foreground demand, headroom, copy state
Output: next-window total Peer budget Bp for each target
1  for each target DP p at the window boundary:
2      snapshot pool, occupancy, references, and copies
3      estimate next-window foreground KV demand
4      Bp ← pool − demand − admission headroom
5      clamp Bp between zero and half of the pool
6      publish Bp and capacity state to KV Master
7      pause new space reservations above the budget
8      reclaim safe zero-reference copies as needed
9      count bytes until physical release completes
~~~

**按引用状态准入和回收。** Master 按 Slack 顺序提出各请求前 $L_r$ 层热块，同 Slack 时使用稳定 ID。已有副本可以共享；新增对象在复制前必须取得预算和真实空间预留。压力下只有引用为零、无在途读写、已有有效 DRAM 后备的对象进入 LRU 淘汰队列。空闲与安全可回收空间仍不足时，拒绝 Peer 增量，保留 DRAM 路径；正常推理不等待 Peer，高优先级不能撤销活跃引用。

成功取得的副本保留请求引用，直到该次 LLM 请求结束，包括返回外部 tool 调用的情况。共享引用全部释放后才可回收，归零不等于立即删除。热集增长或替换需要新准入，旧副本仍计账，因此候选数不保证当前热集完整驻留，也不是保留旧副本后的占用上限。

预算下调后，超过目标时暂停新空间预留并先释放安全副本，其余随请求结束逐步回收；减小请求的 $L_r$ 同样不撤销已有引用。实际占用可暂时超过新目标，只有物理释放完成后才归还前台。增大 $L_r$ 增加候选范围，新对象仍需准入。复制中、已提交与回收中的字节在物理释放前持续计账。

**范围与验证。** 稀疏接入需可观测索引、可恢复的选择器状态和全部必需注意力分支，并将 token 选择映射到物理块。热度不准时可退回完整层装载，稠密注意力取 $h=1$。独立请求取零 Slack，prefill 故障按丢失 chunk 校准。逐请求 $M_r,N_r$ 联合画像、深度切换、竞争准入、预算预测和引用释放滞后仍需验证；轨迹分析与单请求流水线不能替代这些证据。

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
