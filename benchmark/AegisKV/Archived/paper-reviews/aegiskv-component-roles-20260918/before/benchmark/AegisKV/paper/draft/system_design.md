## 3 AegisKV Design

AegisKV 结合工作流的延迟容忍度与单请求的 KV 恢复需求：Tracker 估计 Slack，Planner 决定保护层级及有限容量下的层/块集合，运行时提交副本并并发执行 retry。下面先说明设计依据，再按模块给出决策与执行过程。

### 3.1 Insights 与设计启示

**Insight 1：从工作流进度估计延迟容忍度，但时间估计前提仍需验证。** 重复角色提供历史画像的基础，但多轮 agent 时长还包含工具与服务延迟。图 3(a) 的 CC 轨迹按 workflow 隔离预测中，进度 GBDT 的归一化误差中位数为 51.8%，持续时间中位数基线为 49.3%；角色标签全部为 `Subagent`，尚不能证明按角色准确预测。算法 1 将 GBDT 时间预测与 CPM Slack 传播分开；这一诊断尚未验证完整 Tracker 及其保护决策。

**Insight 2：稀疏注意力改变恢复时需要保护的对象。** 长上下文模型已采用 InfLLMv2、DSA 以及压缩/混合注意力。图 3(b) 的十个发布实例说明适用模型的存在，不代表市场采用率，也不意味着每层都使用相同的 Top-k。Planner 接收真实的逐层选择与模型特定恢复状态，而不将所有历史 KV 字节视为等价。

**Insight 3：过去的选择能预测 retry 尾部所需历史 KV 的一部分。** 图 3(c) 中，相同字节预算下，历史频次覆盖 NOSA-1B、NOSA-3B、MiniCPM4 所需 KV 的 79.2%、77.8%、53.6%，最近优先为 59.7%、59.7%、50.9%。收益依赖模型且存在未命中，因此提前放置必须配合确切需求的补取。这些留出的书籍文本后缀不是 agentic 故障恢复实验。

<figure class="paper-figure">

[<img src="../figures/design-insights/design-insights-row.png" width="1008" alt="图 3 时间估计、稀疏模型与 retry KV 预测">](../figures/design-insights/design-insights-row.pdf)

**图 3：设计依据。** (a) 174 个 workflow、1,688 个 CC agent 的五折预测，workflow 不跨折；每个 agent 的样本为平均绝对剩余时间误差除以总时长，对称对数轴保留全部误差；Median/P90 为持续时间先验。(b) 发布/模型仓库日期与原生上下文；编号 1–10 对应 MiniCPM4、MiniCPM4.1、DeepSeek-V3.2-Exp、DeepSeek-V3.2、GLM-5、MiniCPM-SALA、DeepSeek-V4 preview、MiniMax-M3、GLM-5.2、LongCat-Flash-Lite-Sparse。灰线仅为入选版本的最大上下文，marker 表示稀疏分支中块、token 或压缩项的 Top-k 选择。(c) 每模型 3 份原生 PG19 捕获，32K 历史；Query 32,257–32,768 预测 32,769–32,832 的去重历史需求。强制块包含在 40% 预算内；柱与误差线为文档均值与范围。完整来源见[图像说明](../figures/design-insights/README.md)。

</figure>

### 3.2 System Overview

图 4 分为应用、控制面和推理引擎。应用上报 request/workflow 标识与 DAG 更新；Router 按负载及 KV 局部性分发；AegisKV Controller 维护 Slack、放置和恢复决策。DP0 与 DP1 各有 Adapter、Connector、Local KV 和较小的 Peer 区。Planner 决策，Connector 执行；KV 直接在引擎与存储间传输。黑底编号只索引下文模块，不表示执行顺序。

<figure class="paper-figure">

[<img src="../figures/system-overview-v11.drawio.png" width="480" alt="图 4 AegisKV 三层架构">](../figures/system-overview-v11.drawio.pdf)

**图 4：AegisKV Overview。** ① Tracker、② Planner、③ Recovery Manager、④ Adapter 各标一次；两侧 DP 能力相同。Peer 与 DRAM 路径独立提交，内存比例和块布局为示意。图源：[Draw.io](../figures/system-overview-v11.drawio)。

</figure>

Peer 目标在故障前确定，例如 $n\ge2$ 个 DP 采用 $p(g)=(g+1)\bmod n$，使接管端直接读取本地副本。TP 组按兼容分片恢复；分散到多个接管目标同样需要提前绑定请求和副本。目录与提交元数据保存在源故障域之外。Planner 默认每 1 s 或显著请求/Slack 事件后刷新；静态画像确定热集大小，Adapter 计数更新块身份。

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

### 3.4 KV Placement Planner ②

Planner 先选择前 $L$ 层中每层最热的 $K_l$ 个密封块，再在 Peer 预算内准入完整足迹。

**选择保护层级。** 设 $T_{\mathrm{rc}}$ 为历史重算代价，$T_{\mathrm{rp}}$ 为已知尾部重放计算代价，$W_0$ 为无 Peer 时暴露的 DRAM 等待；$R_{\mathrm{floor}}$ 包含检测、重新路由与准入。Planner 使用

$$R_{\mathrm{base}}=R_{\mathrm{floor}}+T_{\mathrm{rp}},\qquad R_R=R_{\mathrm{base}}+T_{\mathrm{rc}},\qquad R_D=R_{\mathrm{base}}+W_0.$$

代价按模型、上下文、尾长、设备和代表性并发校准。若 $\sigma_r\ge R_R$，请求为 **Tier R**，计划无需备份；否则若 $\sigma_r\ge R_D$，为 **Tier D**，保留 DRAM；其余为 **Tier P**，保留 DRAM 并按 Slack 升序竞争 Peer。层级变化采用 20% 滞回。未获准的请求仍走 DRAM。

Slack 决定整体准入顺序，不缩放请求足迹。整体准入使容量核算和更新更可预测，但可能留下空闲容量或错过部分保护的收益；它是策略取舍，不是全局最优结论，也不是恢复执行顺序。

**定义保护对象。** 对象为包含全部 KV heads 的 `(layer, block)`；当前画像使用 64-token 块。写满密封后才可复制，但故障后的可用前缀以提交前沿为准：未提交的密封块和活跃尾部都要重放。重放使用故障前已知的 token ID 重建 KV，不重新采样。

**离线定大小，在线定身份。** 第 $l$ 层的长度 $n$ 重放需要历史块并集 $U_l(n)=\bigcup_{q=1}^{n}\bigcup_g S_{l,q,g}$；$S$ 为原生选择器输出，重复读取只算一块。以模型、层、上下文档和尾长为索引的表估计 $h_l=|U_l|/B_l$，得到 $K_l=\lceil h_lB_l\rceil$；$B_l$ 为历史块数。强制起始/窗口块必须包含在 $K_l$ 内，画像跨请求缓慢更新。

Adapter 按层/块累计前一个 512 解码步窗口中的真实索引。Planner 先保留强制密封块，再按频次降序填满剩余槽，同频时最近优先；可选旧块连续两个窗口跌出热集才允许替换。替换复用原槽，不增加 $K_l$。只有身份变化产生增量复制，从 Peer 移出的对象仍有 DRAM 覆盖。

**保护暴露传输，而非全部历史字节。** Adapter 按层预取热块并跳过 Peer 驻留对象；选择器状态必须先到达，才可计算确切需求。新发现的缺失块优先于推测性预取，冷块后台补齐。令 $h$ 为预取比例，$\widetilde u$ 为预取与补取并集占历史字节的比例，两者由重放选择轨迹校准。采用 $N$ 个同质层，每层重放计算 $C$，完整历史装载 $D=L_rs/\beta$（$L_r$ 为历史 token 数、$s$ 为每 token 每层 KV 字节、$\beta$ 为有效带宽），则

$$W_{\mathrm{floor}}=N(\widetilde u-h)D,$$
$$W_0=hD+(N-1)[hD-C]^++W_{\mathrm{floor}},\qquad[x]^+=\max(0,x).$$

前两项为首层启动和计算无法掩盖的预取积压；最后一项是在固定热集、因果需求释放和理想可抢占复制流下的补取等待，不是任意保护或装载策略的下界。

Peer 中的前层热集用于消除预取分量。令

$$F^\star(r)=\beta(W_0-W_{\mathrm{floor}}),$$

取满足 $\sum_{l=1}^{L}K_lb\ge F^\star(r)$ 的最小前层数 $L$，$b$ 为每层块字节数，准入另计选择器状态。当 $hD\le C$ 时只需首层热集。足迹取决于请求及传输/计算画像，不含 Slack，在放置窗口边界重新计算；对异构层是规划近似，不能保证运行时恰好达到同质层地板。

<figure class="paper-figure">

[<img src="../figures/design-single/design-layer-pipeline.png" width="480" alt="图 5 四种恢复流水线">](../figures/design-single/design-layer-pipeline.pdf)

**图 5：模型化恢复流水线。** MiniCPM4-8B，32 层、32K 历史、已知 64-token 尾部；每层 $C=2.87$ ms 来自测量，$D=5.37$ ms 对应假设的 6.25 GB/s 带宽。(d) 将 147 MiB 热集驻留 Peer；时间终点为尾部 KV 重建完成。模型采用同质层及理想可抢占复制流，不含检测、排队和干扰。

</figure>

图 5(a,b) 中，逐层流水线将等待从 172 ms 降至 83 ms；图 5(c) 的热集预取降至 44 ms，图 5(d) 的前七层热集驻留后剩 20 ms 补取等待。这是机制解释，不是故障恢复实测。

**预算内准入完整足迹。** 这些足迹竞争每个窗口的 Peer 预算；只借用目标 KV 池扣除前台高水位和准入余量后的容量，并受 $B_{\mathrm{cap}}$（默认 4 GiB）限制：

$$B=[\min(B_{\mathrm{cap}},\mathrm{pool}-\mathrm{watermark}-\mathrm{headroom})]^+.$$

算法 2 按 Slack 升序准入完整足迹，物理共享对象只计一次；当前请求放不下时继续考虑后续较小请求。$A_r$ 包含前 $L$ 层选中的密封块及必需选择器状态，`sealed(r)` 包含全部密封历史 KV。

**算法 2：完整足迹放置**

```text
Input: requests, Slack, profiles, rankings, window budget B
Output: desired DRAM set Ds and Peer set Ps
1  Ds ← ∅; Ps ← ∅
2  for r in (Slack, stable request ID) order:
3      if σr ≥ RR(r): continue
4      Ds ← Ds ∪ sealed(r) ∪ state(r)
5      if σr ≥ RD(r): continue
6      Ar ← footprint(r, F*(r))
7      Δ ← bytes(Ar \ Ps)
8      if Δ > B: continue
9      Ps ← Ps ∪ Ar; B ← B − Δ
10 return Ds, Ps
```

$n$ 个请求的排序为 $O(n\log n)$，利用缓存排名计算每个层前缀为 $O(N)$。Adapter 对目标集合与已提交副本执行差量更新。计划预算窗口内固定，前台压力可触发紧急回收；copying、committed、reclaiming 字节在实际释放前持续计入物理占用，降低预算不等于释放地址。

### 3.5 Recovery Manager：并发接管 ③

Manager 综合成员状态、设备错误及 Adapter 上报的 GPU 进度，进程心跳不能独自证明 GPU 正常。确认并隔离失效源后，从存活控制状态取得 token 前缀、提交前沿、模型/布局标识和副本位置，向预定目标提交 retry。控制状态存活、写隔离、故障域分离和重试去重是运行时契约。

各请求独立进入恢复，仍受前台准入、连续批处理以及共享计算/复制容量约束，并依据自身逐层就绪事件推进。放置优先级不产生请求级完成屏障，Manager 不因某请求 Slack 较小而等待它恢复完才提交下一个。

### 3.6 Adapter：安全副本与按需恢复 ④

**完整后发布。** Adapter 调用 Connector 对 Planner 指定对象分配、传输和确认；Peer 与故障域外 DRAM 独立提交。传输完成并校验模型、布局与分片后才发布可读副本。选择器状态随首层复制，必须先于选择操作就绪。若 Peer 是唯一存活副本，必须等待 DRAM 提交后才能丢弃。

**服从前台。** 内存压力下，Adapter 按准入逆序撤销完整 Peer 足迹，物理释放从后层开始；请求保留 DRAM 路径并在下一窗口重新竞争。复制使用低优先级流并限速（默认链路的 20%），同时核算接管端 HBM 带宽。

**不改变注意力输入。** 预取与前层计算重叠，新揭示的缺失块优先于排队的预取；实际 DMA 粒度可能限制理想抢占。每层全部必需输入就绪后才执行，冷块在后台或后续 decode 时补取，Tier R 重建历史。AegisKV 不改变选择器输出和已知重放 token；在兼容权重、布局与算子下重建同一逻辑 KV，不引入新的注意力近似，但不保证不同浮点调度下后续随机采样逐 token 一致。

**适用边界与验证。** 接入稀疏模型要求可观察索引、可恢复选择器状态及所有必需注意力分支，token 索引需映射到物理复制块。预测差时退化为逐层完整装载；稠密注意力取 $h=\widetilde u=1$，独立请求取零 Slack。Prefill 故障需按丢失 chunk 校准，不能套用固定 64-token 尾部。Agent 负载的 Slack 精度、画像漂移、同时 retry 与前台干扰仍需端到端验证，轨迹分析和流水线模型不能替代这些证据。

---

编辑记录（不进入论文）：本轮只压缩 System Design。旧完整正文、详细校准讨论及撤下的预算/足迹图引用保存在 [设计补充素材](supporting/design-full-20260918/README.md)，用于后续 Evaluation 或补充材料；本节原 Figure 6 顺次成为 Figure 5。两轮紧凑排版将 Figure 3 面板高度从 2.65 inch 经 2.05 inch 调为 1.85 inch，Figure 5 从 4.70 inch 经 3.40 inch 调为 3.05 inch；保留原宽度、字号与所有数据，分别继续采用三图跨双栏与单栏布局。

编辑记录（不进入论文）：原 3.4 与 3.5 合并为同一 KV Placement Planner 小节，按选块、确定层数、预算准入展开；Recovery Manager 和 Adapter 顺次成为 3.5、3.6。正文逐项引用 Figure 3(a)–(c)，流水线解释对应 Figure 5(a)–(d)。

编辑记录（不进入论文）：用户进一步澄清主要问题为 Figure 3/5 的图内字体过大；本轮改用与正文一致的 Linux Libertine，原生字号由 10.25/10.5 pt 调至 10.05 pt，Figure 5 仅面板字母加粗。图尺寸、数据、引用与小节结构保持上一轮结果。

编辑记录（不进入论文）：按用户确认，3.3 改为 GBDT 剩余时间预测与 CPM Slack 传播，并新增算法 1；原放置算法顺次成为算法 2。恢复代价与层级选择移入 3.4 Planner，角色 P90 不再作为当前 Tracker 的预测方法；图 3(a) 的 Median/P90 仍保留为原诊断基线。本轮补充的是论文算法规格，没有重新训练模型或验证端到端预测收益。
