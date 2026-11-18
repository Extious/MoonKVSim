## 2 Background and Motivation

多智能体应用通过相互依赖的 LLM 请求完成一个用户任务。执行节点故障后，重建丢失的 KV 可以恢复单个请求，但用户感知的损失取决于整个工作流何时完成。本节从工作流的依赖关系与长上下文的重建代价出发，说明为什么 KV 保护需要以工作流完成时间为目标，并在有限的备份容量与带宽下分配资源。

<table class="motivation-figures">
<tr>
<td width="33%" align="center" valign="top"><a href="../figures/motivation-row/motivation-branch-gap.pdf"><img src="../figures/motivation-row/motivation-branch-gap.png" width="100%" alt="图 1(a)：并行分支持续时间差的经验累积分布"></a></td>
<td width="33%" align="center" valign="top"><a href="../figures/motivation-row/motivation-workflow.drawio.pdf"><img src="../figures/motivation-row/motivation-workflow.drawio.png" width="100%" alt="图 1(b)：四个并行分支的工作流，条长表示真实持续时间，A2 最晚完成"></a></td>
<td width="33%" align="center" valign="top"><a href="../figures/motivation-row/motivation-recovery-exposure.pdf"><img src="../figures/motivation-row/motivation-recovery-exposure.png" width="100%" alt="图 1(c)：同一工作流四个分支的重算时间与 WCT 损失"></a></td>
</tr>
<tr>
<td align="center">(a) 并行分支的耗时差异</td>
<td align="center">(b) 四分支 Workflow 实例</td>
<td align="center">(c) 重算代价与工作流损失</td>
</tr>
</table>

**图 1：面向工作流的 KV 保护动机。** (a) 121 个 CC/Weka 工作流的经验累积分布，每个工作流贡献通过时序 fan-in 筛选的严格重叠组中最大的分支持续时间差，中位数为 138 s，P90 为 1,173 s。汇合关系由全部分支结束后的 Main 请求推断，允许期间存在 Main 请求。(b) 同一批 fan-in 组中的四分支实例，时长差为 91.2 s；该组不是所属工作流的最大差值组。横轴以首个分支启动为零点，条形保留真实起止时间，右侧数字为持续时间（秒），虚线为到汇合的 Slack。A2 决定 151.6 s 的汇合；Main 方框仅示意依赖。(c) 扇出后 29.5 s 的四个独立分支故障反事实；斜纹部分由 Slack 吸收，实色部分暴露给 WCT。重算代价采用与图 2 相同配置的 Qwen3-14B 静态估计，包含假设的 64-token 尾部；该说明性实例不代表总体故障收益。

### 2.1 工作流、故障与 KV 恢复

**多智能体工作流。** 我们将一个工作流表示为有向无环图 $G=(V,E)$：节点是 LLM 请求，边表示请求之间的数据依赖。一个 agent 分支可以包含多轮请求和工具调用，后继节点在其依赖满足后才能执行。工作流完成时间（workflow completion time，WCT）从首个请求释放计至最后一个请求完成。对于给定的执行计划，请求的 Slack 是在不推迟工作流完成的前提下，其完成时间能够延后的最大幅度；关键路径上的请求没有这种余量。

**服务与故障模型。** 我们考虑由多个 GPU worker 提供服务的集群，请求的 KV 按块管理，可复制到其他 GPU 或主机 DRAM 池。这与 [Mooncake](https://www.usenix.org/conference/fast25/presentation/qin) 等将 KV 存储与请求执行分离的架构相容。本文关注单个执行 GPU 或 worker 的 fail-stop 故障：其本地 KV 不再可用，控制面、承载备份的 DRAM 与其他 worker 存活，由已加载相同模型的存活 worker 接管受影响请求。整机故障、网络分区和静默数据损坏不在本节的故障模型内。

**恢复途径与资源代价。** 没有可用副本时，系统需重新执行 prefill 来重建丢失的 KV。DRAM 副本可以避免重建已保存的前缀，但使用前仍需将状态传入 GPU，多个恢复请求会共享传输带宽。若副本预先驻留在实际接管 GPU 的 HBM 中，则可直接供该 GPU 使用；代价是占用原本可用于前台请求的 HBM，并产生故障前的复制流量。因此，备份介质的容量、恢复速度与正常服务开销之间存在权衡。

已有系统通过 KV 流式复制（[DéjàVu](https://proceedings.mlr.press/v235/strati24a.html)）、纠删编码（[GhostServe](https://proceedings.mlsys.org/paper_files/paper/2026/hash/d99e8e80a6c41e148db686918dd7eab3-Abstract-Conference.html)）或结合负载协调检查点与恢复（[LUMEN](https://arxiv.org/abs/2606.17787)）降低故障代价。多智能体应用进一步提出了一个资源分配问题：保护不同请求所节省的恢复时间，对用户等待时间可能具有不同价值。仅以保存的 KV 字节数或避免的重算量衡量保护效果，无法体现这种差异。

### 2.2 请求恢复代价与工作流损失不同

并行分支的汇合决定了依赖这些分支的后继何时能继续：较早完成的分支可以容忍一定延迟，而决定汇合时刻的分支一旦延迟就会推迟后继执行。为刻画这类时间差异，我们分析公开的 [CC/Weka 编码 agent 轨迹](https://huggingface.co/datasets/semianalysisai/cc-traces-weka-062126)。我们先从 393 条会话中提取严格重叠的子 agent 组，即最晚启动的分支早于最早结束的分支，再保留所有分支均已完成、且最后一个分支结束后仍有 Main 请求的组。Main 在分支执行期间可以继续发出请求。轨迹未记录显式结果依赖，因此这里的 fan-in 是根据时序推断的，不能据此验证 Main 是否消费了全部分支输出。

这一筛选保留 121 个工作流中的 286 个并行组。对每个保留组计算最长与最短分支的持续时间之差，再对每个工作流取最大值。图 1(a) 中该差值的中位数为 138 s，P90 为 1,173 s，表明这些工作流的并行分支存在明显的耗时差异。由于分支起点可以不同，持续时间差并不等于汇合处的 Slack，也不能直接解释为能够吸收故障的时间。

图 1(b) 从这些保留的 fan-in 组中选择一个四分支实例，A1–A4 分别持续 60.370、151.612、132.409、129.429 s，最长与最短之差为 91.242 s。该组并非其工作流的最大差值组，因此不作为图 1(a) 中单个样本的展开。各分支内部的请求和工具调用聚合为一条区间，条形位置与长度保留原始时间差。A2 在扇出后 151.6 s 最晚完成，随后 Main 在 157.4 s 发出请求。在后继依赖全部四个分支的假设下，各分支的 Slack 等于其完成时刻到 A2 完成时刻的余量。我们在分支数为 4–5、时长差约 100 s 的候选组中选取关键分支前缀较长的实例，以清楚展示恢复代价与延迟容忍度的区别。

图 1(c) 在扇出后 29.5 s 分别假设一个分支丢失当前历史 KV，四行对应四个独立反事实。该时刻取自四个分支均有活跃 LLM 请求的区间，并按接近公共执行区间中点的规则确定。历史长度 $M_i$ 取该请求的轨迹哈希块计数，范围为 100,864–113,664 tokens，并统一假设存在已知但未提交的 64-token 尾部。重算时间 $T_i$ 直接查询图 2 所用的 Qwen3-14B、A100-SXM、BF16、batch 1 静态模型，从空缓存重建 $M_i+64$ tokens；该尾部状态是反事实假设，不是轨迹中的观测量。分支 Slack $\sigma_i$ 由原轨迹完成时刻离线计算。其他分支、后继执行和排队保持不变时，暴露给 WCT 的损失为 $\max(0,T_i-\sigma_i)$。这是一项跨模型代价替换分析，不是原服务模型的实测故障重放。

A1–A4 的重算代价分别为 35.2、32.2、36.7、38.9 s，暴露给 WCT 的损失却分别为 0、32.2、17.6、17.0 s。A1 的 91.2 s Slack 可以完全吸收重算；A2 的重算代价最低，却因 Slack 为零而产生最大的 WCT 损失；A3 和 A4 的 19.1、21.9 s Slack 则只能部分吸收延迟。因此，避免最多的重算未必带来最大的 WCT 改善。KV 保护需要考虑请求在工作流中的延迟容忍度；在线估计与实际资源竞争的处理由后续设计与评估展开。

### 2.3 长上下文与备份层级的恢复代价

Agent 的多轮交互将代码、工具输出和其他 agent 的中间结果不断加入上下文。保存历史 KV 可以避免故障后的重复计算，但副本所在的存储层级仍会影响恢复延迟。为区分这两种作用，图 2 比较三个起点状态：完整历史 KV 已在接管 GPU 的 HBM 中、相同状态仅在本机 DRAM 中，以及没有可用副本。三条路径统一以已知 64-token 尾部前向结束、全部历史与尾部 KV 可供继续 decode 使用为终点，模型权重均已加载。因此 HBM reuse 仍有尾部计算代价，不能视为零延迟。

当前比较采用 [NVIDIA AIConfigurator](https://github.com/ai-dynamo/aiconfigurator) 0.9.0 的 HYBRID 静态估计，模型为 Qwen3-4B、8B、14B，统一使用 A100-SXM、vLLM 0.14.0、BF16、batch 1、TP 1。HYBRID 在有数据时使用 kernel 性能表，否则使用性能模型；这些请求级恢复时延均为估计，未进行物理恢复测量。HBM 路径设置已缓存前缀为 $M$，仅计算新增的 64 tokens；Recompute 从空缓存计算 $M+64$ tokens。DRAM 路径在相同尾部计算前，串行加入完整历史 KV 的 H2D 时间，按模型实际层数、KV 头数和头维度计算字节量，并采用 AIConfigurator 系统配置中的 32 GB/s 单向 PCIe 带宽假设。不假设传输与计算重叠，也不将该带宽视为测量结果。

在 128K 历史下，三种模型的 HBM reuse 估计为 35–59 ms，DRAM reuse 为 639–730 ms，Recompute 为 31.4–49.6 s。以 Qwen3-14B 为例，DRAM 副本避免了绝大部分历史重算，而完整 HBM 驻留在此串行传输模型下进一步减少约 671 ms 的传输等待。这一区别表明，备份首先避免历史计算，HBM 相对 DRAM 的增量价值则来自减少传输等待；具体增量仍需同条件测量及并发恢复评估验证。

<figure class="paper-figure">

[<img src="../figures/motivation-row/motivation-recompute.png" width="480" alt="图 2：三种 Qwen3 模型的 HBM、DRAM 与 Recompute 恢复延迟静态估计">](../figures/motivation-row/motivation-recompute.pdf)

**图 2：不同历史驻留状态下的恢复延迟估计。** 单栏三个模型面板；A100-SXM、BF16、batch 1、TP 1，K = 1,024。三路径均包含同一 64-token 尾部前向。HBM 为完整历史驻留参照；DRAM 额外计入按 32 GB/s 假设估计的串行 H2D，无传输计算重叠。所有曲线为 AIConfigurator HYBRID 与传输模型的静态估计，不是实测，无独立工作负载或重复计时。模型加载、检测、排队、复制及软件接管开销不计。超过模型原配置长度的点仅作计算形状估计，未验证长上下文正确性。

</figure>

完整历史 HBM 驻留只是一项参照，不等于 AegisKV 的有限热块 Peer 方案。图 2 也不模拟资源竞争，不能直接推出有限备份容量下的 WCT 收益；它说明需要在避免重算与缩短传输等待之间分配保护资源。图 1 则进一步说明，这些恢复时间只有在超过分支延迟余量时才会成为工作流损失。

### 2.4 问题定义与设计目标

<!-- 当前为用户授权的 AIConfigurator 暂定估计版。原生稀疏模型的同条件物理测量仍未补齐；协议和估计口径见 ../../experiments/plans/reuse-latency-insight.md。 -->

AegisKV 要解决的问题是：在备份容量和复制、恢复带宽有限的条件下，哪些请求的哪些 KV 应获得何种保护，才能减少故障对工作流完成时间的影响？依赖关系使不同请求的保护收益不同，长上下文提高了状态丢失的代价，而备份本身又与前台服务竞争资源。

这一问题要求系统满足五项目标与约束：**(R1)** 以 WCT 衡量恢复效果，考虑请求依赖带来的延迟容忍度；**(R2)** 在请求及其 KV 之间分配有限备份容量，使保护减少实际暴露的恢复等待；**(R3)** 支持并发恢复及传输与计算重叠，避免保护策略引入额外的请求级串行等待；**(R4)** 控制正常运行时的复制开销，使备份容量与带宽占用服从前台服务的资源需要；**(R5)** 保持模型计算与 KV 恢复的正确性，利用已有服务资源完成恢复。下一节给出支撑方法选择的分析，以及相应的放置与恢复机制。
