## 3 AegisKV Design

AegisKV 结合工作流的延迟容忍度与单请求的 KV 恢复需求：Tracker 估计 Slack；Recovery Manager 在请求到达时绑定接管目标；KV Manager 决定保护层级及候选热块；Adapter 按时间窗口控制 Peer 容量和驻留层数，并提交副本、执行恢复。下面先说明设计依据，再按模块给出决策与执行过程。

### 3.1 Insights 与设计启示

**Insight 1：从工作流进度估计延迟容忍度，但时间估计前提仍需验证。** 重复角色提供历史画像的基础，但多轮 agent 时长还包含工具与服务延迟。图 3(a) 的 CC 轨迹按 workflow 隔离预测中，进度 GBDT 的归一化误差中位数为 51.8%，持续时间中位数基线为 49.3%；角色标签全部为 `Subagent`，尚不能证明按角色准确预测。算法 1 将 GBDT 时间预测与 CPM Slack 传播分开；这一诊断尚未验证完整 Tracker 及其保护决策。

**Insight 2：稀疏注意力改变恢复时需要保护的对象。** 长上下文模型已采用 InfLLMv2、DSA 以及压缩/混合注意力。图 3(b) 的十个发布实例说明适用模型的存在，不代表市场采用率，也不意味着每层都使用相同的 Top-k。KV Manager 接收真实的逐层选择与模型特定恢复状态，而不将所有历史 KV 字节视为等价。

**Insight 3：过去的选择能预测 retry 尾部所需历史 KV 的一部分。** 图 3(c) 中，两个策略均使用各模型历史 KV 字节数的 40%，历史频次覆盖 NOSA-3B、MiniCPM4-8B、SeerAttention-Qwen3-8B 所需 KV 的 77.8%、53.6%、43.0%，最近优先为 59.7%、50.9%、42.0%。Seer 在跨 head 取并集后需要约 92.5% 的历史块，该预算下即使预知需求的最优放置也只能覆盖约 43.3%。收益依赖模型与放置粒度且存在未命中，因此提前放置必须配合确切需求的补取。这些留出的书籍文本后缀不是 agentic 故障恢复实验。

<figure class="paper-figure">

[<img src="../figures/design-insights/design-insights-row.png" width="1008" alt="图 3 时间估计、稀疏模型与 retry KV 预测">](../figures/design-insights/design-insights-row.pdf)

**图 3：设计依据。** (a) 174 个 workflow、1,688 个 CC agent 的五折预测，workflow 不跨折；每个 agent 的样本为平均绝对剩余时间误差除以总时长，对称对数轴保留全部误差；Median/P90 为持续时间先验。(b) 发布/模型仓库日期与原生上下文；编号 1–10 对应 MiniCPM4、MiniCPM4.1、DeepSeek-V3.2-Exp、DeepSeek-V3.2、GLM-5、MiniCPM-SALA、DeepSeek-V4 preview、MiniMax-M3、GLM-5.2、LongCat-Flash-Lite-Sparse。灰线仅为入选版本的最大上下文，marker 表示稀疏分支中块、token 或压缩项的 Top-k 选择。(c) 每模型 3 份原生 PG19 捕获，32K 历史；Query 32,257–32,768 预测 32,769–32,832 的去重历史需求。对象为包含所有 KV heads 的逐层 64-token 块，强制块包含在 40% 预算内；Seer 为 Qwen3-8B 加载[公开的实验性 Prefill gate](https://huggingface.co/jiwonsong/SeerAttention-Qwen3-8B-AttnGates)，阈值为 0.001，关闭末尾 Query 块强制 dense 的可选配置。柱与误差线为文档均值与范围。完整来源见[图像说明](../figures/design-insights/README.md)。

</figure>

### 3.2 System Overview

图 4 分为应用、控制面和推理引擎。应用上报 request/workflow 标识与 DAG 更新；Router 按负载及 KV 局部性分发；AegisKV Controller 维护 Slack、恢复目标和备份策略。DP0 与 DP1 各有 Adapter、Connector、Local KV 和较小的 Peer 区。KV Manager 决定备份策略，各目标 Adapter 控制本地 Peer 容量和层数，并调用 Connector 执行复制；KV 直接在引擎与存储间传输。黑底编号只索引下文模块，不表示执行顺序。

<figure class="paper-figure">

[<img src="../figures/system-overview-v11.drawio.png" width="480" alt="图 4 AegisKV 三层架构">](../figures/system-overview-v11.drawio.pdf)

**图 4：AegisKV Overview。** ① Tracker、② Recovery Manager、③ KV Manager、④ Adapter 各标一次；到达时绑定恢复目标，备份策略下发至 Adapter，Peer 容量和层数逐窗口调整；两侧 DP 能力相同。Peer 与 DRAM 路径独立提交，内存比例和块布局为示意。图源：[Draw.io](../figures/system-overview-v11.drawio)。

</figure>

Recovery Manager 在请求到达时记录 retry 目标及 Peer DP rank（§3.4）；KV Manager 在请求/KV/Slack 事件及控制窗口更新备份策略（§3.5）；目标 Adapter 每窗口更新容量和驻留层前缀（§3.6）。目录与提交元数据保存在源故障域之外。

### 3.3 Workflow Tracker：GBDT 与 CPM ①

Tracker 先用 GBDT 预测 agent 剩余执行时间，再用关键路径法（CPM）计算 Slack，过程见算法 1。在时刻 $t$，残余 DAG $G_t=(V_t,E_t)$ 的节点是尚未完成的 **agent 执行段**：每段包含依赖屏障之间的连续多轮请求；父 agent 在分叉/汇合处拆段，避免将子 agent 的执行时间重复计为父 agent 的等待时间。已完成的段移除，每个活跃请求 $r$ 映射至所属执行段 $a(r)$。

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

**传播并更新 Slack。** 活跃请求继承所属执行段的 $\sigma_r=\max(0,\mathrm{LF}_{a(r)}-\mathrm{EF}_{a(r)})$；同段请求共享这份余量，不能将其视为每个请求可独立累加的延迟预算。请求到达/完成、DAG 更新和放置窗口触发重算，CPM 的复杂度为 $O(|V_t|+|E_t|)$。若依赖结构尚不明确或预测不可用，该 workflow 的 Slack 取零；已知但尚未完成的前驱正常参与 CPM。这是规划估计，不是延迟保证；图 3(a) 是 agent episode 的预测诊断，尚未验证完整 Tracker。

### 3.4 Recovery Manager：预定接管目标 ②

Recovery Manager 在故障前决定每个请求的恢复去向。请求 $r$ 到达、Router 选定源 DP rank $g_r$ 后，Manager 将目标 $p_r\ne g_r$ 记录到源故障域之外的控制状态。**同一个 $p_r$ 同时是故障后的 retry 目标和该请求 Peer HBM 所在的 DP rank**。例如 $n\ge2$ 个 DP 可采用 $p_r=(g_r+1)\bmod n$，也可以按请求将负载分散到多个预定目标。绑定目标本身不预留 HBM：是否申请 Peer 保护由 KV Manager 决定，实际容量由目标 Adapter 控制。TP 组按兼容分片作为一个 DP 恢复。

**故障后激活既定路由。** Manager 综合成员状态、设备错误及 Adapter 上报的 GPU 进度，进程心跳不能独自证明 GPU 正常。确认并隔离失效源后，从存活控制状态取得 token 前缀、提交前沿、模型/布局标识及副本位置，向记录的目标提交 retry。目标可以直接读取本地已提交 Peer 副本，其余状态通过 DRAM 或重算恢复。控制状态存活、写隔离、故障域分离和重试去重是运行时契约。若预定目标本身失效，需建立新的有效绑定，不能把旧目标上的副本当作新目标的本地副本。

各请求独立进入恢复，仍受前台准入、连续批处理及共享计算/复制容量约束，并依据自身逐层就绪事件推进。放置优先级不产生请求级完成屏障，Manager 不因某请求 Slack 较小而等待它恢复完才提交下一个。

### 3.5 KV Manager：备份时机与层级决策 ③

KV Manager 决定请求何时需要备份、采用 Recompute/DRAM/Peer 中哪种保护方式，以及哪些历史块是 Peer 候选。它使用 Recovery Manager 已绑定的目标；目标 Adapter 负责实际容量和驻留层数（§3.6）。

**何时决策。** 请求到达时先建立策略，此时尚无可复制的 KV。块密封、显著 Slack 或 DAG 变化、请求完成以及每个控制窗口（默认 1 s）都会触发受影响请求的策略复核。密封增加可复制对象；请求完成移除其保护需求，但保留其他请求仍需要的共享对象。策略未变则不重复传输。热块统计采用此前 512 个解码步，与按墙钟时间划分的控制窗口分别计量。

**选择保护层级。** 设 $T_{\mathrm{rc}}$ 为历史重算代价，$T_{\mathrm{rp}}$ 为已知尾部重放计算代价，$W_0$ 为无 Peer 时暴露的 DRAM 等待；$R_{\mathrm{floor}}$ 包含检测、重路由与准入。Manager 使用

$$R_{\mathrm{base}}=R_{\mathrm{floor}}+T_{\mathrm{rp}},\qquad R_R=R_{\mathrm{base}}+T_{\mathrm{rc}},\qquad R_D=R_{\mathrm{base}}+W_0.$$

代价按模型、上下文、尾长、设备和代表性并发校准；$W_0$ 的装载模型见 §3.6。若 $\sigma_r\ge R_R$，请求为 **Tier R**，计划无需备份，故障后重算；否则若 $\sigma_r\ge R_D$，为 **Tier D**，保留 DRAM；其余为 **Tier P**，保留 DRAM 并申请 Peer HBM 保护。层级切换在上述名义边界周围采用 20% 滞回。Peer 是额外的快速副本，实际驻留由 Adapter 回报；没有取得 Peer 配额的 Tier P 请求仍走 DRAM。Slack 决定竞争 Peer 的请求顺序，不缩放每层热集，也不规定串行 retry 顺序。

**定义与选择保护对象。** 对象为包含全部 KV heads 的 `(layer, block)`；当前画像使用 64-token 块。写满密封后才可复制，但故障后的可用前缀以提交前沿为准；未提交的密封块和活跃尾部使用故障前已知的 token ID 重放，不重新采样。

第 $l$ 层长度 $n$ 重放需要的历史块并集为 $U_l(n)=\bigcup_{q=1}^{n}\bigcup_g S_{l,q,g}$，$S$ 为原生选择器输出，重复读取只计一块。以模型、层、上下文档和尾长为索引的缓慢更新画像估计 $h_l=|U_l|/B_l$，得到 $K_l=\lceil h_lB_l\rceil$；$B_l$ 为历史块数。Manager 先将强制密封起始/窗口块计入 $K_l$，再按 Adapter 上报的实际选择频次填满剩余槽，同频时最近优先；可选旧块连续两个解码统计窗口跌出热集才允许替换，替换复用原槽。这些逐层集合是候选，实际驻留的前层数由 Adapter 每窗口确定。D/P 两类都在恢复元数据中保留热集作为预取提示，但只有 P 类竞争 Peer 容量。

**算法 2：KV 备份策略**

```text
Input: live requests, Slack, profiles, counts, target ranks pr
Output: desired DRAM set Ds, hot sets H, and ordered Peer candidates Qp
1  Ds, H ← ∅; Qp ← [] for each target p
2  for r in (Slack, stable request ID) order:
3      τr ← Tier(r, RR, RD, σr)
4      if τr = R: continue
5      Ds ← Ds ∪ sealed(r) ∪ state(r)
6      Hr,l ← HotSet(r, l, Kl) for each layer l
7      if τr = D: continue
8      append (r, {Hr,l}, profile(r)) to Qpr
9  return Ds, H, {Qp}
```

`Tier` 对已有层级应用滞回，到达时使用名义阈值。算法输出期望策略，尚不代表可读副本；$n$ 个请求的排序为 $O(n\log n)$，共享物理对象在分配时去重。Adapter 对策略变化和已提交副本执行差量更新，并回报实际驻留、提交状态及下次策略刷新所需的装载估计。

### 3.6 Adapter：逐窗口容量与层数控制 ④

Adapter 将 KV Manager 的策略转为实际副本和恢复执行。每个目标 DP 在控制窗口边界（默认 1 s）更新 Peer HBM 总预算 $B_{p,t}$ 和各请求的目标驻留前层数 $L_r(t)$，向控制面回报实际驻留及提交状态。复制完成前，已提交前缀可能短于 $L_r(t)$；恢复只使用实际已提交对象，不将目标层数当作已经可读的层数。

**每窗口控制 Peer 容量。** 目标 DP $p$ 在窗口 $t$ 的预算为

$$B_{p,t}=[\min(B_{\mathrm{cap}},\mathrm{pool}_{p,t}-\mathrm{watermark}_{p,t}-\mathrm{headroom}_{p,t})]^+.$$

$B_{\mathrm{cap}}$ 默认 4 GiB。KV pool 包含已被 Peer 副本占用的容量，因此 $B_{p,t}$ 是总目标而非新增空闲量；前台需求、准入余量及传输/计算估计每窗口刷新。

令 $A_r(k)$ 为 KV Manager 指定的前 $k$ 层热块及这些层必需的选择器状态，$A_r(0)=\varnothing$。Adapter 根据下文推导的有用层数上限 $L_r^\star(t)$，按 Manager 给出的 $Q_p$ 优先级分配。起始 $P_s=\varnothing$，依次选择

$$L_r(t)=\max\{k\in\{0,\ldots,L_r^\star(t)\}:\mathrm{bytes}(P_s\cup A_r(k))\le B_{p,t}\},$$

并令 $P_s\leftarrow P_s\cup A_r(L_r(t))$。共享物理对象只计一次；每次准入完整的单层热集，允许一个请求只获得少于 $L_r^\star(t)$ 的前层数。$L_r(t)=0$ 时保留 DRAM 路径，剩余容量可供后续请求使用。容量或画像变化可使下一窗口的 $L_r(t)$ 增大或减小。该贪心分配不声称全局最优；完成共享对象核算后，利用各层的增量字节数，每请求最多扫描 $N$ 个层前缀。

窗口内目标保持稳定，紧急前台压力可提前收缩：Adapter 从准入优先级最低的请求开始，先撤销后层。copying、committed、reclaiming 字节在实际释放前持续计入物理占用；调低 $B_{p,t}$ 或 $L_r(t)$ 不等于立即释放地址。新复制等待足够的物理余量，读者使用结束前保留 pin；扩容只复制新增对象，回收保留所需 DRAM 恢复路径。

**推导有用层数上限。** Adapter 按层预取热块并跳过 Peer 驻留对象；选择器状态必须先到达，才可计算确切需求。新发现的缺失块优先于推测性预取，冷块后台补齐。令 $h$ 为预取比例，$\widetilde u$ 为预取与补取并集占历史字节的比例，两者由重放选择轨迹校准。采用 $N$ 个同质层，每层重放计算 $C$、完整历史装载 $D=M_rs/\beta$（$M_r$ 为历史 token 数，$s$ 为每 token 每层 KV 字节，$\beta$ 为有效带宽），则

$$W_{\mathrm{floor}}=N(\widetilde u-h)D,$$
$$W_0=hD+(N-1)[hD-C]^++W_{\mathrm{floor}},\qquad[x]^+=\max(0,x).$$

前两项为首层启动和计算无法掩盖的预取积压；最后一项是在固定热集、因果需求释放和理想可抢占复制流下的补取等待，不是任意保护或装载策略的下界。Adapter 使用当前窗口画像计算

$$F^\star(r,t)=\beta_t\bigl(W_0(r,t)-W_{\mathrm{floor}}(r,t)\bigr),$$

取满足 $\sum_{l=1}^{k}K_lb\ge F^\star(r,t)$ 的最小 $k$ 作为 $L_r^\star(t)$，$b$ 为每层块 KV 字节数；没有有用预取时上限为 0，最大为 $N$，选择器状态另外计入 $A_r(k)$。当 $hD\le C$ 时，同质模型只需首层热集。实际 $L_r(t)$ 同时受有用上限与容量约束；对异构层这是规划近似，不能保证运行时恰好达到同质层地板。

<figure class="paper-figure">

[<img src="../figures/design-single/design-layer-pipeline.png" width="480" alt="图 5 四种恢复流水线">](../figures/design-single/design-layer-pipeline.pdf)

**图 5：模型化恢复流水线。** MiniCPM4-8B，32 层、32K 历史、已知 64-token 尾部；每层 $C=2.87$ ms 来自测量，$D=5.37$ ms 对应假设的 6.25 GB/s 带宽。(d) 将 147 MiB 热集驻留 Peer；时间终点为尾部 KV 重建完成。模型采用同质层及理想可抢占复制流，不含检测、排队和干扰。

</figure>

图 5(a,b) 中，逐层流水线将等待从 172 ms 降至 83 ms；图 5(c) 的热集预取降至 44 ms，图 5(d) 的前七层热集驻留后剩 20 ms 补取等待。这是单个校准画像对有用层前缀的说明，既不是跨窗口固定为七层，也不是故障恢复实测。

**完整后发布。** Adapter 按已绑定目标和当前 $D_s,P_s$ 调用 Connector 分配、传输和确认。Peer 与故障域外 DRAM 路径独立提交，传输完成并校验模型、布局与分片后才发布可读副本。选择器状态必须先于选择操作就绪；Peer 若是唯一存活副本，必须等 DRAM 提交后才能丢弃。复制使用低优先级流并限速（默认链路的 20%），同时核算接管端 HBM 带宽。

**按需恢复且不改变注意力输入。** 预取与前层计算重叠，新揭示的缺失块优先于排队的预取；实际 DMA 粒度可能限制理想抢占。每层全部必需输入就绪后才执行，冷块在后台或后续 decode 时补取，Tier R 重建历史。AegisKV 不改变选择器输出和已知重放 token；在兼容权重、布局与算子下重建同一逻辑 KV，不引入新的注意力近似，但不保证不同浮点调度下后续随机采样逐 token 一致。

**适用边界与验证。** 接入稀疏模型要求可观察索引、可恢复选择器状态及所有必需注意力分支，token 索引需映射到物理复制块。预测差时退化为逐层完整装载；稠密注意力取 $h=\widetilde u=1$，独立请求取零 Slack。Prefill 故障需按丢失 chunk 校准，不能套用固定 64-token 尾部。Agent 负载的 Slack 精度、画像漂移、同时 retry 与前台干扰仍需端到端验证，轨迹分析和流水线模型不能替代这些证据。

---

编辑记录（不进入论文）：本轮只压缩 System Design。旧完整正文、详细校准讨论及撤下的预算/足迹图引用保存在 [设计补充素材](supporting/design-full-20260918/README.md)，用于后续 Evaluation 或补充材料；本节原 Figure 6 顺次成为 Figure 5。两轮紧凑排版将 Figure 3 面板高度从 2.65 inch 经 2.05 inch 调为 1.85 inch，Figure 5 从 4.70 inch 经 3.40 inch 调为 3.05 inch；保留原宽度、字号与所有数据，分别继续采用三图跨双栏与单栏布局。

编辑记录（不进入论文）：原 3.4 与 3.5 合并为同一 KV Placement Planner 小节，按选块、确定层数、预算准入展开；Recovery Manager 和 Adapter 顺次成为 3.5、3.6。正文逐项引用 Figure 3(a)–(c)，流水线解释对应 Figure 5(a)–(d)。

编辑记录（不进入论文）：用户进一步澄清主要问题为 Figure 3/5 的图内字体过大；本轮改用与正文一致的 Linux Libertine，原生字号由 10.25/10.5 pt 调至 10.05 pt，Figure 5 仅面板字母加粗。图尺寸、数据、引用与小节结构保持上一轮结果。

编辑记录（不进入论文）：按用户确认，3.3 改为 GBDT 剩余时间预测与 CPM Slack 传播，并新增算法 1；原放置算法顺次成为算法 2。恢复代价与层级选择移入 3.4 Planner，角色 P90 不再作为当前 Tracker 的预测方法；图 3(a) 的 Median/P90 仍保留为原诊断基线。本轮补充的是论文算法规格，没有重新训练模型或验证端到端预测收益。

编辑记录（不进入论文，2026-09-18 最新职责调整）：3.4 Recovery Manager 在到达时绑定 retry 目标与 Peer DP rank；3.5 KV Manager 决定备份触发、层级和候选热块；3.6 Adapter 按窗口控制总预算与实际层前缀。算法 2 改为备份策略输出，原整请求足迹全放或全不放改为 Adapter 按完整层前缀分配；Figure 5 的原有数据保留，仅将解释移入 Adapter。编号同步为 ① Tracker、② Recovery Manager、③ KV Manager、④ Adapter。上述为论文设计规格更新，未将旧模拟器结果视为新策略验证。
