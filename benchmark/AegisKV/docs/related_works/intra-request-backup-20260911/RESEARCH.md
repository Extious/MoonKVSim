**同一请求内，能否用少量 KV 备份获得大部分恢复收益？**

论文选题调研与可证伪的研究路线 · 2026-09-11

**场景已修正：**用户明确的是“少部分 KV 在 Peer HBM，其余在 DRAM”，两层共同保留完整状态。当前结论以 [Peer HBM + DRAM 修订分析](PEER_HBM_DRAM.md)为准。本篇对有限总备份、裁剪和重算的讨论保留为背景，不应直接作为该分层场景的主路径假设。

**核心判断**

可以找到“少量 KV 保留较多任务能力”的已有证据；目前还不能据此断言，在 AegisKV 的目标请求、故障位置和真实字节预算下，它们也能提供大部分备份收益。最有希望的主线是**质量约束下的请求内选择性备份**，同时把精确恢复作为独立路径和比较基准。请求级 Slack 排序视为已给定，本报告不讨论租金算法。

两个原始思路的判断不同。语义选择有较强的算法依据，但已有大量 KV 压缩工作，创新不能停留在“备份 attention 分数高的 KV”。位置选择的计算依据成立，却已经被 Cake（ICML 2025）和 CacheFlow（2026 年预印本）直接利用；而且在标准线性加二次重算模型中，备份末尾 10% 的完整 KV，最多省约 19% 的重算工作，不能单靠它推出“10% 备份免掉 80% 重算”。这个上限是本报告的条件化推导，不是实测时延结论。[^12][^13]

建议把论文问题写成：**对一个已由 Slack 选中的请求，在有限的备份容量和持续写入带宽下，什么状态表示与保护集合，能在给定正确性要求下最大程度缩短故障造成的服务中断？** “状态表示”必须纳入研究，因为少量高精度 KV 与全量低精度 KV 是直接竞争者；只研究 token 选择会遗漏很强的基线。[^15][^16][^17]

| 候选方向 | 文献支持的事实 | 与目标的距离 | 当前建议 |
|---|---|---|---|
| 语义重要 KV 子集 | 多种模型和任务允许删去部分 KV 并保持接近原模型的任务分数 | 尚需证明故障时切换、后续长输出、物理备份字节和持续维护成本 | 优先验证，允许近似恢复 |
| 后段完整 KV 块 | 相同长度的后段 chunk 通常有更多 attention 计算，已有重算/加载系统利用它 | 位置收益未必高度集中，且已有直接先行工作 | 精确恢复强基线或组成部分 |
| 全量低位宽 KV | 量化能够减少总状态字节，保留所有位置 | 有量化误差，需衡量长推理和恢复解码成本 | 与语义选择并列的必测方案 |
| 纠删码或幸存基础状态上的增量 | 依赖幸存数据，可用少量新增冗余恢复较多丢失状态 | 强依赖故障域，不能与“所有原始状态丢失”混为一谈 | 精确路径的条件性候选 |

**1. 先定义“重要”和“备份收益”**

设请求 r 在故障时已经处理到 token 游标 t，其完整运行状态包含 KV、token 历史、位置和采样等元数据。预算 B 指故障域外已经提交、可读取的备份物理字节。KV 数量必须注明是完整 token、token×layer×KV-head 的向量对，还是物理页；这几个口径不能互换。

本报告默认模型权重和可靠的 token 历史可用，恢复工作只覆盖已经发生的计算，不计入尚未生成的未来 token。若模型加载、进程重建、通信组重建占主要时间，KV 优化的收益会被这些成本限制。备份的可用性以提交完成为准；异步复制尚未完成的状态不能计入收益。

“重要”至少有三种含义：

1. **质量重要性**：失去这些 KV 后，后续任务成功率下降多少。
2. **重建重要性**：保存这些状态能够省掉哪些实际计算或通信依赖。
3. **时间重要性**：上述节省是否落在首次可用输出或工作流完成的关键路径上。

三者不等价。例如，一个检索头的少量 KV 可能决定答案正确性；但在精确恢复中，只备份这个头，并不一定能省掉同一 token 的其他头、FFN 和上层计算。相反，保存语义上普通的完整后段 token 状态，可能省掉该段多层前向计算。不能把 attention 分数直接解释为恢复毫秒数。

建议明确区分以下正确性合同：

| 合同 | 允许的变化 | 验证要求 |
|---|---|---|
| 精确状态恢复 | 不主动删除或量化原模型所需的信息 | 被复制/编码状态可做逐字节比较；重算路径还需声明浮点数值和 kernel 差异 |
| 原模型输出等价 | 允许内部执行顺序变化或经验证的推测执行 | 贪心输出一致或规定的采样分布等价；这不自动意味着相同随机种子逐 token 一致 |
| 相对既定稀疏模型的精确恢复 | 完整恢复该稀疏模型本来需要的状态 | 基线使用同一个模型、同一 mask 和同一索引规则 |
| 近似恢复 | 故障后用裁剪、量化或合成状态继续运行 | 任务质量、长输出稳定性、工具调用成功率等满足事先规定的容差 |

“某个 benchmark 分数不变”只支撑对应任务上的质量证据，不构成精确恢复证明。VeriCache 本文对 identical 的主要定义是贪心解码下输出相同，并保留硬件随机性例外；它依赖完整 KV 验证。[^9]

**2. 思路一：语义级选择有依据，但需要跨过四个缺口**

以下几项工作最有助于回答“同一请求中是否有可压缩的关键状态”：

| 工作 | 直接证据 | 对备份研究的启示与边界 |
|---|---|---|
| H2O，NeurIPS 2023 | 累积 attention 中存在 heavy hitters；结合近期 token 做动态保留 | 支撑重要性不均匀。不能把摘要中的“20% heavy hitters”直接当成全部持久备份只需 20% |
| SnapKV，NeurIPS 2024 | 用 prompt 末端观察窗口，为各 head 选择重要位置并保留局部邻域 | 适合已知当前问题的 prompt 压缩；不是任意未来问题或任意 decode 故障点的保证 |
| DuoAttention，ICLR 2025 | 区分保留完整历史的 retrieval heads 与只需 sinks、近期窗口的 streaming heads | 支撑沿 head 维度分配预算；相对原 dense 模型属于近似改造 |
| CAKE，ICLR 2025 | 根据层偏好和时间变化分配 cache 预算 | 支撑层间差异，但极低预算的摘要结论要回到分任务表格核对 |
| KVzip，NeurIPS 2025 | 通过上下文重建评分，构造可供未来不同查询使用的压缩 KV | 比单步 attention 更接近“故障后未来用途未知”的需求；上下文相关评分有额外开销 |
| KVzap，2026 预印本 | 用隐藏状态上的小模型近似重要性评分，覆盖 prefill 和 decode | 与 Qwen3 和长推理最贴近，适合做现实可行性基线；不是现成故障恢复证据 |

来源：H2O[^1]、SnapKV[^2]、DuoAttention[^3]、CAKE[^4]、KVzip[^5]、KVzap[^6]。

**这条路线为什么可能带来高度集中的备份收益？**

关键机制是：如果一个完整、位置正确的压缩快照已经足以让模型继续生成可接受的答案，恢复时就可以跳过其他历史 KV 的重建。它省下的是“等待完整历史状态就绪”这一阶段，而不仅是被保存那些 token 自身的计算。这与精确后缀备份只免去对应部分重算，具有不同的收益结构。

以快照正好覆盖故障游标为例，近似恢复延迟可表示为：

$$
R_{\mathrm{approx}}(S)\approx
T_{\mathrm{load}}(S)+T_{\mathrm{unpack}}(S)+T_{\mathrm{resume}}(S).
$$

这里不包含被主动放弃的旧 KV 的重建；如果快照陈旧，还须加入未提交尾部的处理成本。因此，“保留约 30% 状态，却绕过几乎全部历史 re-prefill”在机制上是可能的。它是否让总恢复时延大幅下降，仍取决于加载、解包、续跑质量和恢复排队。KV 压缩论文主要支撑其中的质量可行性，完整的备份收益链条需要新的故障实验来补上。

**第一，单步读取稀疏，不等于可以少备份。**

设第 j 个未来步骤使用的历史集合为 A_j。即使每个 A_j 很小，要支持后续多个步骤，所需状态可能接近这些集合的并集。查询变化时，并集可以不断扩大。Quest 每步根据 query 和页摘要挑选读取的页；其“token budget”主要衡量该步参与 attention 的数据，完整候选 KV 并未因此被证明可以永久丢弃。[^7]

这在原生稀疏模型上也存在。ECHO 的动机正是：稀疏 attention 降低计算和访问量后，KV 存储仍随上下文增长，因而需要 offload 与 recall。**如果主 GPU 故障后仍从完整 CPU KV 中召回冷数据，总备份口径必须包括那些 CPU 数据。** 该系统的无损预取结论不等于稀疏子集能独立承担恢复。[^8]

只有当模型规定一些状态从此不再被访问，例如严格局部 attention 的过期状态，才可以相对该模型安全地省略它们。此时公平基线也只备份该模型的存活状态。对有动态选择分支的模型，还需保存索引器、候选状态和其他必要分支状态；不能只数被选中的细粒度 KV。

**第二，attention 集中提供局部依据，但不是任务级充分条件。**

下面是本报告的单头分析。固定当前 query、keys、values，完整输出为 y=Σ_i a_i v_i，Σ_i a_i=1。裁剪掉总 attention 质量 ε<1 的集合，将保留部分重新归一化，得到 y_S。记被丢弃部分的归一化输出为 y_D，则：

$$
y-y_S=\epsilon(y_D-y_S),\qquad
\|y-y_S\|\le 2\epsilon V_{\max},
\quad \|v_i\|\le V_{\max}.
$$

因此，较小的遗漏 attention 质量能够控制**固定当前单头输出**的误差；考虑 value 对输出的影响，会比只按 token 语义或 attention 大小排序更有根据。但是，这没有控制后续层放大、未来 query 改变或自回归误差积累。选择几个人类认为重要的词，也不能保证保住模型的重要内部状态。

备份算法可以把局部误差指标当作候选评分依据，最终仍要以从实际故障点继续生成的任务质量来检验。保护 sinks、近期窗口和系统指令等结构性状态，应作为明确的预算组成，而不是统计时排除在“关键 KV”之外。

**第三，少量保留能够工作，但“多小”高度依赖任务。**

KVzip 报告在其评测中可将 KV 缩至约原来的 1/3–1/4；上下文相关评分的额外计算约相当于两次标准 prefill，必须考虑是否能被复用摊薄。它提供的是压缩后任务质量与推理效率证据，并没有测量 AegisKV 的故障收益。[^5]

更贴近当前模型的证据来自 KVzap 表 2：Qwen3-32B 的 RULER-16K 分数为 95.19→94.96，对应移除 65% KV；LongBench 为 50.56→50.40，对应移除 57%。也就是保留量约 35% 和 43%，不是普遍保留 5% 就足够。其 AIME25 只有 30 题、每题 4 次 rollout，论文也明确提出需要扩展到 agentic tasks。[^6]

极端压缩结果更要看细表。CAKE 的 32K NeedleBench 设置保留约 3.2% cache，但附录表 10 中 Mistral-7B 的综合分数从 78.28 降至 71.87；单项检索可以接近或超过全量，不能据此推广为所有子任务无损。这仍是“较少状态保留大量能力”的证据，同时也是不能把平均或单项结果写成通用保证的反例。[^4]

**第四，故障后的长未来，与压缩论文常测的短未来不同。**

KVzip 展示了为即时 query 选择的 cache 在多 query 场景下可能失效；SnapKV 本文也观察到不同指令会改变重要位置。[^2][^5] BeaconKV 这篇 2026-09 的预印本进一步报告，长推理中有少量 query 会突然回访较早的问题或计划，近期局部 attention 未必预测得到。它是值得追踪的机制证据，尚不应视为成熟容错方案。[^11]

近似恢复还有一个特有的实验条件：正常服务可能一直使用完整 KV，故障后才突然切到压缩状态。因此，必须测试“dense 正常前缀→故障→压缩状态续跑”，并将其与“一开始就压缩”的已有方法分别测量。错误的工具调用、函数参数或已经发出的结果，不能靠后来补齐 KV 自动修正。

**3. 思路二：后段重建更贵，成立到什么程度？**

对标准 dense causal Transformer，一个长度为 d、前面已有 p 个位置的 chunk，其 attention 对数为：

$$
A(p,d)=dp+\frac{d(d+1)}{2}.
$$

固定 d，位置越晚，attention 的计算工作越多；同一模型、层/head 范围和数据精度下，该 chunk 的 KV 字节基本不随位置变化。但是，KV 重建并不只有 attention，还包括线性投影、FFN、访存、launch、张量并行通信等。长上下文更可能放大位置差异，短上下文或其他算子占主导时差异可能很小。

这里已经有**直接而且较早的先行工作**。Cake 的核心 insight 就是后段计算更贵、同尺寸 KV 的 I/O 成本基本均匀；其 512-token chunk 实验验证这一趋势，再从前向重算和后向加载两端推进。它发表于 ICML 2025。不要与另一篇做驱逐的 CAKE 混淆。[^12]

CacheFlow 将这条路线扩展到 token、layer、GPU 维度，并研究批量恢复调度。因而，“发现后段 KV 更贵，然后优先备份后段”本身的论文创新空间有限。故障前的有限保护预算，与故障后从完整外部 cache 选择加载内容，仍有问题差别；但需要靠新的保护决策和端到端证据证明这个差别有实质意义。[^13]

**位置差异本身不能制造任意强的收益集中。**

用标准简化模型表示完整重算工作：

$$
C(N)=aN+bN^2,\qquad a,b\ge 0.
$$

其中线性项包含按 token 近似均匀的计算，二次项表示 causal attention；离散的线性余项也可以吸收到 a 中。假设完整保存末尾 rN 个 token 的所有所需 KV，并只重算前面 (1-r)N 个，则省下的重算工作比例为：

$$
S(r)=1-\frac{C((1-r)N)}{C(N)}
=\frac{arN+bN^2(2r-r^2)}{aN+bN^2}
\in[r,\;2r-r^2].
$$

| 完整 token KV 备份比例 r | 线性项主导时省下的工作 | 二次 attention 主导时的上限 |
|---:|---:|---:|
| 5% | 5% | 9.75% |
| 10% | 10% | 19% |
| 20% | 20% | 36% |
| 30% | 30% | 51% |
| 50% | 50% | 75% |

这是**工作量模型的条件化上限**，不包含备份加载成本，也不是普适时延下界。GPU 利用率台阶、批处理、恢复排队、跨设备并行会改变墙钟时间。但它已经足以说明：仅凭 causal attention 的二次复杂度，不能推出 10% 尾部 KV 免去大多数计算。附带的 POSITION_BOUND.csv 是上述公式的计算值，没有实验数据。

在最简单的理想并行恢复中，时间可以近似写作：

$$
T_{\mathrm{restore}}(r)\approx
\max\{T_{\mathrm{recompute}}((1-r)N),\;
T_{\mathrm{load}}(rN)\}+T_{\mathrm{sync}}.
$$

实际最优 r 要由目标 GPU、并发和传输链路测量。把上式自动当成线性成本或保证完全重叠，会高估收益。Cake/CacheFlow 是这类执行方式的先行工作，不应将重叠本身列为新的独立创新点。

**后段能否精确复用，与当前实现是否支持，是两件事。**

在相同 token 历史、位置、模型和必要元数据下，已备份的后段 KV 可以复用：先重建缺失的前段，装载后段，形成完整可用状态后继续推理。后段原先依赖前段，并不意味着前段重新生成后一定要重新生成后段。因果关系限制计算依赖，不会使已经保留的正确结果失去效力。

当前 AegisKV 的连续前缀恢复合同只是现有实现边界。支持后缀或非连续状态，需要显式保留原始位置、层/head 映射和恢复游标，并验证恢复 kernel 的依赖；不能直接把“命中的 KV 数量”当作一个更长的连续前缀。

还要注意，过去逐 token decode 花掉的总时延，不是已知输出的必然重建时延。若 token 日志可靠，历史输出可以作为已知序列做 re-prefill。LUMEN 也明确使用 retained token history 重建状态。用正常生成的 1-token decode 时延直接给输出 KV 标价，会夸大重建成本。[^21]

**4. 还有哪些方向更可能产生“小字节、大收益”？**

**4.1 全位置、低位宽的备份。** KIVI 的非对称 key/value 量化，以及 TurboQuant 的在线向量量化，说明删 token 并非唯一节省字节的办法。以 BF16 为参照，2-bit 载荷名义上为 1/8，但 scale、zero-point、分组、残留高精度窗口和对齐都必须计入；不能直接宣称实际备份压缩 8 倍。[^15][^16]

一个最应该实测的比较是：相同物理备份预算下，保留少量 BF16 KV，还是保留更多位置的低精度 KV，哪一个更能在故障后保持能力？如果量化本身就能稳定获胜，论文应转向状态表示或表示选择，而不是继续假设“必然存在最值得保留的 token 子集”。PM-KVQ 针对长推理的累计误差和敏感 block 分配精度，提醒我们全量低位宽也需要任务验证。[^17]

**4.2 沿 layer/head 分配预算，并考察成组保护。** DuoAttention 和 CAKE 支撑维度间需求差异。可保护检索头更多历史，对局部头保留 sinks 与窗口；也可采用层间不同精度。这里的科研问题不是把全请求 token 排一遍，而是比较物理可执行的保护粒度。[^3][^4]

对精确恢复，完整 token 范围的多层状态更容易省掉完整前向工作；零散 head 备份可能主要省少量投影或读取。因此，“最优近似保护集合”和“最优精确保护集合”很可能不同，这是一个值得测量、不能预设结果的研究假设。

**4.3 保存更便宜的中间表示。** HCache 保存每层输入隐藏状态，再通过 KV 投影恢复，避免重跑完整 attention 和 FFN。它为“重要的不是原始 KV，而是便宜的可恢复表示”提供了直接系统先例。[^14]

但不要照搬其 MHA 分析中的半尺寸结论。设隐藏维度为 D，KV-head 数为 H_kv，head 维度为 d_h，在相同精度下，每 token 每层的隐藏状态与 KV 字节比为：

$$
\frac{M_H}{M_{KV}}=\frac{D}{2H_{kv}d_h}.
$$

官方 Qwen3-32B 配置给出 D=5120、H_kv=8、d_h=128，得到 2.5。也就是说，朴素保存所有层完整隐藏状态，其逻辑载荷反而是 KV 的 2.5 倍；实际 TP 布局还要另外计量复制和分片。HCache 值得借鉴恢复方式，但不能在当前 GQA 模型上未经核算就声称更省备份空间。[^23]

**4.4 合成少量辅助状态，弥补裁剪损失。** RestoreKV 是 2026-08 的新预印本：裁剪前让少量可学习 restore tokens 读取完整上下文，用生成的辅助 KV 和保留 KV 共同组成固定预算。默认 8 个 restore tokens，包含在总预算中。它直接支持“除了挑选原有 KV，还可以构造更有效的备份表示”这一扩展。[^10]

边界也很清楚：需要训练；其恢复指压缩后的行为改善，不是故障后精确重建原始 KV。主表中的激进压缩仍有质量损失。用于故障备份时，还要处理长 decode 期间的在线更新和位置变化，不能把 prefill 后的一次构造开销直接当作全生命周期开销。

**4.5 幸存分片上的纠删码。** GhostServe 使用跨设备 KV 分片生成少量 parity，并将 FP16 按位重解释后做可逆编码。它比语义选择更直接支撑“少量额外冗余、精确恢复”这一命题。论文的 8:2 配置，相对完整复制减少 75% 冗余量，但依赖剩余数据分片仍然存在。[^18]

如果一个请求只在单 GPU 上，而故障把其全部原始 KV 和同故障域的内存一起带走，不能只留下很小的 parity 就恢复任意完整数据。节点、GPU、进程故障必须分别定义。是否符合 AegisKV 目标故障域，比编码算法选择更先决。

**4.6 已有完整基础状态上的小增量。** 如果请求的大部分 prefix 已经在独立故障域持久保存，新增少量尾部即可免掉大部分剩余重算。但这里小的是“本次新增备份量”，不是“总持久状态”。已有流式状态复制如 DéjàVu、异步 host 备份如 FailSafe，必须作为背景和基线；不能重新把增量复制本身当成创新。[^19][^20]

**4.7 压缩草稿与精确验证。** VeriCache 已经用压缩 KV 起草、完整 KV 验证。在故障恢复中，可以研究草稿生成与缺失状态重建的重叠，但这是更复杂的支线。若完整状态也丢失，验证仍要等待重建；首次草稿 token 不等于首次可提交 token，同 GPU 上两种计算还可能互相争用。[^9]

因此，“先近似输出，后台补齐，最终还是精确恢复”这个说法不成立。要保留精确语义，未验证输出必须缓冲，错误草稿必须丢弃或回滚，并将验证等待与成本纳入结果。

**5. 怎样形成足够扎实的 Motivation 和创新点**

可以由现有文献支持的动机是：KV 的质量贡献并不均匀，重算成本也不完全均匀；不同的压缩或恢复方式利用的是不同结构。现有证据不足以直接支持的动机是：目标工作负载中，一小部分可在线识别、可廉价维护、可独立恢复的物理状态，必然覆盖大部分故障收益。

论文需要补上的应该是后一个命题。它包含三个可证伪的问题：

1. **集中性**：预算从 0 增加到 5%、10%、20%、40% 时，恢复收益和任务质量分别怎样变化？最佳可行曲线是否确实有早期快速提升？
2. **可预测性**：只看故障前已知的信息，是否能接近离线未来信息参考？瞬时重要性与未来可用性相差多少？
3. **可实现性**：把评分、打包、维护、复制、解码和错误后果计入后，是否仍胜过量化、后缀备份和已有压缩方案？

单独把 H2O/SnapKV 接在 checkpoint 前面，或把 Cake 的后段加载策略变成后段复制，通常不足以构成强算法贡献。更有说服力的候选贡献，是发现并解决以下至少一个真实矛盾：

| 矛盾 | 可研究的机制 | 需要证明的东西 |
|---|---|---|
| 当前 attention 重要性与未来故障后用途不一致 | 基于未来使用风险、时间稳定性或低成本预测的保护集合 | 相同质量和备份预算下，明显改善故障后的真实任务结果 |
| 逻辑上稀疏，物理页和传输仍不稀疏 | 面向可复制页/段的分组选择和紧凑表示 | 优勢在实际物理字节、复制带宽和恢复时间上仍存在 |
| 低精度全状态与高精度少量状态各有优势 | 依请求内容和恢复合同选择表示或混合精度 | 优于各单一方式及公平调优的组合基线 |
| 备份很小但重要性变化导致反复写入 | 增量更新、稳定性约束和更新时机 | 当前占用小之外，总写入量和正常服务开销也低 |
| 精确重建依赖成组状态，质量保护依赖少量 head | 合同明确的成组保护与恢复计划 | 解释并验证两类最优集合的差异，而不是套一个通用评分 |

这是候选研究空间，不是已经确认的“无人做过”。本次检索覆盖了上述直接竞争工作，仍不能排除并行预印本、尚未公开的系统或不同命名的近邻方案。论文定位应围绕明确机制与比较证据建立。

**一个可操作的问题定义。** 对请求内的保护集合 S、表示 e 和恢复计划 π，定义 R(S,e,π) 为从故障发生到可提交后续输出的延迟。以给定 Slack s_r 做暴露延迟的近似映射：

$$
U_r(S,e,\pi)=
[R(\varnothing)-s_r]_+
-[R(S,e,\pi)-s_r]_+.
$$

在物理字节预算、持续写入预算、正常服务开销预算以及质量容差约束下，研究 U_r 的可达范围。精确合同另要求必要状态或输出等价性成立。这个定义只描述请求内评估，不重做已经给定的请求级重要性选择。

若用于完整工作流，上式仍只是局部近似，不能直接将各请求 U_r 相加当成精确 WCT 收益。评测应回到工作流 DAG、相同请求身份和相同逻辑故障进度，测量真实完成时间。

Slack 也能产生看似强烈的集中效应：例如原恢复 1000 ms、Slack 900 ms，省下 150 ms 即可把暴露延迟从 100 ms 降到 0。这里消除的是全部暴露惩罚，重建本身只快了 15%；绝对收益仅 100 ms。应分别报告这两个结果，避免把门槛效应误写成“少量 KV 免去大部分计算”。

单个块的价值应是给定其他保护状态后的条件边际收益。多个 KV 可能互补，两个证据片段共同决定多跳答案，单独保存一个未必有效。没有额外假设时，不应声称总收益可加、一定单调次模，或者简单 greedy 有全局保证。

**6. 最小而有区分力的实验，先验证选题再做大系统**

以下是建议的实验计划，没有宣称这些实验已经执行。第一阶段的目标是快速发现负结果，而不是生成漂亮的平均曲线。

**实验 A：固定恢复合同下的字节—收益—质量前沿。**

先固定请求级策略，选一个容易跑通的模型和目标 Qwen3-32B，覆盖长文档 QA、包含多处证据的检索、长推理，以及代码/工具调用。每条原始请求先正常执行，再在相同逻辑 token 游标切断主状态；所有方法共享故障点、输入、模型版本和质量评估。

测试完整 BF16 备份、无 KV 备份加可靠 token 重算、前缀/后缀/均匀/随机完整块、近期窗口加 sinks、SnapKV、KVzap，以及 2/4/8-bit 全位置备份。资源不足时先跑后缀、KVzap、4-bit 与全量四条主线，随后补齐必要基线；KVzip 可作高开销离线参考。固定相同物理预算，不按不同方法各自声称的 compression ratio 对齐。

预算扫描建议包括 5%、10%、20%、40%、60%、100%。对每个预算同时记录：备份实际字节、恢复到首个可提交 token 的时间、剩余请求完成时间、任务成功率差异。先判断有无收益集中，再设计更复杂算法。

可以报告相对全量备份参照的收益比 η(B)=[R(0)−R(B)]/[R(0)−R(full)]，仅在分母为正且质量合同满足时解释；必须同时给出三个绝对时间。近似紧凑状态有时加载得比全量更快，η 可能超过 1，所以它不是天然限制在 0–100% 的比例，不能截断后掩盖不同恢复合同的差异。

**实验 B：把“后段更贵”测成真实成本曲线。**

固定 chunk 长度，测不同 past-KV 长度下的 re-prefill 延迟，并分解 attention、投影/FFN、通信和传输；至少覆盖短长上下文及两种并发。输出 token 已知时使用真实 replay/re-prefill 路径。

同时比较只重算、串行加载加重算、Cake 式前向重算/后向加载，以及系统实际能够支持的恢复实现。若新方法只赢过一个不支持后缀复用的旧恢复器，不能把全部差距归因于保护策略。

**实验 C：故障前重要性是否能预测故障后的需要。**

对相同备份预算，测不同快照陈旧程度和不同续跑长度，并加入从局部推理转向早期证据回访的请求。用完整执行得到的未来 attention 或任务信息构造离线参考，它只能是不可部署参考，不能混入在线方法。

重点不是 attention-hit 本身，而是它与任务成功率、输出差异和实际恢复收益是否相关。若“oracle”也找不到少量高收益集合，继续改在线评分器通常不会解决问题。任务反馈辅助搜索只能称离线参考，未经穷举或证明不能称全局最优上界。

**实验 D：逻辑 KV 节省能否落到真实字节。**

统计 token×layer×KV-head 保留率和物理页占用率，并包括位置索引、量化参数、对齐、窗口、打包缓冲和 TP 复制。NVIDIA 的基础设施分析指出，页中仍有存活数据时，逐项驱逐并不会自动释放整页；重要性评分也可能与高效 attention kernel 不兼容。[^22]

如果使用紧凑序列化备份，可以节省传输但恢复时需要散布或专用布局；这部分成本应单独测量。GQA 中多个 query heads 共用 KV heads，不能将 query-head 裁剪数量直接换算为 KV 字节。

**实验 E：持续维护成本与故障收益能否抵消。**

记录评分开销、备份更新周期、每次更新新写入量和正常服务的吞吐/尾延迟。一个仅占 10% 空间但频繁替换内容的备份，其累计写流量可能很大。对上下文相关的高成本评分，只有重复使用或其他收益足以摊销时才合理。

在同一成本口径下，至少检查“故障概率×单次收益”与持续开销的关系，并报告不同故障率、任务长度、更新周期的敏感性。SLO 尾风险与平均 GPU 时间可分别优化，不能混用单位推导一个净收益数字。

**实验 F：正确性与全工作流结果。**

精确状态路径核对恢复张量、token 历史和提交游标；声明数值容差与确定性设置。近似路径报告质量容差内的通过比例、最差任务组和长输出结果，而不只平均分。工具调用需用可验证的参数和功能结果计分。

保持相同工作流/Agent 身份与相同逻辑进度的故障对照。分别报告无故障开销、故障后的恢复时延和 WCT 增量；保留失败、质量下降、零收益和负收益。抽样任务使用配对统计与置信区间，预先选质量容差，避免挑选最有利的故障时刻或随机种子。

**决定是否继续投入的门槛。** 若在目标任务里，即使离线参考也要保留大部分物理状态，或低位宽全量备份已经稳定优于语义子集，就应收缩“关键 KV 子集”的论文主张。若 oracle 收益集中但在线预测失败，研究重点是预测；若逻辑收益集中但系统收益消失，重点是布局与维护。只有两者都成立，才适合把选择算法作为论文核心。

**7. 对当前 AegisKV 模型的具体影响**

本次检查的请求恢复估值位于 [lease_value.py](../../../../../python/moonkvsim/aegiskv/lease_value.py)，RecoveryAgent.curve 使用 prompt 与已知 output 的 1:8 工作权重，并按前缀累计字节构造恢复曲线。该模型没有表示 attention 的内容重要性，在同一阶段内也没有完整表达 token 位置带来的二次工作差异。因此它无法单独验证本报告的两条主张。

仓库另一个 [Qwen3-32B TP4 时延模型](../../../../../python/moonkvsim/aegiskv/qwen3_32b_tp4_duration.py) 在 _phase_breakdown 中显式计算 extend_length×past_kv_length + extend_length×(extend_length+1)/2。这可作为位置相关成本建模的起点，仍须物理 profile 校准；不等于当前保护算法已经使用了这项差异。

现有恢复接口若只接受连续 prefix，语义子集或后缀保护需要新的恢复状态表示和执行路径。只把保存比例乘到原来的 T(k) 上，会把“不支持的非连续复用”错误模拟成收益；把 KVzip 的准确率曲线直接转成恢复时延，也没有依据。

适合的下一步是保留请求级 Slack 输入，对请求内候选保护方案补三类独立数据：实际物理字节、可执行恢复成本、故障后续跑质量。前两类可以进入系统模型，第三类必须来自真实模型执行。校准后的模拟能够扩大调度评估规模，但不能代替语义质量验证。

**8. 建议采用的论文主线**

优先探索**在正常服务保持既定模型行为的前提下，为故障恢复维护一个质量约束下的紧凑请求状态**。把 token 选择、head/layer 分配和低位宽表示视为竞争方案，先找出目标任务里实际存在的收益集中，再围绕它设计低维护开销的备份机制。精确后缀恢复用作强基线；需要精确且故障域允许时，再比较编码或幸存基础状态上的增量。

初稿 Motivation 可以按以下逻辑展开：请求级重要性只能决定保护谁；请求内部的状态具有不同质量贡献、重建依赖和维护成本。已有压缩算法主要优化正常推理的内存与计算，已有恢复系统主要优化完整可得状态的加载或重算。本文要验证并解决的是：在故障前有限保护预算下，这些差异是否能转化为可预测、可维护、正确性明确的恢复收益。

其中“转化是否成立”必须由目标请求的实测支撑。基于目前文献，**语义/表示方向值得做选题验证；位置方向适合作为精确恢复的重要组成部分，单独作为核心新发现较弱。** 研究结果也可能是高收益来自低精度全状态、Slack 门槛或幸存依赖，而不是少数 token。论文应允许并保留这种结论。

**来源与阅读范围**

检索截止 2026-09-11。以下均为论文、作者/机构页面或官方实现资料。已发表状态以会议官方页面核对；未核实正式发表的工作标为预印本。详细阅读范围、适用合同和不能支持的结论见 [LITERATURE.csv](LITERATURE.csv)。报告中的推导、研究假设、实验门槛与建议均为分析，不是引用论文的实测结果。未执行新的 GPU 或 DES 实验。

[^1]: Zhenyu Zhang et al. **H2O: Heavy-Hitter Oracle for Efficient Generative Inference of Large Language Models**. NeurIPS 2023. [官方论文页](https://proceedings.neurips.cc/paper_files/paper/2023/hash/6ceefa7b15572587b78ecfcebb2827f8-Abstract-Conference.html)。核对官方摘要中的机制、模型范围与 20% 表述。
[^2]: Yuhong Li et al. **SnapKV: LLM Knows What You are Looking for Before Generation**. NeurIPS 2024. [官方论文页](https://proceedings.neurips.cc/paper_files/paper/2024/hash/28ab418242603e0f7323e54185d19bde-Abstract-Conference.html)；[正文 §4、§7](https://arxiv.org/html/2404.14469v2)。
[^3]: Guangxuan Xiao et al. **DuoAttention: Efficient Long-Context LLM Inference with Retrieval and Streaming Heads**. ICLR 2025. [官方论文页](https://proceedings.iclr.cc/paper_files/paper/2025/hash/5c1ddd2e59df46fd2aa85c833b1b36ed-Abstract-Conference.html)；[正文 §2、§3.4](https://arxiv.org/html/2410.10819v1)。
[^4]: Ziran Qin et al. **CAKE: Cascading and Adaptive KV Cache Eviction with Layer Preferences**. ICLR 2025. [官方论文页](https://proceedings.iclr.cc/paper_files/paper/2025/hash/dfae940651f3e690a12e19c874edad7c-Abstract-Conference.html)；[正文 §5 与附录表 10](https://arxiv.org/html/2503.12491v1)。与第 12 项 Cake 是不同工作。
[^5]: Jang-Hyun Kim et al. **KVzip: Query-Agnostic KV Cache Compression with Context Reconstruction**. NeurIPS 2025. [官方论文页](https://proceedings.neurips.cc/paper_files/paper/2025/hash/f4eaa4b8f2d08edb3f0af990d56134ea-Abstract-Conference.html)；[正文 §2、§3.4、§4 与限制](https://arxiv.org/html/2505.23416v2)。
[^6]: Simon Jegou, Maximilian Jeblick. **KVzap: Fast, Adaptive, and Faithful KV Cache Pruning**. 2026 预印本. [正文 §2、§3.3–3.8、表 2、§4](https://arxiv.org/html/2601.07891v1)；[官方实现](https://github.com/NVIDIA/kvpress)。
[^7]: Jiaming Tang et al. **Quest: Query-Aware Sparsity for Efficient Long-Context LLM Inference**. ICML 2024. [官方论文页](https://proceedings.mlr.press/v235/tang24l.html)；[正文 §3.4–3.5、表 1](https://arxiv.org/html/2406.10774v1)。
[^8]: Guangda Liu et al. **ECHO: Efficient KV Cache Offloading with Lossless Prefetching for Serving Native Sparse Attention LLMs**. OSDI 2026, pp. 17–37. [USENIX 官方论文页与摘要](https://www.usenix.org/conference/osdi26/presentation/liu-guangda)。
[^9]: Jiayi Yao et al. **VeriCache: Turning Lossy KV Cache into Lossless LLM Inference**. 2026 预印本. [正文 §1、§3–4 与正确性脚注](https://arxiv.org/html/2605.17613v1)；[微软研究院作者页面](https://www.microsoft.com/en-us/research/publication/vericache-turning-lossy-kv-cache-into-lossless-llm-inference/)。
[^10]: Changwoo Baek, Seungjun Shin, Kyeongbo Kong. **RestoreKV: Recovering Full-Cache Behavior Under Aggressive Query-Agnostic KV Cache Eviction**. 2026-08 预印本. [正文 §3、§4.4–4.5、表 3–4](https://arxiv.org/html/2608.01247v1)。
[^11]: Janghyeon Kim et al. **BeaconKV: Key-Value Cache Compression Guided by Beacon Queries for Efficient Large Reasoning Model Inference**. 2026-09 预印本. [正文 §3.1](https://arxiv.org/html/2609.04971v1)。用于未来重要性变化的机制证据，不作为容错实测证据。
[^12]: Shuowei Jin, Xueshen Liu, Qingzhao Zhang, Zhuoqing Mao（Z. Morley Mao）. **Compute or Load KV Cache? Why Not Both?**（Cake）. ICML 2025. [官方论文页](https://proceedings.mlr.press/v267/jin25d.html)；[正文 §4、图 4 说明、附录算法](https://arxiv.org/html/2410.03065v2)。
[^13]: Sean Nian, Jiahao Fang, Qilong Feng, Zhiyu Wu, Fan Lai. **CacheFlow: Efficient LLM Serving with 3D-Parallel KV Cache Restoration**. 2026-04 预印本. [正文 §3.1–3.3、§4](https://arxiv.org/html/2604.25080v1)。
[^14]: Shiwei Gao, Youmin Chen, Jiwu Shu. **Fast State Restoration in LLM Serving with HCache**. EuroSys 2025. [作者提供的会议论文](https://chenyoumin1993.github.io/papers/eurosys25-hcache.pdf)；[正文 §3.1–3.2 的 MHA 分析](https://arxiv.org/html/2410.05004v1)；[会议录用目录](https://2025.eurosys.org/accepted-papers.html)。
[^15]: Zirui Liu et al. **KIVI: A Tuning-Free Asymmetric 2bit Quantization for KV Cache**. ICML 2024. [官方论文页](https://proceedings.mlr.press/v235/liu24bz.html)；[正文与 residual-length 消融](https://arxiv.org/html/2402.02750v1)。
[^16]: Amir Zandieh, Majid Daliri, Majid Hadian, Vahab Mirrokni. **TurboQuant: Online Vector Quantization with Near-optimal Distortion Rate**. ICLR 2026. [官方论文页与摘要](https://proceedings.iclr.cc/paper_files/paper/2026/hash/5c802ef38ab6e366c2ea06eee554c088-Abstract-Conference.html)。采用有损量化的定义；不将质量中性表述解释为张量无损。
[^17]: Tengxuan Liu et al. **PM-KVQ: Progressive Mixed-precision KV Cache Quantization for Long-CoT LLMs**. ICLR 2026. [官方论文页与摘要](https://proceedings.iclr.cc/paper_files/paper/2026/hash/afb8caec018d3c8f6ef8b81fa52386fe-Abstract-Conference.html)。
[^18]: Shakya Jayakody, Youpeng Zhao, Chinmay Dhanraj Nehate, Jun Wang. **GhostServe: A Lightweight Checkpointing System in the Shadow for Fault-Tolerant LLM Serving**. MLSys 2026. [官方论文页](https://proceedings.mlsys.org/paper_files/paper/2026/hash/d99e8e80a6c41e148db686918dd7eab3-Abstract-Conference.html)；[正文 §4.1–4.2](https://arxiv.org/html/2605.00831v1)。
[^19]: Foteini Strati, Sara Mcallister, Amar Phanishayee, Jakub Tarnawski, Ana Klimovic. **DéjàVu: KV-cache Streaming for Fast, Fault-tolerant Generative LLM Serving**. ICML 2024. [官方论文页与摘要](https://proceedings.mlr.press/v235/strati24a.html)。
[^20]: Ziyi Xu, Zhiqiang Xie, Swapnil Gandhi, Christos Kozyrakis. **FailSafe: High-performance Resilient Serving**. 2025 预印本；本次未核实后续会议状态. [正文 §3.2](https://arxiv.org/html/2511.14116v1)。
[^21]: Zhang Cao, Shujie Han, Juncheng Zhang, Yuanming Ren, Yongkun Li, Patrick P. C. Lee. **LUMEN: Coordinated Failure Recovery for Distributed LLM Serving**. 2026-06 预印本. [正文 §3.2、§4.1 与恢复设计](https://arxiv.org/html/2606.17787v1)。
[^22]: Weian Mao, Yukang Chen, Wei Huang, Shuai Yang, Luozhou Wang, Song Han. **KV Cache Compression and Its Infra Problems**. NVIDIA Efficient AI 技术文章，2026-06-12. [原文](https://research.nvidia.com/labs/eai/post/kv-cache-compression-and-its-infra-problems/)。基础设施说明，非同行评审论文。
[^23]: Qwen Team. **Qwen3-32B 官方模型配置**. [config.json](https://huggingface.co/Qwen/Qwen3-32B/blob/main/config.json)。本次核对 hidden_size=5120、num_key_value_heads=8、head_dim=128；比例 2.5 为本报告据配置推导。
