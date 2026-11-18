## 3 AegisKV Design

AegisKV 结合工作流的延迟容忍度与单请求的 KV 恢复需求：Tracker 估计 Slack；Recovery Manager 在请求到达时绑定接管目标；KV Master 决定保护层级及候选热块；Adapter 在每个时间窗口边界更新 checkpoint 间隔、所有请求共用的驻留层数和各目标 Peer 预算，并提交副本、执行恢复。下面先说明设计依据，再按模块给出决策与执行过程。

### 3.1 Insights 与设计启示

**Insight 1：执行上下文使 Agent 剩余工作量具有可预测性。** 已有方法利用任务语义与运行进度估计多轮 Agent 的剩余工作。[Heddle](https://arxiv.org/abs/2603.28101v1) 在第二步后，对 Coding、Search、Math Agent 剩余轨迹长度的预测相关系数约为 0.72、0.88、0.94，均优于第一步后的预测（图 3(a)）。[AgentDecarbonizer](https://arxiv.org/abs/2608.20566v1) 进一步展示了任务级执行时长估计与基于进度的剩余时间更新。AegisKV 使用这些已有能力，将剩余时间估计经 CPM 转换为工作流 Slack，驱动 KV 保护；预测器本身不是本系统的新贡献。图中的轨迹长度相关性支持可预测性，秒级时长仍需与具体模型、工具及部署条件匹配。

**Insight 2：稀疏注意力改变恢复时需要保护的对象。** 长上下文模型已采用 InfLLMv2、DSA 以及压缩/混合注意力。图 3(b) 的十个发布实例说明适用模型的存在，不代表市场采用率，也不意味着每层都使用相同的 Top-k。KV Master 接收真实的逐层选择与模型特定恢复状态，而不将所有历史 KV 字节视为等价。

**Insight 3：过去的选择能预测 retry 尾部所需历史 KV 的一部分。** 图 3(c) 中，两个策略均使用各模型历史 KV 字节数的 40%，历史频次覆盖 NOSA-3B、MiniCPM4-8B、SeerAttention-Qwen3-8B 所需 KV 的 77.8%、53.6%、43.0%，最近优先为 59.7%、50.9%、42.0%。Seer 在跨 head 取并集后需要约 92.5% 的历史块，该预算下即使预知需求的最优放置也只能覆盖约 43.3%。收益依赖模型与放置粒度且存在未命中，因此提前放置必须配合确切需求的补取。这些留出的书籍文本后缀不是 agentic 故障恢复实验。

<figure class="paper-figure">

[<img src="../figures/agent-time-literature/figure3-row.png" width="1008" alt="图 3 时间估计、稀疏模型与 retry KV 预测">](../figures/agent-time-literature/figure3-row.pdf)

**图 3：设计依据。** (a) 改绘自 Heddle Figure 13（arXiv:2603.28101v1，第 10 页），展示 Qwen3-14B 在第一、第二个 Agent 步骤之后预测剩余轨迹长度的 Pearson 相关系数。数值从原始矢量图读取，属于文献报告结果；不是 AegisKV 的秒级时长误差或复现实验。数据来源见[预测能力说明](../figures/agent-time-literature/README.md)。(b) 发布/模型仓库日期与原生上下文；编号 1–10 对应 MiniCPM4、MiniCPM4.1、DeepSeek-V3.2-Exp、DeepSeek-V3.2、GLM-5、MiniCPM-SALA、DeepSeek-V4 preview、MiniMax-M3、GLM-5.2、LongCat-Flash-Lite-Sparse。灰线仅为入选版本的最大上下文，marker 表示稀疏分支中块、token 或压缩项的 Top-k 选择。(c) 每模型 3 份原生 PG19 捕获，32K 历史；Query 32,257–32,768 预测 32,769–32,832 的去重历史需求。对象为包含所有 KV heads 的逐层 64-token 块，强制块包含在 40% 预算内；Seer 为 Qwen3-8B 加载[公开的实验性 Prefill gate](https://huggingface.co/jiwonsong/SeerAttention-Qwen3-8B-AttnGates)，阈值为 0.001，关闭末尾 Query 块强制 dense 的可选配置。柱与误差线为文档均值与范围。完整来源见[图像说明](../figures/design-insights/README.md)。

</figure>

### 3.2 System Overview

图 4 分为应用、控制面和推理引擎。应用上报 request/workflow 标识与 DAG 更新；Router 按负载及 KV 局部性分发；AegisKV Controller 维护 Slack、恢复目标和备份策略。DP0 与 DP1 各有 Adapter、Connector、Local KV 和较小的 Peer 区。KV Master 决定备份策略，各 Adapter 协调 checkpoint 间隔和统一层数、控制本地 Peer 预算，并调用 Connector 执行复制；KV 直接在引擎与存储间传输。黑底编号只索引下文模块，不表示执行顺序。

<figure class="paper-figure">

[<img src="../figures/system-overview-v11.drawio.png" width="480" alt="图 4 AegisKV 三层架构">](../figures/system-overview-v11.drawio.pdf)

**图 4：AegisKV Overview。** ① Tracker、② Recovery Manager、③ KV Master、④ Adapter 各标一次；到达时绑定恢复目标，备份策略下发至 Adapter，Peer 容量和层数逐窗口调整；两侧 DP 能力相同。Peer 与 DRAM 路径独立提交，内存比例和块布局为示意。图源：[Draw.io](../figures/system-overview-v11.drawio)。

</figure>

Recovery Manager 在请求到达时记录 retry 目标及 Peer DP rank（§3.4）；KV Master 在请求/KV/Slack 事件及控制窗口更新备份策略（§3.5）；Adapter 在每个时间窗口边界更新 checkpoint 间隔、统一层数和目标容量（§3.6）。目录与提交元数据保存在源故障域之外。

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

### 3.5 KV Master：备份时机与层级决策 ③

KV Master 决定请求何时需要备份、采用 Recompute/DRAM/Peer 中哪种保护方式，以及哪些历史块是 Peer 候选。它使用 Recovery Manager 已绑定的目标；Adapter 提供窗口级 checkpoint 间隔、统一层数和容量约束（§3.6）。

**何时决策。** 请求到达时先建立策略，prefill 完成后提供首批密封状态，之后每增加 $Z$ 个生成 token 复核该请求；$Z$ 由 Adapter 按 时间窗口发布。块密封只更新候选资格，不再独自触发每次备份。显著 Slack 或 DAG 变化及窗口更新可以提前复核策略。请求完成后释放其 Peer 引用，保留其他请求的共享引用；策略未变则不重复传输。热块统计采用此前 512 个解码步，与 token checkpoint 间隔和墙钟控制窗口分别计量。

**选择保护层级。** 设 $T_{\mathrm{rc}}$ 为历史重算代价，$T_{\mathrm{rp}}$ 为已知尾部重放计算代价，$W_0$ 为无 Peer 时暴露的 DRAM 等待；$R_{\mathrm{floor}}$ 包含检测、重路由与准入。Master 使用

$$R_{\mathrm{base}}=R_{\mathrm{floor}}+T_{\mathrm{rp}},\qquad R_R=R_{\mathrm{base}}+T_{\mathrm{rc}},\qquad R_D=R_{\mathrm{base}}+W_0.$$

代价按模型、上下文、尾长、设备和代表性并发校准；相关恢复画像用于 §3.6 的窗口控制。若 $\sigma_r\ge R_R$，请求为 **Tier R**，计划无需备份，故障后重算；否则若 $\sigma_r\ge R_D$，为 **Tier D**，保留 DRAM；其余为 **Tier P**，保留 DRAM 并申请 Peer HBM 保护。层级切换在上述名义边界周围采用 20% 滞回。Peer 是额外的快速副本，实际驻留由 Adapter 回报；没有取得 Peer 配额的 Tier P 请求仍走 DRAM。Slack 决定竞争 Peer 的请求顺序，不缩放每层热集，也不规定串行 retry 顺序。

**定义与选择保护对象。** 对象为包含全部 KV heads 的 `(layer, block)`；当前画像使用 64-token 块。写满密封后才可复制，但故障后的可用前缀以提交前沿为准；未提交的密封块和活跃尾部使用故障前已知的 token ID 重放，不重新采样。

第 $l$ 层长度 $n$ 重放需要的历史块并集为 $U_l(n)=\bigcup_{q=1}^{n}\bigcup_g S_{l,q,g}$，$S$ 为原生选择器输出，重复读取只计一块。根据模型和稀疏注意力方式的重放画像配置固定预取比例 $h$；它不随请求长度调整，也不等于原生选择器每次的 Top-k 比例或保证命中率。时刻 $\tau$，请求 $r$ 每层有 $n_r(\tau)$ 个已密封历史块，则每层候选热块数量为

$$K_r(\tau)=\lceil h n_r(\tau)\rceil.$$

Master 先将强制密封起始/窗口块计入该名额，配置须能容纳这些强制块；再按 Adapter 上报的实际选择频次填满剩余槽，同频时最近优先。可选旧块连续两个解码统计窗口跌出热集后移出候选；若旧副本仍有请求引用，新候选必须另外申请容量，不能仅因热度变化就复用旧副本的物理槽。

Adapter 在每个时间窗口内对所有请求使用相同的 $L$。同质层布局下，一个请求的 Peer 候选集合包含 $LK_r(\tau)$ 个逻辑 (layer, block) 对象及必需选择器状态。历史块密封且取整结果改变时才增加候选数量，无需重新求层数；热块身份可在候选数量不变时更新。D/P 两类都保留逐层热集作为恢复预取提示，P 类请求申请前 $L$ 层热集的 Peer 驻留。实际覆盖可以不完整，已被引用的旧副本仍需计账并等待安全释放。

**算法 2：KV 备份策略**

```text
Input: live requests, Slack, profiles, counts, target ranks pr
Output: desired DRAM set Ds, hot sets H, and ordered Peer candidates Qp
1  Ds, H ← ∅; Qp ← [] for each target p
2  for r in (Slack, stable request ID) order:
3      τr ← Tier(r, RR, RD, σr)
4      if τr = R: continue
5      Ds ← Ds ∪ sealed(r) ∪ state(r)
6      Hr,l ← HotSet(r, l, Kr) for each layer l
7      if τr = D: continue
8      append (r, {Hr,l}, profile(r)) to Qpr
9  return Ds, H, {Qp}
```

`Tier` 对已有层级应用滞回，到达时使用名义阈值。算法展示全量策略刷新；token 间隔事件只更新受影响请求的期望策略，其余保留。输出尚不代表可读副本；$n$ 个请求的排序为 $O(n\log n)$，共享物理对象在分配时去重。Adapter 对策略变化和已提交副本执行差量更新，并回报实际驻留、提交状态及下次策略刷新所需的装载估计。

### 3.6 Adapter：逐窗口保护控制 ④

Adapter 根据故障风险和正常推理的内存需求调整保护强度。在每个**时间窗口边界**发布下一窗口的三个参数：以生成 token 数计量的 checkpoint 触发间隔 $Z$、所有请求共用的 Peer 目标层数 $L$，以及各目标 DP 的 Peer 总容量 $B_p$。Controller 汇总各 Adapter 的状态，为同一部署模型发布共同的 $Z$ 和 $L$，窗口内不变，新到请求也使用当前值。实际分配仍需检查即时空闲空间。KV Master 在这些参数下决定请求的保护层级、候选块和准入顺序，Connector 执行传输。

**根据故障风险调整 checkpoint 频率。** Adapter 使用相关故障域中单位设备运行时间内的故障记录，得到较长统计周期上的平滑风险估计；观测不足时使用配置先验，不把最近一个时间窗口无故障等同于风险为零。风险升高时，更频繁的 checkpoint 可以减少故障后的丢失进度，但也增加正常备份开销。这一方向与经典 checkpoint 权衡一致（[Daly, 2006](https://doi.org/10.1016/j.future.2004.11.016)），具体间隔仍需按异步增量 KV 备份校准，不能直接套用阻塞式 checkpoint 的公式。

$Z$ 从配置的、与物理块大小对齐的离散档位中选择。风险高于上阈值，且复制积压、提交滞后及前台干扰均在允许范围内时，缩短一档；风险低于下阈值时，放宽一档；其余情况保持不变，并遵守最小、最大间隔。这样既响应风险变化，也避免拥塞时不断增加尚未完成的备份工作。

$Z$ 触发的是 KV Master 的一次决策，不代表副本已经完成。Master 在 prefill 完成后提供首批密封状态，之后每增加 $Z$ 个生成 token 重新决策。窗口发布新 $Z$ 时不清零请求已有的进度计数。故障时真正需要重放的尾部，是已知 token 前缀超出最新有效提交前沿的部分；异步排队可以使其超过 $Z$，Tier R 则可以不做 checkpoint。因此，Adapter 同时观察决策频率和实际提交滞后。

**先为正常推理保留容量。** 每个目标 DP 从可管理 KV 池中扣除下一窗口的前台 KV 需求估计及准入余量，将剩余量作为 Peer 预算，最少为零、最多为整个 KV 池的一半。这里的 KV 池已扣除模型权重和固定运行时开销，但包含现有 Peer 副本；$B_p$ 是总占用目标，不是新增空闲量。正常请求需要更多 KV 空间时缩减预算，压力持续下降时允许恢复。需求估计使用 KV 水位和由内存不足造成的准入等待，不能仅凭 GPU 计算利用率升高就缩减 Peer。

**结合新间隔选择统一层数。** 较小的 $Z$ 通常留下较短的重放尾部，可用于隐藏 DRAM 装载的计算较少，因此更多 Peer 层可能产生收益；较大的 $Z$ 则可能在较小 $L$ 处达到收益平台。但故障可能发生在 checkpoint 周期中的任意位置，而且相同预算下，增加每个请求的层数可能减少能够保护的请求数量。因此，Adapter 不将“风险升高”机械地转换成“增加一层”，而是按算法 3 比较少量候选层数。

恢复画像表按 checkpoint 间隔、历史长度、复制带宽、重放代价和并发情况组织，通过各间隔下的备份与恢复重放校准。表项覆盖按时间采样的 checkpoint 阶段及实际提交滞后，而不是假设故障总在第 $Z$ 个 token 发生；按阶段采样使用故障风险与 checkpoint 阶段近似独立的假设。在线用近期负载统计匹配并加权这些表项。

对每个候选 $L$，Adapter 在当前状态快照上预演 KV Master 的准入，计入共享对象、已有引用、在途复制和下一窗口的复制限额，只按预计能够提交的副本计算恢复收益。候选得分由两部分组成：内存挤占与备份工作引入的前台请求延迟，以及超出请求 Slack 的恢复延迟，后者按请求源在下一窗口内的故障概率加权，两者使用相同的窗口范围。选择得分最低的层数，同分时优先较小值；与新间隔、新预算下保留当前层数相比，只有改善超过配置的不确定性余量才切换，缺少适用画像时保持当前层数。该得分是请求延迟的决策代理，不能把它解释为可直接相加的 Workflow 完成时间损失。

**算法 3：逐窗口更新保护参数**

$Z$ 的档位边界、风险上下阈值、干扰上限、候选层数及切换余量均为部署配置。算法不需要知道下一次故障的时刻，也不为各请求分别求层数。

```text
Input: current settings, risk/load reports, recovery profiles
Output: next-window checkpoint interval Z, common depth L, budgets Bp

1  snapshot live requests, references, and copy progress
2  estimate failure risk from the longer-term history
3  for each target DP p:
4      Bp ← KV pool − foreground KV demand − admission headroom
5      clamp Bp between zero and half of the KV pool
6  next_Z ← Z; next_L ← L
7  if risk is high and copy/foreground guards allow:
8      next_Z ← next smaller allowed checkpoint interval
9  else if risk is low:
10     next_Z ← next larger allowed checkpoint interval
11 if profiles cover next_Z and current load:
12     for each candidate depth, including zero and current L:
13         preview admissions and expected committed coverage
14         score ← estimated foreground delay
15         add risk-weighted recovery delay beyond Slack
16     choose minimum score; break ties by smaller depth
17     if materially better: next_L ← chosen depth
18 publish next_Z, next_L, and Bp for the next window
19 pause excess admission; reclaim only safe copies
```

**按引用状态准入和回收。** KV Master 按 Slack 排序提出前 $L$ 层的热块候选，同 Slack 时使用稳定请求 ID。已有副本可以共享；新增副本必须同时满足预算和实际空间限制，在复制前预留容量。有压力时，只有引用数为零、没有在途读写且已有有效 DRAM 后备的对象可以进入 LRU 淘汰队列。空闲空间与安全可淘汰对象仍不足时，拒绝这部分 Peer 增量，保留请求的 DRAM 路径；正常推理不等待 Peer 准入，高优先级也不能撤销其他活跃请求的引用。

成功取得的 Peer 副本保留请求引用，直到本次 LLM 请求结束，包括返回外部 tool 调用的情况。请求结束后递减引用；共享对象要等所有引用释放才具备回收资格，引用归零不等于立即删除。热集增长或身份变化时，新增对象重新申请准入，已获准对象仍受保护。因此，每层候选数量是保护目标，既不保证当前热集完整驻留，也不是保留旧副本后的实际占用上限。

预算下调后，超过目标时暂停新的空间分配，先释放安全的零引用副本，其余随请求结束逐步回收；减小 $L$ 同样不撤销已有引用。实际占用可能暂时高于新目标，只有物理释放完成后，内存才真正归还正常推理。增大 $L$ 只增加候选范围，新副本仍受准入检查。复制中、已提交和回收中的字节在释放前持续计账，不能把参数发布当作复制或回收已经完成。

**按实际就绪状态提交和恢复。** Peer 与故障域外 DRAM 路径独立提交，传输完成并验证模型、布局和分片后才发布可读副本。低优先级复制流限速，默认不超过链路容量的 20%，同时核算目标 HBM 带宽。恢复只使用已提交对象：按层预取热块，新揭示的缺失块优先于推测性复制，选择器状态先于选择操作就绪，每层等待全部必需输入到齐。实际 DMA 粒度可能限制复制抢占，Tier R 重建历史。AegisKV 不改变选择器输出和已知重放 token；在兼容权重、布局与算子下恢复同一逻辑 KV，不引入新的注意力近似，但不保证不同浮点调度下后续随机采样逐 token 一致。

<figure class="paper-figure">

[<img src="../figures/design-single/design-layer-pipeline.png" width="480" alt="图 5 四种恢复流水线">](../figures/design-single/design-layer-pipeline.pdf)

**图 5：模型化恢复流水线。** MiniCPM4-8B，32 层、32K 历史、已知 64-token 尾部；每层 $C=2.87$ ms 来自测量，$D=5.37$ ms 对应假设的 6.25 GB/s 带宽。(d) 将 147 MiB 热集驻留 Peer；时间终点为尾部 KV 重建完成。模型采用同质层及理想可抢占复制流，不含检测、排队和干扰。

</figure>

图 5 在固定尾长下说明层数的作用：逐层流水线、热集预取和前七层热集驻留依次将暴露等待从 172 ms 降至 83、44 和 20 ms。这是一个校准画像，既不能验证自适应控制器，也不意味着不同 checkpoint 间隔都应选择七层。

**适用边界与验证。** 接入稀疏模型要求可观察索引、可恢复选择器状态及所有必需注意力分支，token 索引需映射到物理复制块。预测差时退化为逐层完整装载；稠密注意力使用完整历史集合（$h=1$），独立请求取零 Slack。Prefill 故障需按丢失 chunk 校准，不能套用固定 64-token 尾部。Agent 负载的 Slack 精度、画像漂移、同时 retry 与前台干扰仍需端到端验证，故障风险控制器还需校准不同 checkpoint 间隔的画像，并验证阈值、复制约束及引用释放滞后的影响；轨迹分析和流水线模型不能替代这些证据。

---

编辑记录（不进入论文）：本轮只压缩 System Design。旧完整正文、详细校准讨论及撤下的预算/足迹图引用保存在 [设计补充素材](supporting/design-full-20260918/README.md)，用于后续 Evaluation 或补充材料；本节原 Figure 6 顺次成为 Figure 5。两轮紧凑排版将 Figure 3 面板高度从 2.65 inch 经 2.05 inch 调为 1.85 inch，Figure 5 从 4.70 inch 经 3.40 inch 调为 3.05 inch；保留原宽度、字号与所有数据，分别继续采用三图跨双栏与单栏布局。

编辑记录（不进入论文）：原 3.4 与 3.5 合并为同一 KV Placement Planner 小节，按选块、确定层数、预算准入展开；Recovery Manager 和 Adapter 顺次成为 3.5、3.6。正文逐项引用 Figure 3(a)–(c)，流水线解释对应 Figure 5(a)–(d)。

编辑记录（不进入论文）：用户进一步澄清主要问题为 Figure 3/5 的图内字体过大；本轮改用与正文一致的 Linux Libertine，原生字号由 10.25/10.5 pt 调至 10.05 pt，Figure 5 仅面板字母加粗。图尺寸、数据、引用与小节结构保持上一轮结果。

编辑记录（不进入论文）：按用户确认，3.3 改为 GBDT 剩余时间预测与 CPM Slack 传播，并新增算法 1；原放置算法顺次成为算法 2。恢复代价与层级选择移入 3.4 Planner，角色 P90 不再作为当前 Tracker 的预测方法；图 3(a) 的 Median/P90 仍保留为原诊断基线。本轮补充的是论文算法规格，没有重新训练模型或验证端到端预测收益。

编辑记录（不进入论文，2026-09-18 最新职责调整）：3.4 Recovery Manager 在到达时绑定 retry 目标与 Peer DP rank；3.5 KV Master 决定备份触发、层级和候选热块；3.6 Adapter 按窗口控制总预算与实际层前缀。算法 2 改为备份策略输出，原整请求足迹全放或全不放改为 Adapter 按完整层前缀分配；Figure 5 的原有数据保留，仅将解释移入 Adapter。编号同步为 ① Tracker、② Recovery Manager、③ KV Master、④ Adapter。上述为论文设计规格更新，未将旧模拟器结果视为新策略验证。


编辑记录（不进入论文，2026-09-18 统一层数修订）：按用户确认，控制窗口设为 5 秒，所有 Agent 请求共用窗口内固定的 $L_t$；删除按请求求 $L_r(t)$ 并截短层前缀的分配。固定模型/稀疏方法预取比例 $h$，每层块数 $K_r(\tau)=\lceil h n_r(\tau)\rceil$ 随密封历史长度变化，块身份按热度替换。容量不足时按请求足迹准入或回退 DRAM。层数推导改为共享参考画像的窗口级选择，不保证各请求均达等待地板；本轮为论文规格更新，尚无对应端到端验证。

编辑记录（不进入论文，2026-09-18 故障风险驱动的 Adapter 修订）：§3.6 改为每 5 秒发布 checkpoint 间隔、统一层数和各目标预算的控制流程，新增算法 3，删除该节的闭式等待/字节/层数推导。故障风险来自较长统计周期，间隔调整受复制与前台开销约束；层数通过有限候选的画像比较选择。回收改为请求引用保护及零引用 LRU，预算下调逐步生效；§3.5 同步触发时机、候选与实际占用的区别。图 5 的原始文件和数字不变。本轮仅更新论文设计规格，尚未实现或验证新的控制器。

编辑记录（不进入论文，2026-09-19）：按用户要求，算法 3 及当前中英文正文统一使用“时间窗口”，不再将窗口长度固定为 5 秒；历史修订记录仅用于追溯。
