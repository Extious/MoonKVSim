---
title: AegisKV｜面向多 Agent 工作流的 KV 缓存容错
---

*Workflow-aware KV Recovery with Complete DRAM Checkpoints and Selective HBM Replication*

中文研究论文式介绍 · 基于项目当前论文稿整理 · 2026-10-02

NOTION_CALLOUT

# 摘要

多 Agent 应用通过反复的模型调用积累上下文及其 KV 缓存。执行节点发生故障后，若没有可用副本，接管节点必须重新处理已接受的历史输入，长上下文的重建代价可能显著延长工作流完成时间。然而，不同 Agent 的恢复延迟对工作流的影响并不相同，完整 KV 也不必全部放入最昂贵的 GPU 内存。AegisKV 将这一问题分成两个层次：依据恢复代价与工作流 Slack，为重要 Agent 在独立故障域的 Peer DRAM 中保留完整检查点；在此基础上，仅将前 L 层各自的 Top-K KV 块额外放入 Peer HBM，并随前台显存压力调整配额。Tracker、Router、KV Master 和 Adapter 协同完成优先级估计、故障接管、状态选择与容量控制。

当前论文的在线回放在 24,576-token 场景中，将故障调用的 retry latency 从 3,960.7 ms 降至 2,375.3 ms，减少 1,585.4 ms（约 40.0%）。但 HBM 相比完整 DRAM 检查点的额外收益至多为 0.217 ms。该结果说明，本组配置的主要收益来自避免长历史重建，而不是大量 HBM 命中。本文据此介绍设计机制、现有证据及其适用边界，不将回放中的无故障零差异解释为实机零开销。

**关键词：** 多 Agent 工作流；KV cache；故障恢复；检查点；稀疏注意力；工作流完成时间

NOTION_TOC

---

# 1　引言

在多 Agent 服务中，一次用户任务通常由多个具有依赖关系的 Agent 协同完成。同一 Agent 可以被连续调用多次，后续调用在先前历史上增加输入与输出；已有 KV 因而既是加速重复调用的缓存，也是故障后避免重复计算的重要状态。PagedAttention、SGLang 和 CachedAttention 分别从显存管理、结构化执行和多轮复用角度降低正常服务成本 [1–3]，但 worker 故障会使它持有的 KV 状态同时失效。

直接保存所有 Agent 的完整 GPU 副本代价很高。项目的长上下文微基准使用 Qwen2.5-7B-Instruct-1M、两张 A100 PCIe 40 GB、TP=2 和 BF16：在约一百万 token 时，完整重建需要 571.2 s，历史 KV 跨两 rank 占用 57.9 GB。复用同一历史状态并处理一个新 token 时，HBM、主机 DRAM 和共享存储路径分别约需 1.3 s、2.7 s 和 10.2 s。这些是恢复路径微基准，**不是 AegisKV 端到端部署性能**；共享存储也不是当前 AegisKV 设计中的第三层。

AegisKV 的核心问题不是“如何备份最多的 KV”，而是“如何用有限的故障安全容量减少暴露到工作流上的恢复延迟”。本文围绕三个相互衔接的设计展开：工作流感知的 Agent 保护、完整恢复覆盖与快速副本的分离，以及服从前台资源约束的 HBM 配额适配。

# 2　背景与设计动机

## 2.1　调用 DAG、Agent 历史与故障域

图 1 展示 invocation 如何映射到模型 worker。节点代表一次调用，而不是一个只执行一次的 Agent；同一字母的不同序号表示同一 Agent 的连续调用。前驱完成后，runtime 才提交依赖它的调用。Worker 可以是单 GPU 模型副本，也可以是多个 tensor-parallel rank 组成的模型副本。各 rank 对同一历史 token 保存不同 KV 分片，复用必须同时匹配 token 前缀、模型版本、并行配置、精度和布局。

NOTION_FIG_SERVING

本文考虑使 worker 不可用的 fail-stop 故障，并假设 workflow DAG、已接受 token 等恢复输入仍在故障域之外存活。Peer 必须位于被保护故障域之外：本机 DRAM 可能抵御进程故障，却不能保护同一主机整体失效。恢复所依赖的完整检查点必须包含所有层、TP 分片和必要的注意力元数据；缺少其中一部分的 HBM 副本只能加速恢复，不能独立提供完整覆盖 [4, 5]。

## 2.2　O1：相近的重建代价，不等于相近的工作流损失

对于单独受到延迟的分支，工作流完成时间 WCT 的增量可写为：

$$
\Delta W_i=\max(0,R_i-\sigma_i)
$$

其中 Rᵢ 是额外恢复延迟，σᵢ 是该分支在 join 前的 Slack。图 2 的 A1 有 91.2 s 的时间余量，33.2 s 的重建不会推迟 join；A2 的重建代价相近，为 32.6 s，却因位于关键路径而全部暴露为工作流延迟。因此，按 KV 大小或重建时长排序，并不等于按工作流收益排序。

NOTION_FIG_AGENT

图 2 的时间线来自 trace，join 关系采用图示假设；重建代价是三次测量的中位数及范围，WCT 增量则是在其他执行保持不变时的条件计算。一次 worker 故障还可能影响多个 Agent，因此单分支关系不能被简单相加为任意共同故障下的全局收益保证。

## 2.3　O2：完整恢复覆盖与快速恢复，是两个不同目标

图 3 表明，原生稀疏注意力的历史访问存在集中性：NOSA-8B、NSA-8B 和 MiniCPM4.1-8B 中，最热的约 20% 历史块分别承载 87.64%、74.76% 和 56.54% 的访问。与此同时，层序恢复允许前面层的计算隐藏后面层的传输。一个块即使经常访问，只要它的搬运完全被计算隐藏，提前把它放入 HBM 也未必缩短恢复。

NOTION_FIG_KV

因此，DRAM 的任务是保留**完整检查点**，HBM 的任务是减少**暴露的传输等待**。图 3 的热点排序是回顾性的频率统计，不是对未来查询命中的保证；实际部署的 Top-K 效果需要另行评估。

## 2.4　O3：快副本的容量必须随前台负载变化

执行中的请求、增长的上下文和临时 workspace 持续改变可用 HBM。固定的大副本配额可能挤占正常服务容量；固定的小配额又可能浪费空闲显存。AegisKV 因而让 Adapter 管理总配额，而由 KV Master 决定哪些 Agent 获得这个配额，避免把“副本是否有价值”和“当前能容纳多少副本”混为一个问题。

---

# 3　系统架构

图 4 按 Application、Controller 与 Engine 三层组织 AegisKV。Runtime 提供调用和依赖，Controller 维护保护决策，Engine 执行推理与 KV 传输。示例中的两个 DP worker 分别位于不同主机，每个 worker 使用 TP=2；Peer DRAM 属于所选 peer 的主机，不是一个独立的全局内存池。

NOTION_FIG_OVERVIEW

| 组件 | 核心职责 | 交付给下游的信息或动作 |
| --- | --- | --- |
| Tracker | 估计 Agent 剩余工作，计算 guarded Slack | 剩余任务 DAG、Slack 与估计有效性 |
| Router | 选择执行 worker 与域外 retry target | 放置位置、接管路由与容量缺口 |
| KV Master | 选择 Agent、维护检查点与 Top-K 副本 | 已提交 manifest、复制与回收决策 |
| Adapter | 根据前台压力调整每 rank 的 HBM 预算 | 安全容量上限与动态配额 |

Rank-local Connector 是传输执行器：执行 Master 的复制指令，报告完成或失败，不独立决定保护策略。故障后，Router 使旧执行失效并把调用发送到 retry target；目标使用已提交的 DRAM 检查点和 HBM 热块恢复。若接管者成为新的执行节点，后续保护需要重新选择独立 peer。

# 4　关键机制

## 4.1　Tracker：从剩余工作估计到保守 Slack

Tracker 以 (workflow, Agent, invocation ordinal) 标识一次调用。预测只在 invocation 提交时触发，输入来自当时已知的任务描述、新输入、已接受输出与历史调用长度/耗时，目标是“从本次提交到该 Agent 完成任务的剩余时间”。同一调用内部不依赖未来输出或最终调用次数更新预测，也不预先指定某一种回归器已经具有足够精度。

对尚未完成的 Agent-task DAG，Tracker 通过关键路径的前向、后向遍历计算最早和最晚完成时间 EF、LF，并扣除校准后的 Slack 高估裕量 g：

$$
s_a=\max\{0,LF_a-EF_a-g_a\}
$$

同一 Agent 的多次 invocation 继承同一个 Agent Slack，避免重复累计其剩余工作。任何必要的预测缺失、失效或过期时，采用零正 Slack 的保守回退。预测与调度异步进行，不要求 token 生成等待控制器完成估计。

## 4.2　KV Master：先决定保护谁，再决定加速哪些块

**Agent 选择。** 令 Tₐ 为从历史长度及离线 Prefill profile 估计的完整重建延迟。Master 计算 Slack 无法隐藏的部分：

$$
E_a=[T_a-s_a]^+,\qquad E_a>\lambda\ \Rightarrow\ \text{eligible for protection}
$$

λ 表示保护阈值。在 DRAM 有限时，Master 按 Eₐ 从大到小接纳完整检查点，并在 invocation 边界或 Slack 更新时重新判断。图 5(a) 取 λ=17 s，A2 与 A4 获得 DRAM 保护。这个阈值是决策规则；容量不足、预测误差和同源多 Agent 故障仍需单独核算，不能据此宣称任意故障的全局 WCT 增量都不超过 λ。

**检查点。** 当前粒度为 Z=256 token，即四个 64-token 块。Connector 增量复制所有层和 TP 分片，只有相应分片全部到达后，Master 才发布新的连续 checkpoint frontier。正常复制及时完成时只需重建短尾部；更一般地，实际重建量由“已接受 token 数 − 已提交 frontier”决定。异步复制落后时，这一尾部可能超过 Z，不能把检查点粒度当作复制滞后的硬上限。

NOTION_FIG_SELECTION

**块选择。** 每层维护原生 attention 选择计数：同一 query 在任一 head 选中某块，即对该块计一次。每 token 只累加已有选择索引对应的计数；Top-K 集合在检查点边界更新，而非逐 token 重新排序。更新包括衰减 β、新 chunk 块的加入，以及 1+ε 的替换迟滞。新进入的热块由 peer 在本地从 DRAM 复制到 HBM；离开的热块等在途读取结束后再释放。因此，已发布的 HBM 热块始终具有完整 DRAM 底本。

## 4.3　层序恢复：把传输隐藏在尾部重建之后

图 6 比较三种恢复组织方式。先搬完全部 DRAM KV 再计算，会暴露全部传输延迟；按层先传 Top-K，可以将后续层搬运与前面层的重建重叠；若前 L 层的 Top-K 已在 HBM 中，则可以进一步消除启动等待和部分累积等待。稀疏 attention 仍按原生逻辑选择块：命中直接使用 GPU 状态，miss 在该层选择结果已知后从 DRAM 优先召回，不能提前使用未来 miss 信息。

NOTION_FIG_PIPELINE

机制设计允许命中块计算与 miss 传输并行，并通过 log-sum-exp 合并 attention 部分结果。这里的流水线图是构造性的解释图；它说明等待如何暴露或被隐藏，不代表真实 kernel 已实现这些重叠，也不证明某个模型能够达到图示加速。

在同质层的简化模型中，N 是层数，B 是单次恢复实际获得的 H2D 带宽，B* 是一层 Top-K 与 miss 数据恰好能在一层重建时间内载入的带宽。由层序到达条件得到深度估计：

$$
L=\max\left\{1,\left\lceil N-(N-1)\frac{B}{B^*}\right\rceil\right\}
$$

图 7 显示：B 不低于 B* 时，预置首层即可覆盖启动等待；带宽降低时，需要更深的 HBM 前缀。部署时应根据预期并发恢复下的有效带宽校准 L，而不是直接采用链路标称峰值。非均匀层、动态 miss 和真实带宽争用仍需用实际调度验证。

NOTION_FIG_DEPTH

## 4.4　HBM 准入与 Adapter：仅为额外收益付出显存

完整 DRAM 检查点已经提供恢复覆盖，HBM 只值得为其增量加速占用显存。设 Tᴰₐ 与 Tᴴₐ 分别为 DRAM-only 和带 HBM 副本时的恢复延迟，Master 使用：

$$
G_a=[T_a^D-s_a]^+-[T_a^H-s_a]^+
$$

在同模型、固定 K/L、单副本等尺寸的配置内，Master 按 Gₐ 降序准入，跳过 Gₐ=0 的 Agent。无法容纳者仍保留 DRAM 检查点，并向 Adapter 提供扩容需求。该等尺寸排序结论不直接外推到任意跨模型大小、资源争用或共同故障下的全局最优。

Adapter 以每 rank 的物理容量为边界，先扣除权重、前台高水位、执行预留和 workspace 余量，再受管理员上限约束。出现分配卡顿、预留受侵占或显存准入等待时，采用乘性减小；连续稳定窗口后若仍有有价值但未接纳的需求，则加性增加。K 与 L 保持部署配置不变，配额只改变可驻留的 Agent 数量。

缩容时按 Gₐ 从小到大释放 HBM 副本，并等待读取租约结束。由于 DRAM 底本完整，缩容不需要先回写这些热块；前台准入仍按照实际占用执行，而不是把尚未释放的预算提前当作可用内存。

---

# 5　现有评估与结果解读

## 5.1　实验设置与证据层次

本节对应当前英文稿 `evaluation.tex` 中的在线到达回放。每个节点配置为两张 A100-PCIe-40GB、一个 TP=2 worker，peer 位于第二个同类型节点；H2D 采用分区上记录的 pinned 传输速率 23.98 GB/s。回放使用三个模型在三个 PG19 文档上的原生 sparse-forward 选择记录，Prefill 与 Decode 分别按 100 μs/token、2 ms/token 计费。每组八个 workflow 在线到达，每个 workflow 只有一个 Agent；它不是复杂多 Agent DAG 的实机端到端故障实验。

对比对象为不保存检查点的 **Restart**、保留完整 Peer DRAM 检查点的 **DRAM-only**，以及额外配置前 L=4 层、每层 K=16 个热块的 **AegisKV**。HBM 配额初始为 16 MiB。故障作用于 wf04 在调用进度 65% 时所在的 worker，后者在剩余运行中不再恢复。图 8 分别展示 workflow 完成时间和目标调用的 retry latency；两者是不同指标，不能混用。

NOTION_FIG_EVAL

## 5.2　主要收益来自避免已检查点历史的重建

24,576-token 场景中，wf04 的 WCT 在无故障、AegisKV 和 Restart 下分别为 2,585.6、4,102.9 和 5,688.3 ms。AegisKV 相比 Restart 减少 1,585.4 ms；wf04 到 wf07 保留相同差值，因为失效 worker 没有恢复，后续队列在相同容量损失下继续演进。

对故障调用的恢复分解显示，两者准入前排队均为 1,500.1 ms，但服务部分由 2,459.6 ms 降至 874.2 ms。检查点覆盖已产生的 16,016 token 中的 15,872 个，AegisKV 只需重建剩余 144 token；Restart 则重建全部历史。不同 prompt 长度下的 retry latency 如表 1 所示。

**表 1　同一故障位置下的 retry latency（ms），NOSA-8B / PG19 文档 10146。**

| Prompt 长度（token） | Restart | AegisKV | 减少 |
| --- | --- | --- | --- |
| 2,048 | 468.9 | 340.9 | 128.0 |
| 8,192 | 1,421.1 | 909.2 | 511.9 |
| 16,384 | 2,690.9 | 1,642.1 | 1,048.8 |
| 24,576 | 3,960.7 | 2,375.3 | 1,585.4 |

随着检查点覆盖的前缀增长，避免的 Prefill 工作增加，绝对节省从 128.0 ms 增至 1,585.4 ms。但队列和其他服务代价仍然存在，不能用“重建 token 数减少比例”直接代替端到端加速比例。

## 5.3　HBM 的增量收益与有限的 Top-K 覆盖

该组回放中，DRAM-only 与 AegisKV 的每个配对 workflow 相差不超过 0.217 ms；图 8(a) 因而只绘制一条近乎重合的保护策略曲线。这不是需要隐藏的结果，而是一个关键判断：**在当前带宽、层序重叠和热集大小下，完整 DRAM 检查点已经提供了几乎全部收益。**

图 9 给出原生访问记录上的 Top-K 诊断。K=16、前四层时，当前 selector 对 NOSA、NSA、MiniCPM 的 distinct future-query blocks 覆盖分别为 8.31%、4.20%、4.06%；Recency 在前两个模型上相当，在 MiniCPM 上达到 4.13%。图中的点等权平均三个文档，须线表示文档范围，而不是独立故障运行的置信区间。

NOTION_FIG_NATIVE

图 3 与图 9 衡量不同对象：前者统计回顾性热点承载的访问频率，后者考察给定小容量下对未来不同块的覆盖。不能从“20% 块承载大部分访问”推出“固定 K=16 一定有高命中率”，也不能把访问覆盖率直接解释为 HBM 对 WCT 的收益。

## 5.4　适用边界与尚需检验的问题

当前无故障矩阵中三种策略的完成时间差为 0 ns，但这是既定计费与资源模型下的结果，不等价于真实 GPU counter、DMA、CPU 决策或 kernel 同步开销为零。项目当前实现说明把相关 runtime 定位为元数据离散事件模型：它不执行数值 attention 或真实 log-sum-exp 合并，也不具备生产 serving 的连续批处理。

八个单 Agent workflow 的回放能解释检查点如何减少重试历史，却不能独立验证复杂 DAG 下的 Slack 选择收益、剩余时间回归精度，或 Adapter 在大规模动态负载下的收益。进一步的系统评估应在匹配的工作负载、故障位置和资源预算下，分别检验预测误差、HBM 增量收益、正常运行开销、同源多 Agent 故障，以及复制积压和 DRAM 压力导致的降级。这里保留既有结果的适用范围，不把历史模拟矩阵或机制示意图升级为当前系统的实机结论。

# 6　相关工作与定位

**KV 管理与多轮复用。** PagedAttention [1]、SGLang [2] 与 CachedAttention [3] 提供了理解缓存组织和前缀复用的重要背景。AegisKV 关注的额外问题是：在失去执行节点 KV 时，哪些可恢复历史最值得占用故障安全容量。

**LLM 容错。** DéjàVu [4] 与 LUMEN [5] 提供 KV streaming、检查点和协调恢复的直接背景。AegisKV 的设计重点是以工作流 Slack 区分 Agent 的保护紧迫性，并分开决定完整 DRAM 覆盖与选择性 HBM 加速；本文没有据此宣称优于这些系统的实测结果。

**工作流语义与稀疏注意力。** Parrot [6] 展示跨调用语义对应用服务的重要性；NOSA [7] 和 MiniCPM4.1 [8] 为非均匀原生 KV 需求提供模型背景。AegisKV 尝试利用这些需求减少暴露的恢复传输，而不改变原生稀疏选择语义。

# 7　结论

AegisKV 将 Agent KV 容错拆解为“保护哪些历史”“哪些状态值得提前进入 GPU”以及“当前可以占用多少 HBM”三个问题。完整 Peer DRAM 检查点提供覆盖，前 L 层 Top-K 热块提供可选的加速，guarded Slack 与 Adapter 则分别连接工作流目标和前台资源约束。现有回放清楚展示了长历史检查点的价值，同时也显示当前配置下 HBM 的额外收益很小。后续设计选择应据此优化真正暴露的恢复瓶颈，而不是追求最大备份量或单独的命中率数字。

---

# 参考文献

[1] Kwon et al. **Efficient Memory Management for Large Language Model Serving with PagedAttention.** SOSP 2023. [DOI](https://doi.org/10.1145/3600006.3613165)

[2] Zheng et al. **SGLang: Efficient Execution of Structured Language Model Programs.** NeurIPS 2024. [论文](https://proceedings.neurips.cc/paper_files/paper/2024/hash/724be4472168f31ba1c9ac630f15dec8-Abstract-Conference.html)

[3] Gao et al. **Cost-Efficient Large Language Model Serving for Multi-turn Conversations with CachedAttention.** USENIX ATC 2024. [论文](https://www.usenix.org/conference/atc24/presentation/gao-bin-cost)

[4] Strati et al. **DéjàVu: KV-cache Streaming for Fast, Fault-tolerant Generative LLM Serving.** ICML 2024. [论文](https://proceedings.mlr.press/v235/strati24a.html)

[5] Cao et al. **LUMEN: Coordinated Failure Recovery for Distributed LLM Serving.** 2026. [预印本](https://arxiv.org/abs/2606.17787)

[6] Lin et al. **Parrot: Efficient Serving of LLM-based Applications with Semantic Variable.** OSDI 2024. [论文](https://www.usenix.org/conference/osdi24/presentation/lin-chaofan)

[7] Huang et al. **NOSA: Native and Offloadable Sparse Attention.** 2026, v2. [预印本](https://arxiv.org/abs/2510.13602v2)

[8] OpenBMB. **MiniCPM4.1-8B Model Card and Release History.** [模型资料](https://huggingface.co/openbmb/MiniCPM4.1-8B)

# 附录　原稿与来源

NOTION_ATTACHMENTS

本文为中文整理稿，而非对本地英文源文件的覆盖修改。机制以当前 `system_design.tex` 为准；数字对应 `motivation.tex` 与 `evaluation.tex`；实施边界另对照 `docs/current-design-simulation.md`。图像直接由当前论文的矢量 PDF 高分辨率导出，未重拟合、重画或更改数据。原有的 [AegisKV 研究笔记](https://app.notion.com/p/3d89726872d98070ba70ce1bd7da4e38) 保持不变。

NOTION_PROVENANCE
