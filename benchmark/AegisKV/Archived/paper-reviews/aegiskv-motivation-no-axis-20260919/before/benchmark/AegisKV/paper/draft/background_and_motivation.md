## 2 Background and Motivation

多智能体应用通过相互依赖的 LLM 请求完成一个用户任务。执行节点故障会同时损失服务能力与 KV 状态，推迟受影响请求及其后继。备份 KV 能减少重建工作，却也占用正常请求所需的内存与带宽。因此，本节关注如何在有限资源下分配保护，以减少工作流完成时间（WCT），以及更快的 GPU 驻留保护何时值得付出额外资源。

<table class="motivation-figures">
<tr>
<td width="33%" align="center" valign="top"><a href="../figures/motivation-row/motivation-branch-gap.pdf"><img src="../figures/motivation-row/motivation-branch-gap.png" width="100%" alt="图 1(a)：并行分支持续时间差的经验累积分布"></a></td>
<td width="33%" align="center" valign="top"><a href="../figures/motivation-row/motivation-workflow.drawio.pdf"><img src="../figures/motivation-row/motivation-workflow.drawio.png" width="100%" alt="图 1(b)：从左到右的 A0、四个并行分支、A5；A0 与 A5 表示 Main 的前后阶段，框内标注分支名称与耗时，A0、A2、A5 标红"></a></td>
<td width="33%" align="center" valign="top"><a href="../figures/motivation-row/motivation-recovery-exposure.pdf"><img src="../figures/motivation-row/motivation-recovery-exposure.png" width="100%" alt="图 1(c)：同一工作流四个分支的重算时间与 WCT 损失"></a></td>
</tr>
<tr>
<td align="center">(a) 工作流内最大耗时差</td>
<td align="center">(b) 四分支 Workflow 实例</td>
<td align="center">(c) 恢复延迟暴露估计</td>
</tr>
</table>

**图 1：工作流时序与恢复延迟暴露示例。** (a) 每个工作流内最大分支持续时间差的 ECDF（121 个工作流，fan-in 由时序推断），并非 Slack 分布。(b) 选取的四分支轨迹实例，时长差为 91.2 s，不是 (a) 中的最大差值样本。A0、A5 分别表示 Main 在并行分支前后的阶段。分支条形保留相对首个分支启动的真实时序；虚线假设全部分支均为 A2 在 151.6 s 完成时的汇合所必需。(c) 扇出后 29.5 s 的独立分支故障反事实，斜纹表示吸收的延迟，实色表示 WCT 损失。重建代价以块计数输入代理值查询 Qwen3-14B/A100 BF16 静态模型，包含假设的 64-token 尾部（batch/TP 均为 1）。

### 2.1 工作流、故障与 KV 恢复

**多智能体工作流。** 我们将一个工作流表示为有向无环图 $G=(V,E)$：节点是 LLM 请求，边表示请求之间的数据依赖。一个 agent 分支可以包含多轮请求和工具调用，后继节点在其依赖满足后才能执行。工作流完成时间（workflow completion time，WCT）从首个请求释放计至最后一个请求完成。对于给定的执行计划，请求的 Slack 是在不推迟工作流完成的前提下，其完成时间能够延后的最大幅度；关键路径上的请求没有这种余量。

**服务与故障模型。** 我们考虑按块管理 KV 的 worker，每个 worker 是一个完整模型副本，也可以由一个张量并行（TP）组承载。GPU 或 worker 的 fail-stop 故障使该 worker 不可用，由已加载兼容权重的存活 worker 接管请求。控制面、token 历史、承载备份的 DRAM 和接管 worker 必须存活。本文研究这一前提下的 KV 恢复，不涵盖整机故障、网络分区、静默数据损坏或丢失的模型服务能力如何恢复。

**恢复途径与资源代价。** 没有可用副本时，系统需重新执行 prefill 来重建丢失的 KV。DRAM 副本可以避免重建已保存的前缀，但使用前仍需将状态传入 GPU，多个恢复请求会共享传输带宽。若副本预先驻留在实际接管 GPU 的 HBM 中，则可直接供该 GPU 使用；代价是占用原本可用于前台请求的 HBM，并产生故障前的复制流量。因此，备份介质的容量、恢复速度与正常服务开销之间存在权衡。

**与现有系统的关系。** [DéjàVu](https://proceedings.mlr.press/v235/strati24a.html) 将 KV 副本流式传入远端 CPU 内存以恢复流水线执行，消耗主机存储和传输带宽。[GhostServe](https://proceedings.mlsys.org/paper_files/paper/2026/file/d99e8e80a6c41e148db686918dd7eab3-Paper-Conference.pdf) 在主机内存存储纠删编码校验片，用编码与重建工作换取更少的检查点字节，并将部分重算与恢复 I/O 重叠；其内存丢失恢复实验维持静态并行拓扑，硬设备故障还需恢复或重建该拓扑。[LUMEN](https://arxiv.org/html/2606.17787v1) 已根据负载协调主机内存检查点放置和重试路由，并在模型重新加载期间提供草稿模型辅助，代价包括检查点流量、预留主机内存和临时草稿状态。[Mooncake](https://www.usenix.org/conference/fast25/presentation/qin) 汇聚 DRAM/SSD KV 存储，在请求延迟 SLO 约束下调度复用以提高吞吐。

工作流感知的缓存分配也已有研究：[KVFlow](https://arxiv.org/html/2507.07400v1) 利用后续 agent 执行步数决定前缀驱逐和重叠预取；[TOPAS 预印本](https://arxiv.org/html/2608.25523v1) 在共享 KV 预算下联合选择前缀驻留和请求准入，利用剩余工作流路径优化任务完成时间。[NOSA/NOSI](https://arxiv.org/html/2510.13602v2) 限制稀疏注意力传输量，并在解码时调入选中但未驻留的块。这些机制面向前缀复用或卸载推理。AegisKV 的具体问题是：依据活跃 KV 丢失后对 WCT 的边际影响，分配 DRAM 备份和额外 HBM 副本，同时保持模型的注意力选择不变。因此，工作流感知、稀疏加载或传算重叠本身均不足以构成新颖性。

### 2.2 请求恢复代价与工作流损失不同

并行分支的汇合决定了依赖这些分支的后继何时能继续：较早完成的分支可以容忍一定延迟，而决定汇合时刻的分支一旦延迟就会推迟后继执行。为刻画这类时间差异，我们分析公开的 [CC/Weka 编码 agent 轨迹](https://huggingface.co/datasets/semianalysisai/cc-traces-weka-062126)。上游发布版要求每会话至少 20 次 Anthropic 请求、峰值并发 subagent 组不超过 10，排除被标记存在动态 agent 标签缺陷的会话，并删除超过输入长度上限的请求；我们的覆盖范围以这一预筛选语料为条件。我们从其中的 393 条会话提取严格重叠的子 agent 组，即最晚启动的分支早于最早结束的分支，再保留所有分支均已完成、且最后一个分支结束后仍有 Main 请求的组。Main 在分支执行期间可以继续发出请求。轨迹未记录显式结果依赖，因此 fan-in 是时序推断，不能验证 Main 是否消费了全部分支输出。

这一筛选从 292 个重叠组中保留 121 个工作流的 286 个组。对每个保留组计算最长与最短分支的持续时间之差，再对每个工作流取最大值。图 1(a) 的中位数为 138 s，P90 为 1,173 s，说明工作流内最大分支持续时间差存在明显异质性，并不表示请求或故障时刻的 Slack 总体分布。未进入这 121 个工作流的会话不能据此归为串行执行。

图 1(b) 选取一个时长差为 91.2 s 的四分支实例。条形保留真实起止时刻，将分支内的请求与工具调用聚合为一条区间。我们从分支数为 4–5、时长差距 100 s 不超过 15 s 的合格候选中选取关键分支前缀最长的组，使恢复延迟暴露更易辨认；该组不是所属工作流的最大差值组。A2 在扇出后 151.6 s 最晚完成，Main 在 157.4 s 发出请求。在 Main 依赖全部四个分支的明确假设下，各分支到 A2 完成的时间余量构成其汇合 Slack；轨迹提供时间，依赖边来自假设。

图 1(c) 在扇出后 29.5 s、四个分支均有活跃 LLM 请求时构造四个独立的单分支故障反事实。我们采用这四个请求记录的输入字段，不取最终输出或分支总量。输入长度代理值为 100,864–113,664，等于 64-token 哈希块数乘以 64，并非真实 tokenizer 计数，在重缓存场景下可能高估。我们加上假设的已知 64-token 尾部，用 AIConfigurator 的 Qwen3-14B、A100-SXM、BF16、batch 1、TP 1 配置估计重建时间 $T_i$。汇合 Slack $\sigma_i$ 由轨迹完成时刻离线计算；其他执行与排队不变时，WCT 损失为 $\max(0,T_i-\sigma_i)$。这项分析组合了轨迹时序、依赖假设与替换的静态模型代价，并非原服务模型上的故障重放或总体收益估计。

A1–A4 的重建代价分别为 35.2、32.2、36.7、38.9 s，暴露给 WCT 的损失却分别为 0、32.2、17.6、17.0 s。A1 的 91.2 s Slack 完全吸收其重建代价；A2 的重建代价最低，却因 Slack 为零产生最大的 WCT 损失。因此，仅按避免的计算量排序可能错误分配保护。该实例支持以 WCT 为目标，并未验证在线 Slack 估计的准确度。

### 2.3 长上下文与备份层级的恢复代价

Agent 的多轮交互将代码、工具输出和其他 agent 的中间结果不断加入上下文。保存历史状态可以避免故障后的重复计算，但副本所在的存储层级仍会影响恢复延迟。图 2 比较三个起点状态：完整历史 KV 及必要辅助状态已在接管 GPU 组的 HBM 中、相同状态仅在本机 DRAM 中，以及没有可用副本。三条路径统一以已知 64-token 尾部前向结束、历史与尾部状态重建完成为终点，模型权重均已加载。因此 HBM reuse 仍包含尾部计算代价。

比较采用 [NVIDIA AIConfigurator](https://github.com/ai-dynamo/aiconfigurator) 0.9.0 HYBRID 静态估计，覆盖 Qwen3-14B 与 Llama-3.1-70B 两种稠密模型、Qwen3-235B-A22B-Instruct-2507（235B 总参数、22B 激活参数）的 MoE，以及 DeepSeek-V3.2（671B 总参数、37B 激活参数）的 MoE＋DSA 稀疏注意力。Qwen 采用稠密分组查询注意力（GQA）成本模型，DSA 包含历史 token 索引器。统一采用 H100-SXM 80 GiB、vLLM 0.19.0、BF16 权重与 KV、batch 1，四个模型的 TP 分别为 1、4、16、32；两个 MoE 的 EP 分别为 16、32，PP 均为 1。各模型的 GPU 数量不同，比较对象是同一模型配置下的三种恢复路径。

横轴为总上下文 $C=M+64$，其中 $M$ 为已保存历史，64 为已知尾部。各曲线延伸到对应上限：[Qwen3-14B](https://huggingface.co/Qwen/Qwen3-14B) 使用 YaRN 到 131,072 tokens，[Llama-3.1-70B](https://huggingface.co/meta-llama/Llama-3.1-70B-Instruct) 到 131,072，[DeepSeek-V3.2](https://huggingface.co/deepseek-ai/DeepSeek-V3.2/blob/main/config.json) 到官方配置的 163,840，[Qwen 2507](https://huggingface.co/Qwen/Qwen3-235B-A22B-Instruct-2507) 到官方扩展配置的 1,010,000。Qwen 2507 原生支持 256K；超过该范围只投影全注意力成本，不含 DCA 位置处理或稀疏内核加速。DSA 算子表覆盖到 32K，更长形状采用表外推算，含历史前缀的查询还使用解析前缀修正。空心标记标出这两类外推区间，实心标记同样是静态估计。

HBM reuse 仅计算新增 64 tokens。Recompute 从空缓存开始，以至多 8,192 tokens 的连续块逐块重建，后续块复用先前重建的 KV；所有路径均排除不参与 KV 重建的词表投影。分块控制建模的激活内存，分块调度的软件开销不计。DRAM reuse 先恢复每个 rank 所需的完整历史状态，再执行相同尾部。GQA 传输量计入 KV 分片和必要的头复制；DSA 计入每个 rank 上复制的 MLA 压缩状态、RoPE key，以及在其余 BF16 配置下保留原生 FP8 的索引器 key 和 FP32 scale。所有 rank 假设同时以各自 64 GB/s 恢复，主机不形成共享瓶颈，传输与计算不重叠。带宽是系统模型假设，未经测量。

在 128K 总上下文下，四个模型的 HBM reuse 估计为 22–56 ms，DRAM reuse 为 155–357 ms，分块 Recompute 为 14.5–21.0 s。Qwen 2507 的全注意力成本投影在 1,010,000 tokens 时为 70 ms、830 ms 和 220 s。以 Qwen3-14B 的 128K 点为例，DRAM 副本避免了绝大部分历史重算，而完整 HBM 驻留在此串行传输模型下进一步减少约 335 ms 的等待。这一区别表明，备份首先避免历史计算，HBM 相对 DRAM 的增量价值则来自减少传输等待；参数量、状态格式与并行配置共同影响绝对代价。

<figure class="paper-figure">

[<img src="../figures/motivation-row/motivation-recompute.png" width="480" alt="图 2：四模型三路径恢复估计，各曲线延伸到其对应的上下文上限，Qwen 2507 超过 256K 为全注意力成本外推">](../figures/motivation-row/motivation-recompute.pdf)

**图 2：同一模型内的静态恢复估计。** 颜色／线型区分路径，标记形状区分模型。Qwen14B、Llama70B、Qwen235B（2507）、DeepSeek-V3.2 使用 1/4/16/32 张 H100，终点为 128K（YaRN）/128K/1,010,000/160K。BF16、batch 1，总上下文包含相同的 64-token 尾部。HBM 保存完整历史；DRAM 按每 GPU 64 GB/s 恢复完整状态后再计算；Recompute 使用 8K 分块。空心标记表示 Qwen 超过 256K 的全注意力投影，以及 DSA 超过 32K 的算子表外推。K = 1,024，M = $10^6$。

</figure>

25 个配置均通过 batch 1 下逐 TP rank 的静态显存检查，最大为每 GPU 77.8 GiB；这不代表多个备份或恢复并发时的容量可行性，也未验证实机部署、长上下文精度或原生稀疏恢复正确性。完整历史 HBM 驻留是一项理想复用参照；AegisKV 的有限热块预算通常仍将部分必需状态留在 DRAM。串行完整状态 DRAM 路径同样是代价参照，并非优化后的 DRAM 基线。该图隔离同一模型内的路径代价，不含检测、排队、软件接管和带宽竞争。

### 2.4 问题定义与设计目标

<!-- 当前为用户授权的 AIConfigurator 暂定估计版。原生稀疏模型的同条件物理测量仍未补齐；协议和估计口径见 ../../experiments/plans/reuse-latency-insight.md。 -->

AegisKV 要解决的问题是：在备份容量和复制、恢复带宽有限的条件下，哪些请求的哪些 KV 应获得何种保护，才能减少故障对工作流完成时间的影响？图 2 支持保存 KV，同时说明 DRAM-only 必须是关键基线：它无需预留备份 HBM 就能避免绝大部分重算。只有 HBM 增量减少的恢复等待暴露给工作流时，才能改善 WCT。对 Slack 为 $\sigma$ 的孤立请求，若 DRAM 和 HBM 的恢复延迟分别为 $D\ge H$，则节省的 WCT 为 $\max(0,D-\sigma)-\max(0,H-\sigma)$，至多为 $D-H$；当 $\sigma\ge D$ 时为零。因此，较大的分支持续时间差本身不能证明占用 HBM 合理，避免数秒 prefill 也不能证明相对 DRAM 的亚秒级收益值得其代价。

收益成立的条件应包括：请求剩余 Slack 较小、传输等待无法由必要计算隐藏，以及存在不会损害前台服务的可用 HBM。只有多个恢复共享受限主机或链路时，并发恢复才可能放大这类等待；图 2 未建模该效应。确定收支平衡点，需要将有限 HBM 保护与强 DRAM-only 基线配对比较：基线支持按层优先传输、模型允许的按需加载及传算重叠，两者使用相同恢复内核重建相同必需状态。测试须扫描负载、共享带宽、每 rank 备份容量和故障频率，统计受影响及未受影响工作流；传输和重算均不能默认拥有无争用资源。按故障频率加权的恢复收益需要抵偿复制和挤占前台 KV 带来的正常服务损失；若不能，系统应保留 DRAM 保护并释放额外 HBM。这些是需要验证的条件，并非当前静态曲线已证明的收益。

这一问题要求系统满足五项目标与约束：**(R1)** 以 WCT 衡量恢复效果，考虑请求依赖带来的延迟容忍度；**(R2)** 在请求及其 KV 之间分配有限备份容量，使保护减少实际暴露的恢复等待；**(R3)** 支持并发恢复及传输与计算重叠，避免保护策略引入额外的请求级串行等待；**(R4)** 控制正常运行时的复制开销，使备份容量与带宽占用服从前台服务的资源需要；**(R5)** 保持模型计算与 KV 恢复的正确性，利用已有服务资源完成恢复。下一节给出相应的放置与恢复设计。
