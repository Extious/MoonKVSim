# AegisKV 评审意见（EuroSys 2027 视角）

## 0. 阅读与可读性声明

我逐段读了附件 `main-review-baseline.pdf` 的全部 9 页：摘要、§2.1–§2.4、§3.1–§3.6、公式 (1)(2)、Algorithm 1–3、Figure 1–5 及图注、参考文献 [1]–[24]。

关于图表的可读性，需要如实说明：Figure 1(b)(c)、Figure 5 的数值标注（60.4/151.6/132.4/129.4 s；35.2/32.2/36.7/38.9 s 与 91.2/0.0/19.1/21.9 s；264/172、175/83、136/44、112/20 ms）我能直接读到并已用于核算。Figure 1(a) 的 CDF、Figure 2 的 12 条曲线、Figure 3(a)(b)(c) 我只能读到图注中给出的标注值（median 138 s / P90 1,173 s；0.72/0.88/0.94；77.8/53.6/43.0% 与 59.7/50.9/42.0%），**曲线上未标注的中间点我无法逐点读数**，因此下文不对未标注数值做任何推断。Figure 4 的系统框图我能读到组件、徽章编号和连线方向，但 HBM 内 Local KV / Peer KV 的比例是示意性的（作者已说明），我不据此判断容量。

另外我核对了 EuroSys 2027 CFP：正文 12 页、参考文献不计入；所有文字含图和图注需 ≥10pt 字号、≥12pt 行距；图表需在灰度打印下无需放大即可读；评审依据为新颖性、意义、趣味性、清晰性、相关性与正确性，并期待"严格的评估清楚展示方案的收益、局限以及相对已有工作的优势"。Fall 轮全文截稿为 2026 年 9 月 24 日——距今 5 天，下文第 6 节会给出时间线建议。

我按作者要求区分了四类证据：**静态估计**（AIConfigurator HYBRID、Figure 2、Figure 1(c) 的 $T_i$）、**解析模拟**（Figure 5）、**文献结果**（Figure 3(a) 来自 Heddle）、**本系统实测**（目前为零）。本文**没有实现、没有实测、没有基线、没有评估**，我不会把任何未提供的实验当作已完成；但我会指出哪些结论在现有范围内就已经无法成立。

---

## 1. 核心贡献与总体判断

### 1.1 稿件试图做什么

AegisKV 提出：在多智能体 LLM 工作流中，KV 容错资源应按**工作流层面的完成时间影响（WCT）**而非**单请求恢复成本**来分配。机制上由四个组件构成：Tracker 用 GBDT 预测剩余执行时间、用 CPM 计算 slack（Alg 1）；Recovery Manager 在请求**到达时**预绑定接管目标 $p_r$，使 Peer 备份天然位于未来的接管 GPU；KV Master 在 checkpoint 事件上选择保护层级 R/D/P、每请求层深 $L_r$ 与热块集（式 (1)(2)、Alg 2）；Adapter 以窗口为粒度控制 Peer HBM 预算 $B_p$，并保证不驱逐活引用（Alg 3）。

### 1.2 最强的三点

**S1｜问题抽象的转向是正确且及时的。** 把容错目标从"少算多少 token"改成"少延迟多少工作流"，在 agent 时代是一个有价值的重新定义。Figure 1(c) 的 A1/A2 对照非常干净：A2 重算成本最低（32.2 s）却造成最大 WCT 损失（32.2 s），A1 成本最高（35.2 s）却损失为零。这是一个读者会记住的论点，而且与式 (1) 的层级规则在逻辑上直接对应。

**S2｜恢复路径的成本分解给出了可证伪的量级结构。** $R_{base}=R_{floor}+T_{rp}$、$R_R=R_{base}+T_{rc}$、$R_D=R_{base}+W_0$ 三项拆分清晰，配合 Figure 2 的三档量级（128K 时 14.5–21.0 s / 155–357 ms / 22–56 ms）和 Figure 5 的流水线分解（172→83→44→20 ms），形成了一个别人可以复现、可以反驳的成本模型。这在系统论文里是加分项。

**S3｜到达时预绑定接管目标是一个简洁的工程判断。** 让 $p_r$ 同时是"重试目的地"和"Peer 副本所在 DP"，把放置决策前移到故障之前，从而使"可用副本天然 local to takeover"（§3.4，第 4–5 页）。这避免了故障后再选目标、再搬数据的常见二次延迟。配合 §3.6 的引用计数契约（"priority does not revoke a live reference"），容量控制的语义比多数同类论文写得更细。

另外值得肯定：作者对估计/模拟/文献/实测的区分极其诚实（"These are literature results, not AegisKV runtime-error measurements"、"This cost substitution does not constitute physical failure replay"）。这种诚实我会正面计分——但它不能替代证据，下文我会说明每条"诚实声明"的实际后果。

### 1.3 现有动机/算法是否达到 EuroSys 水平

**动机：方向对，证据不够。** §2.2 的核心结论（恢复成本排序 ≠ WCT 影响排序）目前只由**一个手工挑选的四分支样例**支撑，且作者自己写明了挑选准则（"we select one with a longer critical-branch prefix"）。这是自认的选择偏差。要支撑一篇 EuroSys 论文的立论，必须有总体分布。

**算法：结构合理，目标函数有形式化缺陷。** Alg 1 是教科书 CPM，正确但缺资源约束；Alg 2/3 的工程契约写得细，但 §3.5 的打分函数（前台延迟 + 故障概率 × 超 slack 恢复延迟）量纲不可比、且在现实 MTBF 下会退化（见 P0-05）。层级阈值与深度打分对故障概率的处理互相矛盾。

**整体：当前范围（摘要+§2+§3）尚未达到 EuroSys 接收水平，但问题选择值得继续投入。** 按 CFP 的"严格的评估清楚展示收益、局限与相对已有工作的优势"标准，本文差的不只是"还没做实验"，而是几个会改变设计的论证缺口。

### 1.4 最可能导致拒稿的五个原因

**R-1｜立论建立在单样例上，且成本与 slack 来自两个不可通约的系统。** Figure 1(c) 的 $T_i$ 是 Qwen3-14B/A100 的静态估计，$\sigma_i$ 是 CC/Weka 轨迹（另一个服务系统、另一个模型）的观测完成时间。二者之比恰是全文的核心量。没有总体分布、没有敏感性分析、没有 fan-in 依赖验证。

**R-2｜收益结构与机制复杂度严重错配。** 按作者自己的数字：重算 ~32 s → DRAM ~0.3 s → Peer HBM ~0.02 s。即 **tier D 已吃掉约 99% 的可恢复延迟，Peer/HBM 层的边际收益约占 1%**。而全文的机制复杂度（$L_r$ 选择、热块排序、窗口预算、引用计数、LRU 回收）全部压在这 1% 上；真正承载 99% 收益的 DRAM 层在 §3.5 中只有一行 `Add sealed(r) ∪ state(r) to D_s`（Alg 2 第 6 行），**没有容量模型、没有带宽模型、没有驱逐策略**。这是审稿人会最先攻击的结构性问题。

**R-3｜恢复期的争用完全未建模，导致层级判定会系统性出错。** §2.1 提到"concurrent recoveries share transfer bandwidth"，但式 (1) 的 $W_0$ 是单请求无争用值。单 GPU 故障会同时命中该 rank 上的**所有**并发请求，这正是 $W_0$ 最不准的时刻（见 P0-04 的量化）。

**R-4｜无实现、无实验、无基线；R1–R5 五条目标全部未验证，且关键正确性契约仅以散文声明。** 恢复一致性模型、重试去重、tool 副作用的 exactly-once 语义都只是"runtime contracts"一句带过。对 EuroSys 的 dependable systems 方向，这是硬伤。

**R-5｜相关工作覆盖不足，增量边界不清；且 12 页预算不可行。** 只对比了三个容错系统（DéjàVu/GhostServe/LUMEN），缺少两类最近的邻居：DAG 感知的 LLM 应用服务，以及 DL 训练的 in-memory/peer checkpoint。同时，当前 9 页只写到 §3 结束，加上引言、实现、评估、相关工作，无法压进12 页正文。

---

## 2. 分级问题清单（19 条）

每条格式：**编号｜严重性｜位置｜问题与机制/反例｜可执行修改｜验收通过标准｜负责范围**。

---

### P0-01｜动机结论依赖手选样例，且未报告适用范围覆盖率
- **位置**：§2.2，第 1–2 页；Figure 1(b)(c) 及图注（"Among groups with four or five branches and a gap near 100 s, we select one with a longer critical-branch prefix"；"The example illustrates recovery exposure, not population-average failure impact"）。
- **问题与机制**：全文最重要的断言——"避免最多重算未必带来最大 WCT 改善"——只由一个被承认为非代表性的样例支撑。更严重的是**适用范围未量化**：从 393 个 session 筛到 286 组 / 121 个 workflow，意味着约 69% 的 session 不满足"严格重叠 + 推断 fan-in"条件。如果这些 session 主要是串行链，则其中所有请求 slack ≈ 0，AegisKV 相对"按成本排序"没有任何区分力。论文目前把最有利于自己的 31% 当成了全集。
- **可执行修改**：(a) 新增 Figure 1(a') 总体面板：对全部 286 组 × 所有分支 × **在分支生命周期上均匀采样的故障时刻**，画出 $(T_i-\sigma_i)^+$ 与 $T_i$ 的联合分布，并报告二者的 Spearman 秩相关 $\rho$。论点成立的充分条件是 $\rho$ 显著低于 1。(b) 报告 393 个 session 的结构分类：无 fan-out / 有 fan-out 但 slack≈0 / 有可用 slack，各占多少 session、多少请求、多少 GPU-秒。(c) 把 Figure 1(b)(c) 明确降格为"case study"，图注首句改为 "A single illustrative group; see Figure 1(a') for the population"。
- **验收标准**：读者能从总体面板读出"按成本排序与按 WCT 影响排序的 top-k 重合度"，且该重合度在 k=10%/20%/50% 上都显著低于 1；同时能读出"有可用 slack 的请求占全部请求时间的比例"。若后者低于约 20%，作者需正面讨论这对 R1 的意义。
- **范围**：动机（仅需重新分析已有轨迹，无需新硬件）。

---

### P0-02｜$M_i$ 的时间语义不明确，可能系统性高估 $T_i$；且成本与 slack 来自异构系统
- **位置**：§2.2，第 2 页："Trace hash-block counts provide history lengths $M_i$ of 100,864–113,664 tokens"；"We query a Qwen3-14B static configuration at each exact length"。
- **问题与机制**：故障时刻设定在 fork 后 29.5 s，而分支时长为 60.4–151.6 s。此时各分支的历史长度**应当显著短于会话末态**。如果 $M_i$ 取的是会话（或分支）**总计**的 hash-block 计数而非 29.5 s 时刻的快照，则全部四个 $T_i$（35.2/32.2/36.7/38.9 s）被系统性高估，而 $\sigma_i$ 来自真实完成时间没有被同样放大——**偏差方向恰好放大论文想证明的 WCT 损失**。这是可能决定动机成立与否的测量语义问题，必须澄清。其次，$T_i$ 是 Qwen3-14B/A100-SXM 的静态估计，$\sigma_i$ 来自另一套服务系统的真实轨迹；二者之比在物理上不可通约（作者已承认是 "cost substitution"，但未说明后果：整张 Figure 1(c) 的相对大小关系可能随模型/硬件选择而翻转）。
- **可执行修改**：(a) 明确写出 $M_i$ 是"故障时刻 $t=29.5$ s 的已密封历史长度"还是别的，并给出推导方式；若是末态，必须改成时刻快照重算。(b) 增加归一化表达：把重算成本表示为该分支**自身观测时长的比例** $T_i/\text{dur}_i$，这样跨系统比较至少是无量纲的。(c) 给出硬件/模型敏感性：至少再给一组 H100 + 另一个模型规模，说明结论的符号不变（同时解决 Figure 1 用 A100、Figure 2 用 H100 的跨图不一致）。
- **验收标准**：读者能复现 $M_i \to T_i \to (T_i-\sigma_i)^+$ 的完整链条，且在 ≥2 组硬件/模型配置下"成本排序 ≠ WCT 影响排序"的结论符号一致。
- **范围**：动机（无需新硬件，重算即可）。

---

### P0-03｜收益结构与机制复杂度错配：DRAM 层被当作无限容量、无争用
- **位置**：跨章节。§2.3 第 3 页："a DRAM copy avoids most historical recomputation; full HBM residency additionally removes about 335 ms of modeled transfer waiting"；§3.5 Alg 2 第 6 行 `Add sealed(r) ∪ state(r) to D_s`；§3.6 全节只治理 $B_p$（Peer HBM）。
- **问题与机制**：按作者自己的量级，tier R→D 的收益约 32 s，D→P 的收益约 0.3 s，比例约 100:1。但论文的**全部**资源治理机制（式 (2)、深度选择、Alg 2 的 preview、Alg 3 的窗口预算与 LRU）都作用在 P 层。与此同时 $D_s$ 是无条件累加的集合：没有容量上限、没有驱逐、没有 host DRAM 带宽共享模型。这与 §2.4 的 R2（"limited backup capacity"）直接冲突——论文声称资源有限，但让承载 99% 收益的那一层无限。

  量化一下 DRAM 侧的真实压力（用论文自己的参数）：Qwen3-14B、GQA 8 个 KV head、head_dim 128、BF16、40 层，每 token 约 160 KiB KV；128K 上下文约 **20 GiB / 请求**。一个 1–2 TB DRAM 的节点只能容纳 50–100 个这样的请求的全量历史。在 agent 工作负载下（论文自己强调"Repeated agent interactions accumulate ..."），DRAM 容量**就是**约束。论文完全错过了自己最强的论据。
- **可执行修改**：(a) 在 §2.4 之前加一段容量可行性分析表：给定节点 DRAM、GPU 数、并发请求数、上下文分布，计算 tier D 的可满足率。(b) 把 $D_s$ 纳入同一个分配框架：DRAM 也需要预算、驱逐与引用计数，Alg 2 第 6 行必须变成一次**受限准入**。(c) 明确回答"如果只做 tier D 全量备份（DéjàVu 式），AegisKV 还剩多少收益"——这是审稿人必问的问题，必须在正文而不是 rebuttal 里回答。
- **验收标准**：论文能指出一个明确的参数区间（并发度、上下文长度、DRAM 容量、恢复带宽），在该区间内 tier P 的边际收益 ≥ 总收益的 10%；区间之外则诚实说明 AegisKV 退化为 tier D 调度器。
- **范围**：跨章节（分析可不用新硬件；结论可能触发重大设计决策）。

---

### P0-04｜恢复期争用未建模，$W_0$ 会导致层级系统性误判
- **位置**：§2.1 第 1 页（"concurrent recoveries share transfer bandwidth" 仅一句）；§2.3 第 3 页（"We assume concurrent restoration at 64 GB/s per rank, with no shared host bottleneck or transfer–compute overlap"）；§3.5 式 (1) 中的 $W_0$。
- **问题与机制**：失效模型是"一个 GPU/worker 的 fail-stop"，但一个 GPU 上通常有**几十个**并发请求。故障瞬间产生的是**恢复风暴**，不是单请求恢复。用论文参数算：16 个 128K 长上下文请求 × 20 GiB = 320 GiB，共享 64 GB/s → 约 **5 s**；32 个请求 → 约 10 s。这已经与 Figure 2 的 chunked recompute（14.5–21.0 s）同一量级，而不是图中显示的 155–357 ms。

  后果是决定性的：式 (1) 的 $R_D = R_{base} + W_0$ 用单请求无争用的 $W_0$ 会把 $R_D$ 低估 1–2 个数量级，于是大量本应进入 tier P（甚至本应直接选择重算，因为在风暴下重算可并行而传输不可）的请求被判为 tier D。**分层规则在最需要它的场景下给出相反的答案。**
- **可执行修改**：(a) 把 $W_0$ 重定义为并发度的函数 $W_0(k, B_{agg})$，其中 $k$ 是同一故障域下同时恢复的请求数、$B_{agg}$ 是共享的聚合带宽；在式 (1) 下方给出排队/带宽共享的显式形式。(b) 相应地把 $T_{rc}$ 也建成并发函数（重算受 GPU 算力约束，也会排队）。(c) 增加一个 §2.x 小节或 Figure 2 的第二面板：横轴为同时恢复的请求数，纵轴为三条路径的恢复时间——这张图会**交叉**，交叉点是本文最重要的设计依据。
- **验收标准**：新图显示 DRAM 与 Recompute 曲线在某个并发度上交叉，且 AegisKV 的层级规则在交叉点两侧给出不同的、正确的选择。
- **范围**：动机 + 算法（分析可不用新硬件；必须修改式 (1)）。

---

### P0-05｜深度选择的目标函数量纲不可比，且被故障概率压成恒等解；与层级阈值互相矛盾
- **位置**：§3.5 "Select a depth for each request"，第 6 页："The score adds predicted foreground delay from the candidate's backup work and memory occupancy to recovery delay beyond the request's slack, weighted by source-failure probability from the configured risk model over the same policy horizon."
- **问题与机制**：这句话定义的是
  $$\text{score}(d) = \underbrace{\Delta_{\text{fg}}(d)}_{\text{确定发生}} + p_{\text{fail}} \cdot \underbrace{\max(0, R(d)-\sigma_r)}_{\text{条件发生}}$$
  两个问题：

  1. **退化解**：在现实 MTBF 下，单个请求生命周期内源 GPU 故障的概率 $p_{\text{fail}}$ 是 $10^{-5}$ 量级。第二项被压到接近零，最小值点**恒为 $d=0$**。也就是说，按字面意思实现，AegisKV 永远不做 Peer 备份。论文若想让它工作，必须把 $p_{\text{fail}}$ 设得不真实地高——那么这个"risk model"就不是风险模型而是一个调参旋钮，应当如实说明。
  2. **与层级阈值自相矛盾**：式 (1) 的三个阈值（$\sigma \ge R_R$ → R；$R_D \le \sigma < R_R$ → D；否则 P）**完全不含 $p_{\text{fail}}$**，即隐含假设故障必然发生（$p_{\text{fail}}=1$）。同一节里，第一阶段假设 $p=1$、第二阶段用 $p \ll 1$ 加权，两者不可能同时正确。
  3. **量纲**："前台延迟（秒）"与"内存占用（字节）"被加到一起，文中没有给出换算系数。
- **可执行修改**：把问题重述为**约束优化**而非加权和——这是系统论文的标准做法，也回避了量纲问题：
  $$\max \sum_r \Big[\text{ExpectedWCTSaving}_r(d_r)\Big] \quad \text{s.t.} \quad \sum_r \text{bytes}_r(d_r) \le B_p,\ \ \Delta_{\text{fg}} \le \epsilon\cdot\text{baseline}$$
  其中 $\epsilon$ 是显式的开销预算（比如 2% 吞吐），对应 R4。然后：(a) 统一两个阶段的故障概率处理（建议两处都用同一个 $p_{\text{fail}}$，或者两处都用条件恢复成本 + 一个全局开销约束）；(b) 给出 $p_{\text{fail}}$ 的敏感性曲线（$10^{-6}$ 到 $10^{-2}$），说明系统在哪个区间给出非平凡解；(c) 写出所有项的单位。
- **验收标准**：在重述后的形式下，给定 $B_p$ 与开销预算，最优解非平凡（$L_r > 0$ 的请求占比非零），且该结论在 $p_{\text{fail}}$ 变化两个数量级时保持稳定。
- **范围**：算法（重大设计决策，无需新硬件即可完成形式化修订）。

---

### P0-06｜按 slack 排序的贪心在零 slack 区退化为 FCFS；有简单反例
- **位置**：§3.5 与 Alg 2 第 3 行（第 7 页）："for $r$ in $(\sigma_r, \mathrm{ID}_r)$ order"；§3.6 "in slack order, using stable request IDs to break ties"。
- **问题与机制**：式 (1) 把所有 $\sigma_r < R_D$ 的请求都归为 tier P，**其中包含全部关键路径请求（$\sigma=0$）**。这些请求在 Alg 2 里的排序键 $(\sigma_r,\mathrm{ID}_r)$ 完全相同的首分量，于是排序**退化为按请求 ID（到达顺序）先到先得**——在最重要的那一类请求内部，AegisKV 不做任何价值区分。

  **反例**：$r_1$：$\sigma=0$，上下文 2K，$T_{rc}=0.4$ s，最大可挽回 0.4 s；$r_2$：$\sigma=1$ s，上下文 128K，$T_{rc}=20$ s，最大可挽回 19 s。Alg 2 先处理 $r_1$，其 Preview 在快照 $S$ 上通过并占用预算（只要 $r_1$ 自身的分数支持 $L>0$ 即可，无需与 $r_2$ 比较，因为打分是**每请求局部的**，第 14 行只用选中计划更新 $S$）。预算耗尽时 $r_2$ 被拒。系统用掉资源换来 0.4 s，放弃了 19 s。
- **可执行修改**：把排序键从 slack 改为**边际收益密度**：$\dfrac{p_{\text{fail}}\cdot[\min(R_D,\ \cdot)-R_P(d)]}{\text{bytes}(d)}$，即"每字节挽回的期望 WCT"。slack 只作为其中一项输入（通过 $\max(0,R-\sigma)$ 进入分子），不再作为排序键。同时在评估里把"slack-order 贪心"与"密度贪心"作为两个 ablation 对比。
- **验收标准**：ablation 显示密度贪心在 P95 WCT 上优于 slack-order 贪心；若不优，作者需解释为何在该工作负载下二者等价（例如上下文长度分布退化）。
- **范围**：算法（无需新硬件即可完成，但属设计决策）。

---

### P0-07｜恢复正确性只有散文声明：混合来源 KV/选择器状态的一致性模型缺失
- **位置**：§3.5 "Commit and recover by actual readiness"，第 7 页："Placement changes neither selector outputs nor known replay tokens and adds no attention approximation; compatible weights, layout, and operators reconstruct the same logical KV state, without promising identical future stochastic samples across floating-point schedules."；§3.4 "retry deduplication are runtime contracts"；R5（§2.4）。
- **问题与机制**：恢复后的 KV cache 是**混合来源**的：前 $L_r$ 层的热块来自故障前的原始副本，其余层与冷块来自重算。三个具体风险：

  1. **数值一致性**：重算发生在不同的 batch 组成下，kernel 归约顺序不同 → 重算出的 KV 与原始 KV 在数值上不同。这本身可接受，但论文声称"reconstruct the same logical KV state"却未定义"logical"的等价关系（逐位？逐 token 输出相同？分布等价？）。
  2. **选择器状态的跨层不一致**（对本文尤其关键）：DSA 的 historical-token indexer keys、Seer 的 gate 输出属于"required auxiliary state"。若某些层的选择器状态恢复自副本、某些层重算，则恢复后各层的 top-$k$ 选择可能与故障前不同。此时 §3.5 精心构造的热块集 $H_{r,l}$ 可能**整体失配**，全部走 demand fetch——Figure 5(d) 的 20 ms 变回 44 ms 甚至更差。论文用"Selector state arrives before selection"回避了这个问题，但那只保证**时序**，不保证**内容一致**。
  3. **tool 副作用的 exactly-once 语义**：§3.6 提到 Peer 引用保持到"a response that hands control to an external tool"。如果请求已完成、tool 调用已发出、随后源 GPU 故障并触发重试，外部工具会被调用两次。在多智能体工作流中这可能意味着重复写文件、重复提交代码。"retry deduplication are runtime contracts"这一句不足以承担这个责任。
- **可执行修改**：(a) 新增一小节"Consistency model"，用 3–5 行明确写出保证等级，建议形式："给定相同的 token 前缀与相同的模型/layout/shard ID，恢复后的执行与无故障执行在**已承诺前缀上 token 级相同**，在后续采样上仅保证分布等价"。(b) 明确声明选择器状态的恢复规则：是否强制**整层同源**（要么整层来自副本、要么整层重算），以避免层内混合；如果允许混合，需给出选择漂移率的度量。(c) 把 tool 幂等性提升为显式假设或显式机制（例如 commit frontier 必须在 tool 调用之前落盘，且 tool 调用带 request-epoch 去重键）。(d) 设计一个可证伪的正确性实验（见 §4 的 M7）。
- **验收标准**：存在一个实验，在 ≥1000 次注入故障中报告"恢复后输出与无故障 golden run 的 token 级一致率"以及"tool 重复调用次数 = 0"。
- **范围**：算法 + 跨章节（需要新实验；一致性模型的定义属重大设计决策）。

---

### P0-08｜Insight 3 的证据与用途错配：PG19 文本、n=64 的极短 replay、oracle 上界使策略差异 ≈ 0、Seer 配置偏离
- **位置**：§3.1 Insight 3，第 5 页；Figure 3(c) 及图注（第 4–5 页）："32K history; queries 32,257–32,768 predict distinct historical KV for 32,769–32,832"；"Seer's demand spans 92.5% of historical blocks after the head union, limiting even oracle placement to 43.3% coverage"；"Seer uses an experimental Qwen3-8B Prefill gate [19] (threshold $10^{-3}$; final-block dense override disabled)"。
- **问题与机制**：这是支撑"热块选择"这一核心机制的唯一定量证据，但它有四层问题：

  1. **策略差异接近零**：Seer 上 past-frequency 43.0% vs recency 42.0% vs oracle 上界 43.3%——三者相差 1.3 个百分点，说明**约束是预算 $h=0.4$ 而不是排序策略**。MiniCPM 上 53.6% vs 50.9%，差 2.7 个百分点。只有 NOSA-3B 有显著差距（77.8% vs 59.7%）。论文用"gains depend on the model and placement granularity"一句带过，但这等于承认了**在 3 个模型中有 2 个，§3.5 的热块排序机制几乎无用**。
  2. **replay 长度不匹配用途**：$U_l(n)$ 定义为对 $n$ 个 replay token 的并集，但测量只做了 $n=64$（32,769–32,832）。实际恢复后请求会继续解码成百上千 token，并集单调增长，覆盖率必然下降。论文用 $n=64$ 的结果论证一个 $n\gg64$ 的机制。
  3. **域不匹配**：PG19 书籍文本的注意力模式与 agent 的代码/工具输出/多轮上下文差异极大。作者已承认，但未说明后果——agent 上下文有强结构性（重复的工具调用格式、代码块），past-frequency 可能表现**更好**也可能因为上下文突变而**更差**，方向未知。
  4. **Seer 配置偏离**：使用**prefill** gate 来预测 **decode** 阶段的选择，并关闭了 final-block dense override。这两项偏离很可能就是"92.5% demand spread"的成因。也就是说，表现最差的那个模型的结果可能是配置伪影，而不是模型性质。
- **可执行修改**：(a) 把 Figure 3(c) 改成**覆盖率 vs 两个自变量**的曲线族：横轴 $h \in [0.1, 1.0]$，分面为 $n \in \{64, 256, 1024, 4096\}$，每个模型一条线，并画出 oracle 上界。(b) 至少补一个 agent 域的上下文来源（可用 [18] 的轨迹文本重建），哪怕只做一个模型。(c) 说明 Seer 的 gate 选择理由，或改用与推理路径一致的 gate，或在图注中标注该点为"configuration-limited"。(d) 在 §3.5 里为"策略差异小"的情形给出退化路径（例如 $h$ 直接取 1.0 走全层加载，见 §3.6 Scope 已有的 fallback），并说明何时启用。
- **验收标准**：存在至少一个 $(模型, h, n)$ 组合，past-frequency 相对 recency 的覆盖率优势 ≥10 个百分点，且该优势在端到端 ablation 里转化为可测的 WCT 收益。
- **范围**：动机 + 算法（覆盖率曲线无需新硬件；端到端转化需新实验）。

---

### P0-09｜相关工作缺口与增量边界不清；缺"现有栈已免费提供 tier D"的基线
- **位置**：§2.1 第 1 页（仅 DéjàVu [20]、GhostServe [6]、LUMEN [1]）；参考文献 [1]–[24]。
- **问题与机制**：三条缺口，每一条都可能被审稿人单独用作拒稿理由：

  1. **DAG 感知的 LLM 应用服务**未被提及。本文 §3.3 的"从应用拿到 DAG，据此做资源决策"在调度维度已有前例——最接近的是 Parrot（OSDI 2024，用 Semantic Variable 暴露 LLM 应用的依赖关系并据此调度）；此外 Autellix 一类的 agent 程序服务引擎（*待核验*，我无法确认其确切版本与发表状态）。论文必须说明：我们的新意在于把 DAG 用于**容错资源分配**而非调度，而非"首次利用 DAG"。
  2. **DL 训练的 in-memory / peer checkpoint**未被提及。GEMINI（SOSP 2023，把 checkpoint 放到**对端主机内存**并做放置优化）与 Just-In-Time Checkpointing（EuroSys 2024，故障时按需 checkpoint）在机制上与 §3.4/§3.6 高度同构。不引用这两条线，"预绑定接管目标 + 窗口化对端预算"的新颖性无法界定。
  3. **前缀缓存/分层 KV 生态**未被作为基线。vLLM 的 automatic prefix caching、SGLang 的 RadixAttention、LMCache、Mooncake Store（[15] 已引但只用于失效模型）、CacheBlend（EuroSys 2025）都已经把 KV 下沉到 DRAM/SSD。**这意味着在现代服务栈里，tier D 很可能是免费的副产品，而不是 AegisKV 的贡献。** 这直接决定了 P0-03 中那 99% 的收益是否可归于本文。

  （以上除 [15] 外，我依据的是既有文献知识，未在本轮逐条核实版本与页码，**作者在引用前请自行核验**；Parrot / GEMINI / JIT Checkpointing / CacheBlend / RadixAttention 我有较高把握确实存在，Autellix 请标注待核验。）

  另外一个被完全忽略的**设计机会**：多智能体工作负载的前缀共享率极高（论文自己用 hash-block 计数）。故障时，丢失的 KV 很可能**已经存在于另一个 GPU 的前缀缓存中**。跨请求前缀缓存是比 DRAM 更便宜的恢复源，论文没有考虑。
- **可执行修改**：(a) 新增或扩充相关工作，按三条线组织（LLM 服务容错 / 训练容错 / 分层 KV 与前缀缓存），每条线用一句话写清 delta。(b) 把"vLLM APC + LMCache 式 DRAM 卸载"作为**主基线 B2**，而不是拿"无保护"当基线。(c) 在 §3.4 增加"cross-request prefix cache as a recovery source"的讨论，至少说明为何不用（或作为 future work）。
- **验收标准**：读者读完相关工作后，能用一句话说出"AegisKV 相对 B2 多做了什么、多省了多少"。
- **范围**：跨章节（无需新硬件；B2 基线需新实验）。

---

### P1-10｜Alg 1 无资源约束、DAG 增量揭示导致 slack 不稳定、失败路径退化代价最高
- **位置**：§3.3 与 Algorithm 1，第 4–5 页，第 2 行 "if DAG structure incomplete: return $\sigma$"、第 4 行 "if any prediction unavailable or invalid: return $\sigma$"、第 7 行 $\mathrm{EF}_a \leftarrow \hat d_a + \max_{b\in P(a)}\mathrm{EF}_b$、第 10 行 $\mathrm{LF}_a \leftarrow \min_{b \in S(a)}(\mathrm{LF}_b - \hat d_b)$；以及 §3.6 Scope "Standalone requests use zero slack"。
- **问题与机制**：三个子问题。

  1. **无资源约束**：Alg 1 是无限资源 CPM。两个并行 segment 若落在同一个过载 DP 上，实际不可能按 $\hat d$ 并行完成。CPM 的 total float 因而**系统性高估** slack → 系统系统性**欠保护**。排队延迟也完全不在图里。
  2. **DAG 增量揭示导致 slack 不稳定**：多智能体的子 agent 是运行时 fork 的，"DAG incomplete"是**常态**而非异常。第 8 行 $T=\max\{\mathrm{EF}_a\}$ 只在当前已知残图上取最大，因此每当新分支出现，$T$ 增大、所有叶子的 $\mathrm{LF}$ 增大、slack **跳变**。这意味着同一请求的 $\sigma_r$ 在生命周期内会剧烈波动，而 $\sigma_r$ 正是 tier 判定与排序的唯一输入。§3.5 的 20% hysteresis 只对**阈值**做平滑，对**输入跳变**无效。
  3. **退化路径代价最高**：第 2/4 行任一触发，整个 workflow 的 $\sigma$ 全置 0；加上"Standalone requests use zero slack"。零 slack ⇒ 全部 tier P ⇒ Peer 预算瞬间耗尽 ⇒ 按 P0-06 退化为 FCFS。**保守默认值把系统推向最昂贵且最无区分力的状态**，且这是可预期的常态而非边缘情况。另外，单个 segment 的预测缺失会让整个 workflow 归零（第 4 行是全局 return），粒度过粗。
- **可执行修改**：(a) 在 CPM 之上加一层简单的资源修正：至少把每个 DP 的排队长度折算为 $\hat d$ 的加项，或在评估中报告"CPM 预测的 EF 与实际完成时间的误差分布"。(b) 报告 $\sigma_r$ 的**时间稳定性**指标（例如每请求 $\sigma$ 的变异系数、tier 翻转次数/请求），并说明 hysteresis 是否足够。(c) 把第 4 行从全局 return 改为按 segment 降级（缺预测的 segment 用历史均值 + 置信区间下界）。(d) 为"零 slack 洪泛"设计显式的二级排序（即 P0-06 的密度排序），并在评估中给出 DAG 可见度为 0%/50%/100% 时的表现。
- **验收标准**：在 DAG 可见度 0% 的极端情形下，系统开销（复制字节、前台 P99）不超过关闭 Peer 层时的某个明确上界（例如 +5%）；且 tier 翻转率有报告。
- **范围**：算法（(a)(b)(c) 无需新硬件可先做分析与模拟；(d) 需新实验）。

---

### P1-11｜$p_r=(g_r+1)\bmod n$ 造成接管热点与备份故障域集中
- **位置**：§3.4，第 4–5 页："A simple mapping for $n \ge 2$ DPs is $p_r = (g_r+1) \bmod n$; per-request assignments may distribute load across several targets."
- **问题与机制**：默认映射把 rank $g$ 上**所有**请求的重试与 Peer 副本集中到唯一的邻居 $g+1$。故障发生时该邻居同时承担：自己的前台负载 + 接管的全部重试 + 已 pin 住的 Peer 副本。三者在同一块 HBM 上竞争，且 §3.6 的预算规则会因"前台需求上升"而**降低** $B_p$——但已被活引用 pin 住的副本无法回收（Alg 3 第 8 行只回收零引用对象）。于是出现死结：正是需要这些副本的时刻，它们变成了前台内存压力的来源。论文写了"may distribute load across several targets"但没有给出策略、没有给出负载感知、与 Router 的 load+locality 调度也没有耦合。

  第二个问题：**$p_r$ 自身的故障域**。若 $p_r$ 而非 $g_r$ 失效，所有以它为目标的请求同时失去备份，需要重新分配目标并重建副本——一次突发复制风暴，且在重建完成前处于无保护窗口。§3.4 只写了"A failed target requires a new valid assignment"，没有代价分析。
- **可执行修改**：(a) 把 $p_r$ 的选择改为负载/容量感知，并与 Router 共享状态；给出扇出度参数 $f$（每个源 rank 的备份目标数），在评估中扫描 $f \in \{1,2,4\}$，权衡"接管热点"与"元数据/局部性"。(b) 增加 $p_r$ 失效的处理路径与代价模型。(c) 在评估中加入故障风暴场景（见 §4 的 F3）。
- **验收标准**：故障后接管 rank 的前台 P99 TPOT 退化有上界报告；$f>1$ 时该退化显著低于 $f=1$。
- **范围**：算法（需新实验；$f$ 的引入属设计决策）。

---

### P1-12｜层级迁移的瞬态：R→P 时存在保护空窗与突发复制，未建模
- **位置**：§3.5（tier 定义与触发条件，第 6 页）与 §3.6（"Low-priority copying is rate-limited (default 20% of link capacity)"，第 7 页）。
- **问题与机制**：一个请求初期 slack 大 → tier R → **没有任何备份**（Alg 2 第 5 行直接 continue，连 $D_s$ 都不加）。随后 DAG 更新或兄弟分支变慢，slack 归零 → tier P。此刻系统需要一次性把全部已密封历史搬到 DRAM 再到 Peer。用论文参数：20 GiB 的历史、20% 链路限速、64 GB/s 链路 → $20/(0.2\times64) \approx 1.6$ s 仅 DRAM 一段，Peer 段还要再来一次。在这 1.6 s+ 内请求**完全无保护**，而它此时恰是零 slack 的关键路径请求。

  更糟的是这个迁移是**相关触发**的：join 临近时，多个分支会几乎同时从 R 掉到 P，产生同步的复制突发，正好撞上前台负载高峰。20% 限速会让它更慢，形成"越需要越慢"的正反馈。
- **可执行修改**：(a) 在 §3.5 显式定义"protection lag"：从 tier 变更到副本实际提交的时间，并给出其上界表达式（历史字节 / 有效复制带宽）。(b) 考虑对 tier R 也保留**增量 DRAM 密封**（即 $D_s$ 始终累加，只有 Peer 层受预算约束）——这会把迁移成本从 $O(\text{全历史})$ 降到 $O(\Delta)$，代价是 P0-03 提到的 DRAM 容量压力，需要一起治理。(c) 在评估中报告 protection lag 的分布与"故障恰好落在空窗内"的比例。
- **验收标准**：protection lag 的 P99 有报告，且在层级迁移率最高的工作负载下不超过某个明确阈值。
- **范围**：算法（(a)(b) 属设计决策；(c) 需新实验）。

---

### P1-13｜容量控制的两个时钟不同步；preview 与实际分配的偏差无指标；50% clamp 不构成 R4 所说的"bound"
- **位置**：§3.6 与 Algorithm 3，第 7–8 页：第 4–5 行 $B_p \leftarrow$ pool − demand − headroom，clamp 到 $[0, \text{pool}/2]$；第 7 行 "Pause new space reservations above the budget"；§3.5 "Real allocation rechecks availability atomically; it may admit fewer objects than the preview."
- **问题与机制**：

  1. **两个时钟**：$L_r$ 在任意 policy event 变化，$B_p$ 只在 window boundary 变化。Alg 2 的 Preview 基于虚拟快照 $S$；Alg 3 第 7 行在预算收缩时只"暂停新预留"，而已 pin 的物理占用可以超出新目标（作者自己写了"Physical usage can therefore exceed a newly reduced target"）。结果是 Master 的 preview 会**持续高估**可用容量，产出大量"预览通过、实际失败"的计划。论文承认了这个现象但**没有任何指标、没有回退策略、没有收敛性论证**。
  2. **50% clamp 不是开销上界**：R4 说"Bound normal-service replication overhead"。把 KV pool 的一半让给备份，意味着前台 batch size 可能腰斩——这在 LLM 服务里是数十个百分点的吞吐损失，不能称为"bounded overhead"。论文需要把开销约束表达在**前台 SLO** 上（吞吐/TTFT/TPOT），而不是内存比例上。
  3. **引用排空可能很慢**：§3.6 写"Completion releases that request's Peer references while preserving shared references"。在前缀共享普遍的 agent 工作负载里，共享块的引用计数可能长期非零（跨轮次、跨 agent），使"referenced copies drain as requests finish"这一假设失效。
- **可执行修改**：(a) 定义并报告 `preview_admit_rate`（预览通过且实际成功 / 预览通过）与 `budget_overshoot`（物理占用 − 目标）/ pool 的时间序列；给出 overshoot 的收敛时间上界。(b) 把 R4 重写为 SLO 形式："前台 P99 TPOT 退化 ≤ $\epsilon$"，并让 $B_p$ 的更新以此为控制目标（当前公式是开环的前馈估计，没有反馈）。(c) 分析共享引用的排空时间分布。
- **验收标准**：存在一个负载扫描实验，显示 $B_p$ 控制器在前台需求阶跃变化后的 overshoot 收敛时间与前台 SLO 退化幅度，且二者都有界。
- **范围**：算法（需新实验；R4 的重述属设计决策）。

---

### P1-14｜"保护不可满足"时没有反馈闭环
- **位置**：§3.4–§3.6 的组件接口。§3.6："If free space and safe victims are insufficient, the Peer increment is denied and the request retains its DRAM path."；§3.5："A tier-P request without a Peer grant retains DRAM recovery."
- **问题与机制**：这是一个**接口层面的逻辑漏洞**。一个请求被判为 tier P 的定义就是 $\sigma_r < R_D$，即"DRAM 恢复也无法满足 slack"。当 Adapter 拒绝 Peer 授权时，系统把它退回到一个**按定义已知不足**的路径，然后什么也不做：不通知 Tracker、不通知 Router、不触发重调度、不向上层 agent runtime 报告风险、也不记录为 SLO 违约。

  这意味着系统在"我知道这个关键路径请求得不到足够保护"的状态下静默运行。对一个以 WCT 为优化目标的系统，正确的行为应该是把这个信息反馈出去——例如让调度器避免再往该源 rank 放关键路径请求、或提前提高该请求的 checkpoint 频率、或向 agent runtime 暴露一个"此分支高风险"的信号以便上层做 speculative 备份分支。
- **可执行修改**：(a) 定义显式的 `protection_unsatisfiable` 状态与其在控制面的传播路径；(b) 至少给出一个消费者（Router 的放置决策，或 Tracker 的 slack 重算把预期恢复延迟计入 EF）；(c) 在评估中报告该状态的发生率及其与 WCT 尾延迟的相关性。
- **验收标准**：系统能报告"未被满足的保护需求"占比，且该指标与观测到的 WCT 退化相关；存在至少一条基于该信号的反馈动作。
- **范围**：跨章节（设计决策 + 新实验）。

---

### P1-15｜共享前缀的收益归因错误；跨请求前缀缓存作为恢复源被忽略
- **位置**：§3.5（"Each candidate previews incremental admission ... accounting for shared copies"）与 §3.6（"Existing copies can be shared"）。
- **问题与机制**：论文在**成本**侧处理了共享（去重、共享引用），但在**收益**侧没有。保护一个被 $k$ 个 agent 共享的前缀块，其收益是 $k$ 个请求收益之和，还包括未来会命中该前缀的请求——这是一个正外部性。按请求逐个打分的贪心（Alg 2 第 3–14 行）无法捕获它：第一个请求看到的是"我一个人的收益 / 全部字节"，会低估；后面的请求看到的是"零增量成本"，会高估。两侧都错，且方向相反。

  在多智能体编码工作负载中这不是边缘情况——共享的系统提示 + 仓库上下文可能占历史的大部分，这也正是论文自己用 hash-block 计数的原因。

  同时，共享意味着一个更便宜的恢复源：丢失的前缀块很可能仍驻留在**其他 GPU 的前缀缓存**里。AegisKV 完全没有考虑从同伴的 live cache 恢复，而这可能比 DRAM 更快且零额外内存成本。
- **可执行修改**：(a) 把打分单位从"请求"改为"保护对象"，收益按当前引用数 + 预期未来引用数加权；(b) 在 §3.4 的恢复路径里增加第四条"peer live-cache reuse"，并说明其与 Peer backup 的关系（是否可以完全替代小 $L_r$ 的 Peer 层？）；(c) 在评估中报告工作负载的前缀共享率，并做共享率扫描。
- **验收标准**：在高共享率（≥50% 历史块被 ≥2 个请求引用）工作负载下，对象级归因相对请求级归因有可测的 WCT 收益。
- **范围**：算法（(b) 属重大设计决策；(a)(c) 需新实验）。

---

### P1-16｜魔数全部未做敏感性；热块统计存在冷启动盲区
- **位置**：§3.5 第 6 页："reviews an active request after each additional $Z$ generated tokens"、"Tier changes use 20% hysteresis"、"Hot-block statistics use the preceding 512 decoding steps"、"An optional block leaves the candidate set after two successive decoding-statistics windows"；§3.6 "rate-limited (default 20% of link capacity)"、"clamped between zero and half of the pool"；式 (2) 的 $h$。
- **问题与机制**：至少 7 个配置常数（$Z$、hysteresis 20%、512 步统计窗、2 窗淘汰、20% 限速、50% clamp、$h$）全部为固定值，全部无敏感性分析。§3.6 的 Scope 段只说"The configured checkpoint interval needs sensitivity analysis"，但其余 6 个连这句话都没有。

  **冷启动盲区尤其具体**：刚完成 100K+ token prefill、尚未解码 512 步的请求，是恢复成本**最高**的（$T_{rc}$ 最大）、也是最可能被判为 tier P 的；但它恰恰**没有解码统计**，HotSet 只能退化为 mandatory 块 + recency。而 Figure 3(c) 显示 recency 的覆盖率明显低于 past-frequency（NOSA 上低 18 个百分点）。**机制在最需要它的时刻最弱。** 论文没有为这种状态定义任何替代策略（例如用 prefill 阶段的选择器输出做初始化）。

  另一个：$h$ 是"fixed ... configured for each model and sparse-attention method"，即静态配置。但全文主张"request-specific"，$L_r$ 是每请求自适应的而 $h$ 不是——这个不对称没有理由。
- **可执行修改**：(a) 做参数敏感性表（至少 $Z$、$h$、限速、clamp 四项），标注默认值的选择依据。(b) 为冷启动定义显式策略：用 prefill 阶段的选择器统计初始化 HotSet，并在评估中对比"冷启动请求"与"热请求"的恢复延迟。(c) 说明为何 $h$ 不随请求自适应，或把它纳入 $L_r$ 的联合选择。
- **验收标准**：存在参数扫描表；冷启动请求的恢复延迟与热请求的差距有报告且被讨论。
- **范围**：算法（(a)(b) 需新实验；(c) 可在修订中论证）。

---

### P1-17｜Insight 1 的证据类型与用途不匹配；slack 是差值，误差会放大
- **位置**：§3.1 Insight 1 与 Figure 3(a)，第 4–5 页："Heddle [24] reports trajectory-length correlations of approximately 0.72, 0.88, and 0.94 for coding, search, and math agents after two steps"；图注："these are literature results, not AegisKV runtime-error measurements"。
- **问题与机制**：三重错配。(1) **量不同**：Pearson 相关衡量的是**轨迹长度**（步数）的线性关系，AegisKV 需要的是**剩余时间（秒）**的绝对误差。$r=0.72$ 完全可以对应 ±50% 的相对误差。(2) **误差传播**：slack 是 $\mathrm{LF}-\mathrm{EF}$，是两个预测量的**差**，且 $\mathrm{EF}$ 沿路径累加、$T$ 取全图最大——最大值算子会放大正向误差。一条路径上 $k$ 个 segment 各有 $\epsilon$ 的误差，slack 的误差可达 $O(\sqrt{k}\,\epsilon)$ 甚至更差。论文没有做任何误差传播分析。(3) **领域**：Heddle 的场景是 agentic RL rollout，与生产 agent 服务的执行特征未必一致。
- **可执行修改**：(a) 明确写出"我们需要的是 $\hat d$ 的相对误差分布，而文献给出的是相关系数；二者关系待测"。(b) 增加**噪声注入研究**（可纯模拟，不需要真实预测器）：向真实 $\sigma$ 注入 $\pm x\%$ 误差，$x \in \{0,10,25,50,100\}$，观察 WCT 收益的衰减曲线，并报告层级误判的混淆矩阵（R/D/P 三类）。这张图会是全文最有说服力的鲁棒性证据之一，且**成本很低**。(c) 在评估里给出 GBDT 在 [18] 轨迹上的实际误差（预测器本身可离线训练评估，无需在线系统）。
- **验收标准**：存在"slack 误差 → WCT 收益"的衰减曲线；在 $x=50\%$ 时系统仍优于最强静态基线，或作者明确说明可接受的误差上界。
- **范围**：算法 + 动机（(b) 无需新硬件；(c) 只需离线训练）。

---

### P2-18｜图表灰度可读性、单位混用与跨图参数不一致
- **位置**：Figure 2（第 3 页）、Figure 3(b)(c)（第 4–5 页）、Figure 5（第 7 页）；Figure 2 图注 "K = 1,024; M = $10^6$"。
- **问题与机制**：
  1. **Figure 2 灰度不可读**：图注明写"Color denotes path; line style and marker denote model"——路径（HBM/DRAM/Recompute）这个**最重要的区分维度**只用颜色编码。蓝/橙/红在灰度下极易混淆，直接违反 CFP 的灰度可读要求。同时 12 条曲线挤在跨 4 个数量级的 log-log 图上。
  2. **单位混用**：同一横轴上 $K=1024$ 而 $M=10^6$，于是 "1M" ≠ "1024K"，刻度不自洽。
  3. **Figure 3(b) 不支撑其论点**：作者自己写"establishes release examples, not deployment share"。一张不能支撑论点的散点图占用了宝贵版面（见 P2-19 的页数预算）。
  4. **跨图参数不一致（实质性）**：§2.3 假设 64 GB/s per rank，Figure 5 假设 6.25 GB/s——相差 10 倍，而这个参数正是决定"Peer 层是否值得存在"的关键。此外，Figure 5 中 "147 MiB of Peer residency" 对应 7 层热块；按图注参数（$D=5.37$ ms/层 @ 6.25 GB/s ⇒ 每层约 33.6 MB 全量 KV）反推，$h \approx 0.6$–0.66，而 Figure 3(c) 用的是 $h=0.4$。两处 $h$ 不一致且 Figure 5 未声明 $h$。
  5. **图注过长**：Figure 1 的图注约 13 行、Figure 3 约 10 行，承载了本应在正文的方法细节；且 ACM 模板默认图注字号小于正文，需核对是否满足≥10pt。
- **可执行修改**：(a) Figure 2 改为 2×2 small multiples（每模型一格，格内 3 条路径用实线/虚线/点线 + 不同 marker），删除颜色依赖；统一为 $1\text{K}=1024$、$1\text{M}=1024\text{K}$ 或全用十进制并注明。(b) 删除 Figure 3(b)，改为正文一句话 + 一个 4 行的表（或直接引用），腾出的空间给 P0-01 的总体面板。(c) Figure 5 的 5 类图例改用 hatch pattern；在图注中声明 $h$ 并解释 6.25 GB/s 与 §2.3 的 64 GB/s 为何不同（或统一）。(d) 把图注压到 ≤5 行，方法细节移入正文；核对全部图内文字字号。
- **验收标准**：把 PDF 转成灰度并以 100% 缩放打印，所有曲线/柱条可区分；全文带宽与 $h$ 参数在一张表中集中声明且各图引用一致。
- **范围**：表达（无需新硬件）。

---

### P2-19｜结构缺失与页数预算不可行；防御性免责句过密
- **位置**：全文结构；§2.2/§2.3/§3.1/§3.5/§3.6 的免责句（粗略统计 ≥20 处，如 "This cost substitution does not constitute physical failure replay"、"These are planning estimates, not delay guarantees"、"Bars/whiskers are document means/ranges, not fault-recovery runs"）。
- **问题与机制**：
  1. **缺 §1 Introduction**。审稿人读的第一页决定基调，而本稿没有引言、没有贡献列表、没有结果预览。即使本轮只提交部分章节，最终稿的引言质量是可接受与否的关键。
  2. **页数预算不可行**：当前 §2 约 3 页、§3 约 4.5 页。加上引言（≈1.25）、实现（≈0.75）、评估（≈3.5）、相关工作（≈0.75）、结论（≈0.25），合计约 14 页，超出12 页正文限制约 2 页。必须现在就做压缩规划：§2.3 的 AIConfigurator 方法细节（HYBRID、DSA 表外推、25 组合的静态内存检查）整段移到 supplementary；§3.5/§3.6 的运行时契约细节可压缩 30%。
  3. **免责句密度**：诚实是优点，但目前的写法像一份预先写好的 rebuttal，反而会让审稿人觉得作者自己也不相信这些证据。建议每个小节末尾集中一个 "Scope of this analysis" 的 2–3 句话，而不是每段一句。
  4. **术语不统一**：Peer / Peer HBM / Peer budget / Peer protection；tier R vs Tier R；protection object vs (layer, block) vs logical layer-block object；"known 64-token tail"（其实是一个贯穿全文的**假设**，应改名为 "assumed replay tail" 并在首次出现处给出依据）。
- **可执行修改**：(a) 现在就写出引言骨架与贡献列表（4 条，每条对应一个可验证的结果）。(b) 做一张页数预算表并据此裁剪。(c) 合并免责句。(d) 建一张术语表，全文统一。
- **验收标准**：完整稿正文 ≤12 页；随机抽 3 页统计免责句数量 ≤3 句/页。
- **范围**：表达（无需新硬件）。

---

## 3. 跨组件接口自洽性检查与具体失败场景

我把四个组件的输入/输出契约摆在一起看，发现**三处接口不自洽**，并据此给出四个具体的失败或退化场景。

### 3.1 接口不自洽

**I-A｜时间基准不一致（Tracker ↔ KV Master）。** Tracker 输出的 $\sigma_r$ 来自一张**不含故障、不含恢复争用、不含资源约束**的计划图（Alg 1）。KV Master 用它与 $R_R/R_D$ 比较，而后者包含 $R_{floor}$（检测 + 重路由 + 重新准入）。两个量的定义域不同：$\sigma$ 是"在无故障世界里可以晚多久"，$R$ 是"在有故障世界里要花多久"。更关键的是，$\sigma \ge R_R$ 判定"不需要备份"时，没有把**恢复本身对下游的连锁影响**计入——恢复占用的 GPU 算力会拖慢同 rank 上其他 workflow 的 EF，而 Alg 1 从不知道这件事。建议：在 Alg 1 的 $\hat d_a$ 里加入一个可选的"recovery-induced delay"项，或至少在论文中承认 $\sigma$ 与 $R$ 不可直接比较并给出修正系数。

**I-B｜决策时钟不同步（KV Master ↔ Adapter）。** $L_r$ 在 policy event 变，$B_p$ 在 window boundary 变，物理占用在引用归零后才变。三个时钟互不对齐，而 Alg 2 的 Preview 用的是**虚拟快照**，Alg 3 第 7 行在收缩时只"暂停新预留"。结果是"preview 通过 → 实际分配失败"的路径没有定义重试语义：失败后是立即重评 $L_r$？等下一个 checkpoint？还是永久退回 DRAM？论文只说"it may admit fewer objects than the preview"，没有定义后续行为。这是一个**真实的设计漏洞**，不是表述不足。

**I-C｜没有降级反馈通道（Adapter → 上层）。** 见 P1-14。Adapter 拒绝后信息就地丢失。

### 3.2 失败/退化场景

**场景 A｜恢复风暴 + 接管热点死结（综合 P0-04、P1-11、P1-13）。**
设 8 个 DP rank，$n=8$，$p_r=(g_r+1)\bmod 8$。rank 3 上有 24 个活跃的长上下文 agent 请求（平均 80K 上下文）。rank 3 fail-stop。
1. 24 个重试**全部**涌向 rank 4。rank 4 的前台负载翻倍。
2. 24 个 DRAM 恢复共享带宽：$24 \times 12.5\ \mathrm{GiB} = 300\ \mathrm{GiB}$，按 64 GB/s 需约 **4.7 s**，而 KV Master 在做层级判定时用的 $W_0$ 是单请求值（约 200 ms），低估 20 倍以上。
3. 按式 (1)，这些请求本应有相当一部分被判为 tier P（因为真实 $R_D$ 远大于 $\sigma$），但实际被判为 tier D，**故障前没有为它们准备 Peer 副本**。
4. rank 4 的 Adapter 观察到前台需求上升 → 下一个窗口把 $B_p$ 调低 → 拒绝新的 Peer 分配；但已有的 Peer 副本被活引用 pin 住（Alg 3 第 8 行只回收零引用），无法回收。
5. 净效果：rank 4 同时承受 2× 前台负载 + 4.7 s 的传输风暴 + 无法释放的备份内存。真实 WCT 损失远超 Figure 1(c) 预测的 17–32 s。
**这个场景不是极端情况，而是"单 GPU fail-stop"这个失效模型的典型实例**——论文的失效模型和它的成本模型（单请求、无争用）之间存在结构性不匹配。

**场景 B｜DAG 不可见导致的全局退化（综合 P1-10、P0-06）。**
一个用 LangGraph 式框架的部署没有上报完整 DAG（或子 agent 在运行时才 fork，DAG 天然不完整）。
1. Alg 1 第 2 行触发 → 整个 workflow 的 $\sigma \equiv 0$。
2. 全部请求 $\sigma < R_D$ → 全部 tier P。
3. Alg 2 第 3 行的排序键 $(\sigma_r,\mathrm{ID}_r)$ 首分量全相同 → 退化为按到达顺序 FCFS。
4. Peer 预算被最早到达的请求占满，与工作流价值完全无关；且由于引用 pin，后到的关键请求即使 slack 真的为 0 也拿不到资源。
5. 系统付出了 Tracker（每次到达/完成都跑一次 CPM）、KV Master（每 $Z$ token 一次多候选打分与 preview）、Adapter（窗口预算 + LRU）的全部控制面开销，却做出了与"随机分配"等价的决策。
**这是可预期的常态而非边缘情况**，因为多智能体系统的 DAG 本质上是增量揭示的。论文必须报告这个模式下的开销上界。

**场景 C｜选择器状态跨层混合导致热块全失效（P0-07 的具体化）。**
DeepSeek-V3.2 风格的 DSA 部署，$L_r=7$（32 层中的前 7 层有 Peer 热块）。故障后：
1. 第 1–7 层：KV 与 indexer keys 来自 Peer 副本（原始数值）。
2. 第 8–32 层：由重算产生（不同的 batch 组成 → 不同的归约顺序 → 数值不同）。
3. 第 8 层的 indexer 输入来自第 7 层的输出——而第 7 层是"原始"的、第 8 层的权重计算是"重算"的。两者拼接后，第 8 层的 top-$k$ 选择可能与故障前不同。
4. 若选择漂移，§3.5 基于故障前统计构造的 $H_{r,l}$（$l>7$ 的层作为 "recovery-preload hints"）失效，全部走 demand fetch。
5. Figure 5(d) 的 20 ms 退回到接近 (b) 的 83 ms 甚至更差（因为 demand fetch 是随机访问而非顺序预取）。
**论文当前的措辞 "Placement changes neither selector outputs" 不足以排除这个场景**，因为漂移的原因不是 placement，而是恢复路径本身的数值异质性。

**场景 D｜冷启动请求的保护空窗（P1-12 + P1-16 的交汇）。**
一个 agent 刚完成 110K token 的 prefill，正要开始解码。此刻它：(i) $T_{rc}$ 最大（约 35 s，见 Figure 1(c)）；(ii) 解码统计为空 → HotSet 只能用 mandatory + recency，覆盖率按 Figure 3(c) 是三个模型里最低的一档；(iii) 如果它之前是 tier R，现在刚转 P，还要等 1.6 s+ 的复制（P1-12）。**三个弱点在同一时刻叠加**，而这恰好是恢复成本最高的时刻。论文没有任何机制识别或补偿这个窗口。

---

## 4. 最小但有说服力的评估矩阵

下表是我认为能让这篇论文**及格**的最小集合（不是理想集合）。标注：🟢=无需新硬件，改稿/重分析/模拟即可；🟡=必须做新实验；🔴=需要重大设计决策后才能定义实验。

### 4.1 基线（至少 B0、B1、B2、B4 必须有）

| ID | 基线 | 说明 | 标注 |
|---|---|---|---|
| B0 | No protection | 纯重算，下界参考 | 🟡 |
| B1 | Full DRAM streaming | DéjàVu 式全量 KV 流式备份 | 🟡 |
| **B2** | **现有栈的 DRAM 卸载** | vLLM APC / LMCache / Mooncake Store 式分层 KV（**最关键的基线**，见 P0-09） | 🟡 |
| B3 | Cost-first | 按 $T_{rc}$ 或 KV 字节排序分配，不用 slack | 🟡 |
| B4 | Slack-only tiering | 只做 R/D/P 分层，不做 $L_r$/热块 | 🟡 |
| B5 | Erasure-coded backup | GhostServe 式，说明为何选复制而非 EC | 🟡 |
| B6 | Offline oracle | 已知故障时刻与真实 slack 的上界 | 🟢（模拟） |

### 4.2 消融

| ID | 消融项 | 目的 | 标注 |
|---|---|---|---|
| A1 | 去 slack（排序改为 FCFS / 成本序 / **密度序**） | 验证 R1；同时检验 P0-06 的反例 | 🟡 |
| A2 | 热块排序：past-freq / recency / random / 全层前缀 | 验证 Insight 3 是否转化为端到端收益（P0-08） | 🟡 |
| A3 | 固定 $L_r$ vs 自适应 $L_r$ | 验证请求特定深度的价值 | 🟡 |
| A4 | 固定 $B_p$ vs 窗口化控制 | 验证 Alg 3 的必要性 | 🟡 |
| **A5** | **slack 噪声注入 $\pm\{0,10,25,50,100\}\%$** | 鲁棒性；**成本最低、说服力最高**（P1-17） | 🟢 |
| A6 | 参数扫描：$h$、$Z$、限速、clamp | P1-16 | 🟡 |
| A7 | 前缀共享率扫描 | P1-15 | 🟡 |

### 4.3 工作负载

| ID | 负载 | 要点 | 标注 |
|---|---|---|---|
| W1 | CC/Weka [18] **全量**回放 | 必须包含无并行的 session，不能只用 286 个保留组（P0-01） | 🟢（分析）/🟡（回放） |
| W2 | 第二个领域/框架 | 单一 coding trace 无法支撑外部效度；search/math agent 或合成 DAG 生成器 | 🟡 |
| W3 | 合成 DAG 扫描 | 扫 fan-out 度、分支时长方差、DAG 可见度（0%/50%/100%） | 🟢（模拟） |

### 4.4 故障

| ID | 场景 | 要点 | 标注 |
|---|---|---|---|
| F1 | 单 GPU fail-stop，**故障时刻均匀采样** | 不能只在一个时刻注入（P0-01） | 🟡 |
| F2 | 备份目标 rank 故障 | P1-11 未覆盖的路径 | 🟡 |
| **F3** | **恢复风暴**（单 rank 上 $k$ 个并发请求，扫 $k$） | 场景 A；本文最缺的实验 | 🟡 |
| F4 | 检测延迟扫描 $R_{floor} \in \{0.1, 1, 10\}$ s | 若 $R_{floor}\gg$ 收益，Peer 层无意义 | 🟢（分析）/🟡（实测） |
| F5 | 慢节点/部分降级 | 超出当前失效模型，至少讨论 | 🔴 |

### 4.5 指标

| ID | 指标 | 说明 | 标注 |
|---|---|---|---|
| M1 | WCT P50/P95/P99 + 相对无故障的 inflation | 主指标（R1） | 🟡 |
| M2 | 暴露恢复时间 $(T-\sigma)^+$ 的分布 | 连接动机与结果（R2） | 🟡 |
| M3 | 正常服务开销：吞吐、TTFT/TPOT P99、复制字节/请求·秒、链路与 HBM 带宽占用 | R4 的**真正**验收口径（见 P1-13） | 🟡 |
| M4 | 保护可满足率；`preview_admit_rate`；`budget_overshoot` 收敛时间 | I-B、I-C、P1-13、P1-14 | 🟡 |
| M5 | slack 预测误差分布 + 层级误判混淆矩阵 | P1-17；预测器可离线评估 | 🟢 |
| M6 | 控制面开销：CPM 频率与延迟、决策/秒、CPU 核数 | Alg 1/2 在高请求率下的可扩展性 | 🟡 |
| M7 | 正确性：恢复后 vs golden run 的 token 级一致率；tool 重复调用计数；选择漂移率 | P0-07、场景 C | 🟡 |

### 4.6 优先级建议（若只能做三件事）

1. **A5（噪声注入）+ W3（合成 DAG 扫描）+ P0-01 的总体重分析**——全部 🟢，成本最低，但能一次性回答"动机是否成立""预测误差是否致命""适用范围多大"三个最致命的问题。
2. **F3（恢复风暴）+ B2（现有栈基线）**——🟡，但这两个决定了论文的核心论点（Peer 层是否必要、99% 的收益是否可归于本文）。
3. **M3 + M7**——🟡，对应 R4 和 R5，缺任一条都难以在 EuroSys 的 dependable systems 语境下站住。

### 4.7 必须先做设计决策才能定义实验的项（🔴）

- P0-05 的目标函数重述（加权和 → 约束优化）；
- P0-03 的 DRAM 层治理（是否纳入统一预算框架）；
- P0-07 的一致性模型定义与 tool 幂等性契约；
- P1-11 的 $p_r$ 分散策略（引入扇出参数 $f$）；
- P1-14 的降级反馈接口；
- P1-15 的跨请求前缀缓存作为恢复源。

---

## 5. 五条最有价值的英文改写 / 图表重构建议

**① 摘要末句（第 1 页）——移除无证据的性能承诺。**
现状："Experiments show that AegisKV substantially reduces workflow completion time under failures while introducing negligible overhead during normal inference."
问题：本稿无实验；且 "substantially" / "negligible" 是未量化的承诺，审稿人会直接标记。
建议改为（在有数字前的占位形式）："We analyze recovery costs and workflow slack on production agent traces, and specify a protection policy that allocates backup capacity by workflow-level delay exposure rather than by recovery cost alone. §N evaluates AegisKV against full-DRAM replication and cost-ordered protection under injected worker failures, reporting workflow completion time, exposed recovery wait, and steady-state serving overhead."
（有数字后再替换为具体区间，例如 "reduces P95 WCT by X–Y% at Z% throughput cost"。）

**② §2.2 的样例挑选句（第 2 页）——把自认的偏差转为明确的结构性说明。**
现状："Among groups with four or five branches and a gap near 100 s, we select one with a longer critical-branch prefix to illustrate recovery exposure, not population-average failure impact."
问题：读者读到的是"我们挑了对自己有利的例子"，而没有被告知总体是什么样。
建议改为："Figure 1(b–c) is a deliberately chosen case, not a representative one: we picked a group with a long critical-branch prefix so that the cost–slack divergence is visible at a single glance. Figure 1(a′) reports the same quantity over all 286 retained groups and all failure instants, where the rank correlation between recovery cost and WCT loss is $\rho = \_\_$; the case study is consistent with, but does not establish, that population result."

**③ §2.3 的收益归因句（第 3 页）——目前这句话在为放弃 Peer 层做论证。**
现状："Thus, backups avoid computation, while HBM's incremental value over DRAM comes from reducing transfer waiting."
问题：读者会立刻算出 32 s : 0.3 s : 0.02 s，并得出"只要做 DRAM 就够了"的结论。必须在同一段里给出 Peer 层的存在区间。
建议改为："Under single-request, uncontended assumptions, a DRAM copy removes almost all of the recovery cost, and peer-HBM residency removes a further $\sim$335 ms of modeled transfer wait — roughly 1% of the total. Peer residency therefore matters only where the DRAM path itself is contended: a single worker failure triggers $k$ concurrent restores that share host bandwidth, so the DRAM wait grows as $\Theta(k)$ while recomputation parallelizes across surviving GPUs. §N quantifies this crossover; it, not the single-request numbers above, is what motivates a peer tier."

**④ §3.5 的打分句（第 6 页）——从不可比的加权和改为显式约束优化。**
现状："The score adds predicted foreground delay from the candidate's backup work and memory occupancy to recovery delay beyond the request's slack, weighted by source-failure probability from the configured risk model over the same policy horizon."
问题：量纲不可比；$p_{\text{fail}}$ 加权在现实 MTBF 下把最优解压成 $L_r=0$；且与式 (1) 隐含的 $p_{\text{fail}}=1$ 矛盾。
建议改为（并在正文给出对应公式）："We select depths by maximizing expected exposed-wait reduction per byte, subject to two explicit budgets: the target's peer capacity $B_p$, and a foreground service budget $\epsilon$ expressed as tolerated P99 TPOT degradation. Formally, for each request we choose $d$ maximizing $[\,\min(R_D, R_P(0)) - R_P(d)\,]^{+}_{\sigma_r} / \mathrm{bytes}(d)$, and admit candidates in descending order of that density until either budget binds. Failure probability enters only through the admission budget, not through a per-candidate weight; we report sensitivity to it in §N."

**⑤ Figure 2 重构 + 参数集中声明（第 3 页）。**
现状：单张 log-log 图，12 条曲线，**颜色**编码最重要的维度（恢复路径），且 $K=1024$ 与 $M=10^6$ 混用；同时 §2.3 的 64 GB/s 与 Figure 5 的 6.25 GB/s 相差十倍，Figure 5 未声明 $h$。
建议：(a) 改为 2×2 small multiples，每格一个模型；格内三条路径用 **实线/虚线/点线 + 圆/方/三角 marker**，颜色仅作冗余编码；(b) 统一 $1\text{M}=1024\text{K}$（或全十进制并在图注注明）；(c) 在 §2.3 开头加一张 4–6 行的 "Modeling parameters" 表，集中声明带宽、$h$、chunk size、tail length、TP/EP/PP，全文各图统一引用表中符号，图注只写"parameters as in Table N unless noted"；(d) Figure 5 的图注补上 $h$ 的取值并解释为何用 6.25 GB/s（若是不同互联，请在表中作为第二组参数列出）；(e) 删除 Figure 3(b)，换成两行正文 + 一个紧凑表格，腾出的空间给建议 ② 的 Figure 1(a′)。

---

## 6. 关于投稿时间线的实务建议

CFP 显示Fall 轮全文截稿为 2026 年 9 月 24 日——距今 5 天。本稿缺少引言、实现、评估、相关工作，且上述 P0 中有至少四项（P0-03/04/07/09）需要新实验或设计变更。**赶 9/24 会得到一份"无评估"的投稿，几乎必然被拒**；而 CFP 明确规定在某一轮被拒的论文不能投紧接着的下一轮，这会让你们额外损失一整个周期。

我的建议是：放弃本轮，用这段时间做 §4.6 中标为 🟢 的三件事（噪声注入、合成 DAG 扫描、轨迹总体重分析）——它们不需要新硬件，且恰好能在实现完成之前就验证"动机是否成立"。如果 P0-01 的总体分析显示"成本序与 WCT 影响序高度重合"，或 P0-03 显示 Peer 层的边际收益在任何合理参数下都低于 5%，那么**现在就应该调整立论**，而不是先实现再发现。这比赶一个截稿日更有价值。

需要的话我可以把这份评审整理成 Markdown 文件给你，或者针对其中某一条（例如 P0-05 的目标函数重述，或 §4 的评估矩阵）展开成可直接执行的修改方案。
