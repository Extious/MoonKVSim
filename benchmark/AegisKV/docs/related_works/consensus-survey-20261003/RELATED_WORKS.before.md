# AegisKV Related Works 论文索引

本索引生成于 2026-09-01、续核于 2026-09-02，按本地目录年份归档，共收录 97 篇论文。简介基于本地 PDF 首页、摘要及必要正文整理；目录年份不一定等于论文首发年份或正式发表年份，身份以本地 PDF 可核验信息为准，并对明确需要修正的正式出版信息作了核对。匿名、保密或仅有本地稿件的材料不可对外分发，也不应按正式论文引用。

**年份导航：** [2021（1）](#20211-篇) · [2024（2）](#20242-篇) · [2025（30）](#202530-篇) · [2026（64）](#202664-篇)

**主题规模：** 故障容错、检查点与恢复 13 篇 · Agentic Workflow 与工作流调度 20 篇 · KV Cache 管理、复用与分层存储 45 篇 · LLM Serving 调度、内存与执行系统 11 篇 · 资源管理、可靠性与外围参考 8 篇。

**优先阅读（最接近 AegisKV）：**
- 故障：LUMEN、RaidServe、KevlarFlow、GhostServe、DéjàVu、HCache
- 工作流：TOPAS、HexAGenT、SAGA、KVFlow、Continuum、Cortex
- KV 存储：Mooncake、Strata、SYMPHONY、Tutti、解耦 KV 立场稿、KV 综述

**阅读提示：** 每篇条目包含身份、简介和与 AegisKV 的关系；其中“与 AegisKV 的关系”是本项目的分析，不是原论文自述。每个年份内部按与 AegisKV 的接近程度依次组织为：故障容错、检查点与恢复 → Agentic Workflow 与工作流调度 → KV Cache 管理、复用与分层存储 → LLM Serving 调度、内存与执行系统 → 资源管理、可靠性与外围参考；仅显示该年实际包含论文的主题。2026 年 KV 一类再按分层存储/解耦、offload 与预取、亲和路由、压缩与复用细分。跨主题论文按主要贡献唯一归类，目录年份保持不变。

## 2021（1 篇）

本年收录：资源管理、可靠性与外围参考 1 篇。

### 资源管理、可靠性与外围参考

这组工作从通用资源控制、语义可靠性、软错误或上下文处理侧提供外围背景，不与 AegisKV 的 fail-stop KV 恢复直接等价。

#### [DRLPart: A Deep Reinforcement Learning Framework for Optimally Efficient and Robust Resource Partitioning on Commodity Servers](2021/DRLPart%20-%20A%20Deep%20Reinforcement%20Learning%20Framework%20for%20Optimally%20Efficient%20and%20Robust%20Resource%20Partitioning%20on%20Commodity%20Servers.pdf)
- 身份：published
- 简介：面向商用服务器上共置工作负载的 CPU 核、末级缓存和内存带宽联合分区问题，DRLPart 用深度强化学习从实时性能计数器等系统状态直接生成资源分配。它以离线性能预测模型降低训练交互成本，并在发现高预测误差时通过专用模型和贪心搜索在线微调异常决策。
- 与 AegisKV 的关系：属于外围的自适应资源管理思路，可对照 AegisKV 的 HBMQuotaAIMD 和 Peer-HBM 容量控制；但它优化通用服务器吞吐量，不处理 KV 后缀保护、故障恢复收益/受害者损失门控或副本一致性。

## 2024（2 篇）

本年收录：故障容错、检查点与恢复 1 篇；KV Cache 管理、复用与分层存储 1 篇。

### 故障容错、检查点与恢复

这组工作直接讨论 fail-stop、KV 状态保护、检查点、重建与恢复路径，是 AegisKV 的核心基线与机制参照。

#### [DéjàVu: KV-cache Streaming for Fast, Fault-tolerant Generative LLM Serving](2024/DejaVu%3A%20KV-cache%20Streaming%20for%20Fast%2C%20Fault-tolerant%20Generative%20LLM%20Serving.pdf)
- 身份：正式发表：ICML 2024（PMLR 235）；本地 PDF 为带 arXiv:2403.01876v1 标记的版本形态。
- 简介：DéjàVu 以高效 KV-cache 流式传输库为基础，将 prefill 与 decode 分离以减少流水线气泡，并通过微批次级 CPU/GPU 换入换出提高显存利用率。它还按 token 增量复制 KV 状态，结合心跳检测与流水线恢复，使故障后从最近已复制位置继续执行。
- 与 AegisKV 的关系：与 AegisKV 的跨节点 KV 保护、故障 fencing、恢复激活和传输成本建模直接相关，是连续复制路线的近邻。AegisKV 更侧重按恢复伤害收益、受害者损失与 HBM 压力选择性准入和驱逐保护后缀，而非固定邻居的持续全量增量复制。

### KV Cache 管理、复用与分层存储

这组工作覆盖 KV 的复用、放置、驱逐、压缩、路由及跨 HBM/DRAM/SSD/CXL 层流动，为 AegisKV 的容量与传输权衡提供基线。

#### [Prompt Cache: Modular Attention Reuse for Low-Latency Inference](2024/Prompt%20Cache%20-%20Modular%20Attention%20Reuse%20for%20Low-Latency%20Inference.pdf)
- 身份：published
- 简介：Prompt Cache 将跨请求反复出现的系统消息、模板和文档定义为带稳定位置编号的 prompt modules，预计算并复用其 KV 注意力状态，从而跳过相应 prefill 计算。其 PML schema、参数化模块和不连续 position ID 支持组合式复用，主要降低首 token 延迟。
- 与 AegisKV 的关系：与 AegisKV 的 content alias、共享物理 KV 分配及逻辑请求独立 frontier/key binding 直接相关，可作为重复前缀去重与复用的参考。它关注正常路径的跨请求计算复用，不涵盖故障下的保护准入、后缀安全驱逐和恢复调度。

## 2025（30 篇）

本年收录：故障容错、检查点与恢复 1 篇；Agentic Workflow 与工作流调度 4 篇；KV Cache 管理、复用与分层存储 12 篇；LLM Serving 调度、内存与执行系统 7 篇；资源管理、可靠性与外围参考 6 篇。

本年主题：[故障容错](#2025-failure) · [工作流](#2025-workflow) · [KV Cache](#2025-kv) · [Serving](#2025-serving) · [外围参考](#2025-peripheral)

<a id="2025-failure"></a>
### 故障容错、检查点与恢复

这组工作直接讨论 fail-stop、KV 状态保护、检查点、重建与恢复路径，是 AegisKV 的核心基线与机制参照。

#### [Fast State Restoration in LLM Serving with HCache](2025/Fast%20State%20Restoration%20in%20LLM%20Serving%20with%20HCache.pdf)
- 身份：published：EuroSys 2025 正式发表（DOI 10.1145/3689031.3696072）
- 简介：论文指出从 token 重算 KV 偏计算密集，而直接卸载/回载 KV 偏 I/O 密集。HCache 保存中间激活来恢复状态，并以无气泡调度组合互补的计算与 I/O 路径，同时用 chunk 存储管理解决保存与恢复布局不匹配。
- 与 AegisKV 的关系：它是 AegisKV 恢复路径的重要近邻：都权衡重算、传输和分块状态。区别在于 HCache 针对容量驱动的状态淘汰与恢复，AegisKV 还要求故障域隔离、保护准入和故障后可用性。

<a id="2025-workflow"></a>
### Agentic Workflow 与工作流调度

这组工作以 agent 程序或工作流 DAG 为调度对象，为 AegisKV 的关键路径、slack、JCT 和工具调用连续性建模提供参照。

#### [KVFlow: Efficient Prefix Caching for Accelerating LLM-Based Multi-Agent Workflows](2025/KVFlow%3A%20Efficient%20Prefix%20Caching%20for%20Accelerating%20LLM-Based%20Multi-Agent%20Workflows.pdf)
- 身份：preprint：公开 arXiv 预印本（2507.07400v1），PDF 明示 “Preprint. Under review.”
- 简介：论文指出 LRU 不理解智能体执行顺序，常在代理即将再次激活前淘汰其 prefix KV。KVFlow 用 Agent Step Graph 估计 steps-to-execution，做节点级工作流感知淘汰，并提前从 CPU 向 GPU 预取下一步代理所需 KV。
- 与 AegisKV 的关系：它与 AegisKV 的工作流 DAG、缓存淘汰和传输重叠直接相关；AegisKV 可借鉴未来激活距离，但其准入依据还必须包含故障恢复伤害与故障域约束。该稿尚在审，结果应审慎使用。

#### [Continuum: Efficient and Robust Multi-Turn LLM Agent Scheduling with KV Cache Time-to-Live](2025/Continuum%3A%20Efficient%20and%20Robust%20Multi-Turn%20LLM%20Agent%20Scheduling%20with%20KV%20Cache%20Time-to-Live.pdf)
- 身份：preprint：公开 arXiv 预印本（2511.02230；所存 PDF 为 2026-05-25 的 v6，尚无会议出版信息）
- 简介：论文针对智能体在 LLM 调用与工具调用间暂停时，turn 结束即淘汰 KV 会导致重算/重载及逐轮排队延迟。Continuum 为 GPU 中的 KV 设置由重载成本与淘汰后排队代价共同决定的 TTL，并结合 program-level FCFS 保持多轮连续性。
- 与 AegisKV 的关系：它与 AegisKV 都需判断 KV 保留价值和内存压力，但 Continuum 优化无故障多轮驻留，AegisKV 优化跨故障域保护及恢复伤害。TTL/排队代价可启发 AegisKV 的收益模型，却不能替代故障安全门槛。

#### [Cortex: Workflow-Aware Resource Pooling and Scheduling for Agentic Serving](2025/Cortex%3A%20Workflow-Aware%20Resource%20Pooling%20and%20Scheduling%20for%20Agentic%20Serving.pdf)
- 身份：preprint：公开 arXiv 预印本（2510.14126v1）；正文称 prototype，未见正式出版信息
- 简介：论文主张按智能体工作流阶段隔离资源池，为每个阶段配置独立引擎、队列、缓存与扩缩容策略。编排器基于调用图、SLO slack、阶段选择性和服务时间调度，以减少跨阶段干扰并提高 KV locality。
- 与 AegisKV 的关系：其工作流感知、阶段隔离和 slack 优先级与 AegisKV 的 DAG 工作负载、SLO 伤害建模相关。它不涉及节点失效或冗余 KV，更多是正常态资源编排的互补方案。

#### [HEXGEN-TEXT2SQL: Optimizing LLM Inference Request Scheduling for Agentic Text-to-SQL Workflows](2025/HEXGEN-TEXT2SQL%20-%20Optimizing%20LLM%20Inference%20Request%20Scheduling%20for%20Agentic%20Text-to-SQL%20Workflow.pdf)
- 身份：preprint：公开 arXiv 预印本（2505.05286v1），未见正式出版信息
- 简介：论文面向多租户、异构 GPU 上的多阶段 Text-to-SQL 智能体工作流，处理任务依赖、时延波动和端到端 deadline。它采用全局负载均衡分发与实例内基于剩余 slack/执行时间的紧迫度优先，并用轻量模拟调参。
- 与 AegisKV 的关系：它与 AegisKV 的工作流 DAG、异构资源、slack 和模拟评估直接相关，但没有 KV 保护/恢复机制。其层次调度可作为故障前后请求排序的互补背景。

<a id="2025-kv"></a>
### KV Cache 管理、复用与分层存储

这组工作覆盖 KV 的复用、放置、驱逐、压缩、路由及跨 HBM/DRAM/SSD/CXL 层流动，为 AegisKV 的容量与传输权衡提供基线。

#### [MOONCAKE: Trading More Storage for Less Computation — A KVCache-centric Architecture for Serving LLM Chatbot](2025/MOONCAKE%3A%20Trading%20More%20Storage%20for%20Less%20Computation---A%20KVCache-centric%20Architecture%20for%20Serving%20LLM%20Chatbot.pdf)
- 身份：published：FAST 2025 正式发表（USENIX 论文集）
- 简介：论文介绍 Kimi 的生产平台，以 prefill/decode 分离和汇聚 CPU、DRAM、SSD、NIC 的分布式 KVCache 为核心。全局缓存与调度器以 SLO 下的有效吞吐为目标，在大规模部署中以更多存储减少重复计算。
- 与 AegisKV 的关系：它是 AegisKV 的直接系统底座与最重要对照：AegisKV 在 Mooncake 式全局 KV/Store 架构上增加故障保护、Peer-HBM 冗余和恢复控制。比较时应明确哪些能力来自 Mooncake 基线，哪些来自 AegisKV。

#### [IMPRESS: An Importance-Informed Multi-Tier Prefix KV Storage System for Large Language Model Inference](2025/IMPRESS%3A%20An%20Importance-Informed%20Multi-Tier%20Prefix%20KV%20Storage%20System%20for%20Large%20Language%20Model%20Inference.pdf)
- 身份：published：FAST 2025 正式发表（USENIX 论文集）
- 简介：论文针对 prefix KV 落盘后 I/O 可能抵消复用收益的问题，只加载对输出更重要的 prefix KV。IMPRESS 利用不同 attention head 重要 token 集合的相似性高效识别重要项，并据此管理 GPU、CPU 和磁盘多级存储。
- 与 AegisKV 的关系：它与 AegisKV 的多级 KV Store、选择性搬运和 TTFT 权衡高度相关。IMPRESS 允许丢弃低重要度 KV 以维持近似精度，而 AegisKV 的故障恢复若要求精确状态，不能直接采用同一语义。

#### [Shared Disk KV Cache Management for Efficient Multi-Instance Inference in RAG-Powered LLMs](2025/Shared%20Disk%20KV%20Cache%20Management%20for%20Efficient%20Multi-Instance%20Inference%20in%20RAG-Powered%20LLMs.pdf)
- 身份：preprint：公开 arXiv 预印本（2504.11765v1），未见正式出版信息
- 简介：论文利用 RAG 查询对文档的访问局部性，预生成常用文档的 KV 并持久化到磁盘。Shared RAG-DCache 在多个 LLM 实例间共享这些 disk KV，并结合排队延迟和资源配置提升吞吐、降低 TTFT。
- 与 AegisKV 的关系：它与 AegisKV 的共享 Store、跨实例 KV 和磁盘/慢层恢复路径直接相关。该方案面向文档局部性及正常复用，未说明节点故障时副本隔离、一致提交和可恢复性。

#### [KVCache Cache in the Wild: Characterizing and Optimizing KVCache Cache at a Large Cloud Provider](2025/KVCache%20Cache%20in%20the%20Wild%3A%20Characterizing%20and%20Optimizing%20KVCache%20Cache%20at%20a%20Large%20Cloud%20Provider.pdf)
- 身份：published：USENIX ATC 2025 正式发表
- 简介：论文首次系统刻画大型云提供商生产 LLM 服务中的 KV 复用模式，发现复用跨请求呈偏斜、单轮与多轮都重要，按请求类别又具有一定可预测性，理想命中所需容量总体适中。基于这些观察，论文提出 workload-aware 淘汰策略。
- 与 AegisKV 的关系：它为 AegisKV 的现实 KV 复用分布、缓存容量敏感性和淘汰基线提供强实证依据。其目标是正常态命中率，未覆盖故障概率、保护副本收益或恢复正确性。

#### [DiffKV: Differentiated Memory Management for Large Language Models with Parallel KV Compaction](2025/DiffKV%3A%20Differentiated%20Memory%20Management%20for%20Large%20Language%20Models%20with%20Parallel%20KV%20Compaction.pdf)
- 身份：published：SOSP 2025 正式发表（DOI 10.1145/3731569.3764810）
- 简介：论文认为键/值、token 重要性及不同 attention head 的动态稀疏性不应被统一处理。DiffKV 据此差异化压缩 KV，并用 GPU 内并行内存整理把不规则稀疏造成的碎片压成连续空闲区。
- 与 AegisKV 的关系：它与 AegisKV 共享 KV 容量和碎片管理问题，压缩后可改变保护成本与可容纳副本数。但其近无损压缩不等同于故障恢复所需的精确副本，若结合必须显式建模精度和格式兼容性。

#### [Rethinking Key-Value Cache Compression Techniques for Large Language Model Serving](2025/Rethinking%20Key-Value%20Cache%20Compression%20Techniques%20for%20Large%20Language%20Model%20Serving.pdf)
- 身份：published：MLSys 2025 正式发表
- 简介：论文从生产部署视角复审 KV 压缩，指出只报告显存和整体准确率不够。实测发现现有内核/分页实现可能抹平吞吐收益，压缩还可能使输出变长并增加端到端延迟，且存在特定任务的负样本；论文据此提供分析与失败案例工具。
- 与 AegisKV 的关系：它对 AegisKV 很重要，因为压缩改变保护容量、传输量与重算成本，但也可能改变输出和运行时间。任何将压缩加入 AegisKV 的扩展都应联合评估可靠性、长度分布和真实内核，而非只缩放字节数。

#### [NEO: Saving GPU Memory Crisis with CPU Offloading for Online LLM Inference](2025/NEO%3A%20Saving%20GPU%20Memory%20Crisis%20with%20CPU%20Offloading%20for%20Online%20LLM%20Inference.pdf)
- 身份：published：MLSys 2025 正式发表
- 简介：论文通过把部分 attention 计算和 KV 状态卸载到本机 CPU 来扩大 GPU batch，而不是全量卸载。其非对称 GPU–CPU 流水和负载感知调度动态平衡两侧计算与内存资源，面向在线延迟约束。
- 与 AegisKV 的关系：它与 AegisKV 的 HBM 压力、主机层 KV 和传输/计算重叠相关，可作为无故障 CPU 卸载基线。AegisKV 的 Peer/Store 保护还需承担故障域与恢复可用性，不能仅按吞吐选择卸载。

#### [Marconi: Prefix Caching for the Era of Hybrid LLMs](2025/Marconi%3A%20Prefix%20Caching%20for%20the%20Era%20of%20Hybrid%20LLMs.pdf)
- 身份：published：MLSys 2025 正式发表
- 简介：论文处理 Attention 与 SSM 混合模型中 recurrent state 只能精确命中、无法回滚到部分前缀，导致大量低复用大缓存项的问题。Marconi 的准入/淘汰同时估计多种命中场景的复用概率及单位内存带来的计算节省。
- 与 AegisKV 的关系：它与 AegisKV 的收益—容量准入框架概念相近，尤其强调不能只看 recency。模型状态类型和失败语义不同；AegisKV 需基于 fail-now 恢复伤害而非一般命中收益。

#### [CacheBlend: Fast Large Language Model Serving for RAG with Cached Knowledge Fusion](2025/CacheBlend%3A%20Fast%20Large%20Language%20Model%20Serving%20for%20RAG%20with%20Cached%20Knowledge%20Fusion.pdf)
- 身份：published：EuroSys 2025 正式发表（DOI 10.1145/3689031.3696098）
- 简介：论文研究 RAG 输入由多个非前缀文本块组成时，如何组合其预计算 KV 而不明显损害生成质量。CacheBlend 复用各块 KV，仅选择性重算一小部分 token，并将重算与慢速存储读取流水化。
- 与 AegisKV 的关系：它与 AegisKV 都涉及分块 KV、慢层存储和传输/计算重叠；区别是 CacheBlend 解决跨上下文近似融合，AegisKV 面向故障时受约束的保护与精确恢复。可用于审视恢复路径上的 I/O 隐藏机会。

#### [Cache-Craft: Managing Chunk-Caches for Efficient Retrieval-Augmented Generation](2025/Cache-Craft%3A%20Managing%20Chunk-Caches%20for%20Efficient%20Retrieval-Augmented%20Generation.pdf)
- 身份：preprint：公开 arXiv 预印本（2502.15734v1）；PDF 明示 “Preprint, ArXiv, 2025”
- 简介：论文面向 RAG 中同一文档块在不同位置、不同前置上下文下反复出现却不能直接复用 KV 的问题。Cache-Craft 判断哪些 chunk-cache 可复用，只重算少量 token 修复上下文差异，并设计存储、淘汰及开销掩蔽机制。
- 与 AegisKV 的关系：其 chunk 级复用与 AegisKV 的分块缓存和多级存储相关，但目标是正常 RAG 重复计算消除，不提供故障保护副本或恢复语义。其选择性重算也提醒 AegisKV 区分“近似复用”与“可验证的精确恢复”。

#### [KVShare: An LLM Service System with Efficient and Effective Multi-Tenant KV Cache Reuse](2025/KVShare%20-%20An%20LLM%20Service%20System%20with%20Efficient%20and%20Effective%20Multi-Tenant%20KV%20Cache%20Reuse.pdf)
- 身份：preprint：公开 arXiv 预印本（2503.16525v2），PDF 明示 “Preprint. Under review.”
- 简介：论文在多租户请求间复用非严格同前缀的 KV，并处理新 token 导致的 attention deviation。KVShare 用自适应长度分块、prefill/decode 双阶段高偏差 token 重算，以及按 KV 命中率优先的连续批调度。
- 与 AegisKV 的关系：它与 AegisKV 的多租户分块、命中感知调度相关，但采用选择性重算维持近似准确度，语义不同于故障后精确状态恢复。可用于比较跨请求复用收益，不能作为可靠性保证。

#### [Locality-aware Fair Scheduling in LLM Serving](2025/Locality-aware%20Fair%20Scheduling%20in%20LLM%20Serving.pdf)
- 身份：preprint：公开 arXiv 预印本（2501.14312v1），未见正式出版信息
- 简介：论文研究 prefix locality 与多租户公平性的冲突，提出 DLPM 在有界公平性下放宽调度顺序以提高前缀命中。分布式 D2LPM 进一步在公平、局部性和负载均衡间做双重 deficit 协调。
- 与 AegisKV 的关系：它可作为 AegisKV 路由/调度中“复用优先是否伤害租户公平”的关键参照。论文不建模故障或保护占用，因此 AegisKV 还需单独验证故障恢复资源不会造成不公平挤占。

<a id="2025-serving"></a>
### LLM Serving 调度、内存与执行系统

这组工作提供通用推理调度、并行执行、attention、内存虚拟化和 PD 服务机制，用于校准 AegisKV 的正常态系统假设。

#### [Optimizing LLM Inference: Fluid-Guided Online Scheduling with Memory Constraints](2025/Optimizing%20LLM%20Inference%20-%20Fluid-Guided%20Online%20Scheduling%20with%20Memory%20Constraints.pdf)
- 身份：preprint：公开 arXiv 预印本（2504.11320v1），未见正式出版信息
- 简介：论文将 KV 随 decode 增长的 LLM 推理视为多阶段在线调度，以流体近似建立可处理的 benchmark。对已知输出长度提出 WAIT，对未知长度提出分层 Nested WAIT，并在重载极限下给出近最优分析。
- 与 AegisKV 的关系：它与 AegisKV 的流体资源模型、动态 HBM 约束和在线调度非常相关，可帮助设计解析基线。其“fluid”是排队/调度近似，不等于 AegisKV 对共享传输的流体带宽或故障恢复语义。

#### [Apt-Serve: Adaptive Request Scheduling on Hybrid Cache for Scalable LLM Inference Serving](2025/Apt-Serve%20-%20Adaptive%20Request%20Scheduling%20on%20Hybrid%20Cache%20for%20Scalable%20LLM%20Inference%20Serving.pdf)
- 身份：published：SIGMOD 2025 / PACM Management of Data 正式发表（DOI 10.1145/3725394）
- 简介：论文针对高负载下 TTFT SLO 达标率下降，指出 KV cache 占用限制批量规模、FCFS 又使批组成僵化。Apt-Serve 用 KV cache 与更省内存的 hidden cache 组成混合缓存，并以有理论保证的自适应调度动态优化批组成。
- 与 AegisKV 的关系：它直接关联 AegisKV 的 HBM 压力、缓存驻留和 SLO 感知调度，但关注正常服务扩容而非 GPU 故障后的冗余 KV 与恢复。可作为比较缓存占用—批处理—TTFT 权衡的基线。

#### [Online Scheduling for LLM Inference with KV Cache Constraints](2025/Online%20Scheduling%20for%20LLM%20Inference%20with%20KV%20Cache%20Constraints.pdf)
- 身份：preprint：公开 arXiv 预印本（2502.07115v4），未见正式出版信息
- 简介：论文建立受 KV 内存约束的在线 batching/scheduling 理论模型，以整数规划给出全未来信息下的最优基准，并证明任意到达下确定性在线算法无常数竞争比。随后提出多项式时间 MC-SF，并在条件下给出竞争性与模拟实证。
- 与 AegisKV 的关系：它为 AegisKV 的内存受限在线调度和“最优基准”设计提供理论参照。论文主要最小化正常推理延迟，不包含故障保护占用、恢复迁移或副本一致性。

#### [Context Parallelism for Scalable Million-Token Inference](2025/Context%20Parallelism%20for%20Scalable%20Million-Token%20Inference.pdf)
- 身份：published：MLSys 2025 正式发表
- 简介：论文把长上下文推理沿 context 维度扩展到多 GPU/多节点，提出精确无损的 pass-KV 与 pass-Q 环形注意力变体。它还针对多轮 prefill/decode 设计持久 KV 分片、负载均衡和算法选择启发式，在百万 token 上展示近线性扩展。
- 与 AegisKV 的关系：它为 AegisKV 的 TP/多节点 KV 分片、通信同步和长上下文 HBM 核算提供直接系统背景。论文不处理故障副本一致提交；AegisKV 在 TP 场景需额外保证各 rank 分片与版本元数据一致。

#### [vAttention: Dynamic Memory Management for Serving LLMs without PagedAttention](2025/vAttention%3A%20Dynamic%20Memory%20Management%20for%20Serving%20LLMs%20without%20PagedAttention.pdf)
- 身份：published：ASPLOS 2025 正式发表（DOI 10.1145/3669940.3707256）
- 简介：论文指出 PagedAttention 虽缓解 KV 物理碎片，却使虚拟地址不连续并增加内核改造与性能维护成本。vAttention 用 CUDA 虚拟内存 API 解耦虚拟/物理分配，在保持虚拟连续的同时按需映射物理页。
- 与 AegisKV 的关系：它与 AegisKV 的 HBM 账本、动态 KV 分配、连续尾部和物理守恒有关。vAttention 解决单机正常态内存映射，不提供跨 GPU 保护、故障 fencing 或恢复生命周期。

#### [POD-Attention: Unlocking Full Prefill-Decode Overlap for Faster LLM Inference](2025/POD-Attention%3A%20Unlocking%20Full%20Prefill-Decode%20Overlap%20for%20Faster%20LLM%20Inference.pdf)
- 身份：published：ASPLOS 2025 正式发表（DOI 10.1145/3676641.3715996）
- 简介：论文指出混合 batch 虽可叠加 prefill 与 decode 的线性算子，但现有 attention kernel 仍分开执行两阶段。POD-Attention 在同一 GPU multiprocessor 上并发安排两类 attention，联合利用计算与内存带宽。
- 与 AegisKV 的关系：它影响 AegisKV 对正常推理日历、prefill/decode 干扰和可隐藏传输窗口的性能假设，但不处理 KV 保护。若用于参数化模拟，应以相同硬件和 workload 校准，不能直接搬用峰值加速比。

#### [FlashInfer: Efficient and Customizable Attention Engine for LLM Inference Serving](2025/FlashInfer%3A%20Efficient%20and%20Customizable%20Attention%20Engine%20for%20LLM%20Inference%20Serving.pdf)
- 身份：published：MLSys 2025 正式发表
- 简介：论文提供可定制高性能 attention 引擎，以 block-sparse/可组合格式统一多样 KV 布局，通过 JIT 模板适配不同 attention 变体。其运行时调度处理动态序列长度并兼容要求静态配置的 CUDA Graph。
- 与 AegisKV 的关系：它是 AegisKV 模拟中 attention/KV 布局和性能参数的底层实现背景，而非保护策略。若 AegisKV 结果声称物理 GPU 性能，需要用此类内核实测校准；当前纯模拟不能据论文数据直接外推。

<a id="2025-peripheral"></a>
### 资源管理、可靠性与外围参考

这组工作从通用资源控制、语义可靠性、软错误或上下文处理侧提供外围背景，不与 AegisKV 的 fail-stop KV 恢复直接等价。

#### [Sherlock: Reliable and Efficient Agentic Workflow Execution](2025/Sherlock%3A%20Reliable%20and%20Efficient%20Agentic%20Workflow%20Execution.pdf)
- 身份：preprint：公开 arXiv 预印本（2511.00330v1），未见正式出版信息
- 简介：论文处理智能体工作流中早期错误向下游传播的问题，通过反事实故障注入识别高风险节点，并为其选择成本最优 verifier。运行时让下游任务在验证后台推测执行，验证失败则回滚到最近已验证输出。
- 与 AegisKV 的关系：它与 AegisKV 都使用工作流级故障影响和选择性保护思想，但 Sherlock 保护语义正确性、处理 LLM 输出错误；AegisKV 保护 KV 状态、处理硬件失效。其关键节点分析可启发保护优先级。

#### [CAIR: Counterfactual-based Agent Influence Ranker for Agentic AI Workflows](2025/CAIR%3A%20Counterfactual-based%20Agent%20Influence%20Ranker%20for%20Agentic%20AI%20Workflows.pdf)
- 身份：published：EMNLP 2025 正式发表（ACL 论文集页 18940–18966）
- 简介：论文解决多智能体工作流中无法量化各代理对最终输出影响的问题。CAIR 通过离线注入反事实代理输出估计影响，再在推理时快速预测代理影响排序，可服务于监控、护栏等下游机制。
- 与 AegisKV 的关系：它不研究 KV 系统，但其反事实影响排序与 AegisKV 的因果故障焦点选择、按工作流关键性分配保护资源在方法论上相近。不能直接作为 KV 故障恢复性能基线。

#### [ReaLM: Reliable and Efficient Large Language Model Inference with Statistical Algorithm-Based Fault Tolerance](2025/ReaLM%20-%20Reliable%20and%20Efficient%20Large%20Language%20Model%20Inference%20with%20Statistical%20Algorithm-Based%20Fault%20Tolerance.pdf)
- 身份：preprint：公开 arXiv 预印本（2503.24053v2）；正文给出名为 ReaLM_DAC25 的代码仓库，但所存 PDF 未提供足以确认正式出版的会议论文集信息
- 简介：论文研究加速器低压、老化等导致的计算位错误，先大规模注错刻画 LLM 各组件的容错差异，再提出统计型 ABFT，仅在错误统计超过适应性保护条件时恢复。配套轻量检测电路降低在线统计开销。
- 与 AegisKV 的关系：它与 AegisKV 同属 LLM 推理可靠性，但故障模型不同：ReaLM 处理可容忍的算术软错，AegisKV 处理 GPU fail-stop 与 KV 状态丢失。两者可互补，不能相互替代或直接比较恢复开销。

#### [RCR-Router: Efficient Role-Aware Context Routing for Multi-Agent LLM Systems with Structured Memory](2025/RCR-Router%20-%20Efficient%20Role-Aware%20Context%20Routing%20for%20Multi-Agent%20LLM%20Systems%20with%20Structured%20Memory.pdf)
- 身份：preprint：公开 arXiv 预印本（2508.04903v3）；PDF 虽带 AAAI 2025 版权标记，但未给出具体会议会次、论文集或页码，故不据此认定已正式发表
- 简介：论文针对多智能体系统把完整或静态上下文暴露给所有代理造成 token 浪费，按代理角色和任务阶段从结构化共享记忆中动态选择相关子集并施加 token budget。中间输出持续写回共享记忆以迭代细化上下文。
- 与 AegisKV 的关系：它减少上下文长度，从源头改变 AegisKV 的 KV 规模、共享结构和故障恢复成本。它是语义级 context routing，不提供物理 KV 副本或恢复机制。

#### [FleetIO: Managing Multi-Tenant Cloud Storage with Multi-Agent Reinforcement Learning](2025/FleetIO%20-%20Managing%20Multi-Tenant%20Cloud%20Storage%20with%20Multi-Agent%20Reinforcement%20Learning.pdf)
- 身份：published：ASPLOS 2025 正式发表（DOI 10.1145/3669940.3707229）
- 简介：论文研究多租户共享 SSD 中性能隔离与利用率的长期矛盾。FleetIO 用多智能体强化学习按运行时 I/O 轨迹聚类工作负载、调整奖励，并动态细粒度收割存储资源，在可编程 SSD 上联合改善利用率与尾延迟。
- 与 AegisKV 的关系：它不研究 LLM KV，但与 AegisKV 的共享 Store/SSD 层、租户隔离和 SLO 感知资源控制有关。其 RL 控制方式不能直接证明 AegisKV 确定性准入策略的正确性，只可作为存储资源管理的旁证。

#### [Optimizing LLM Queries in Relational Data Analytics Workloads](2025/Optimizing%20LLM%20Queries%20in%20Relational%20Data%20Analytics%20Workloads.pdf)
- 身份：published：MLSys 2025 正式发表
- 简介：论文针对关系数据上的批量 LLM 查询，通过重排行和每行字段来最大化 prefix KV 命中。它提出精确但指数复杂的 OPHR，以及利用函数依赖和统计信息缩小搜索空间的近似 GGR，并保持查询语义。
- 与 AegisKV 的关系：它说明上游工作负载重排可显著改变 AegisKV 所观察到的前缀局部性和保护价值。其离线全局可见假设与 AegisKV 在线故障场景不同，适合作为 workload shaping 的互补方向。

## 2026（64 篇）

本年收录：故障容错、检查点与恢复 11 篇；Agentic Workflow 与工作流调度 16 篇；KV Cache 管理、复用与分层存储 32 篇；LLM Serving 调度、内存与执行系统 4 篇；资源管理、可靠性与外围参考 1 篇。

本年主题：[故障容错](#2026-failure) · [工作流](#2026-workflow) · [KV Cache](#2026-kv) · [Serving](#2026-serving) · [外围参考](#2026-peripheral)

<a id="2026-failure"></a>
### 故障容错、检查点与恢复

这组工作直接讨论 fail-stop、KV 状态保护、检查点、重建与恢复路径，是 AegisKV 的核心基线与机制参照。

#### [LUMEN: Coordinated Failure Recovery for Distributed LLM Serving](2026/LUMEN%3A%20Coordinated%20Failure%20Recovery%20for%20Distributed%20LLM%20Serving.pdf)
- 身份：arXiv 预印本，arXiv:2606.17787v1；首页未给出正式发表信息。
- 简介：LUMEN 将分布式 LLM 服务的 worker 故障恢复拆为故障前 KV 检查点放置、故障时中断请求分发和模型重载期间容量恢复三个协同决策。它采用负载感知检查点、局部性感知恢复调度及草稿模型辅助的渐进恢复，并以 SGLang 原型和 Vidur 大规模模拟评估。
- 与 AegisKV 的关系：LUMEN 与 AegisKV 在故障、KV 检查点、请求重路由和恢复期间集群压力方面最为直接相关，是算法与实验设计的重要对照；其原型加模拟证据也适合用于校准 AegisKV 当前纯模拟边界。

#### [RaidServe: High-Performance Resilient Serving](2026/RaidServe%3A%20High-performance%20Resilient%20Serving.pdf)
- 身份：正式发表：MLSys 2026；该工作此前以 FailSafe 名称作为 arXiv:2511.14116 预印本流传，本地 PDF 的旧会议年份行属于未更新的版本信息。
- 简介：RaidServe 面向 tensor-parallel 服务中的不规则 GPU 可用性，使用循环 KV 放置、混合 attention 和细粒度负载路由缓解故障后的计算与内存失衡。它通过主动 KV 备份和按需权重恢复避免完整重算，论文报告在 8×H100 上将恢复延迟降低最多两个数量级并在多卡故障下维持吞吐。
- 与 AegisKV 的关系：这是与 AegisKV 最直接的容错基线之一，尤其适合比较 KV 备份方式、恢复流量、恢复延迟和降级运行能力。其设计与 TP 内部非规则并行重构紧密耦合，和更一般的 KV 存储/迁移容错需分别比较。

#### [Towards Resiliency in Large Language Model Serving with KevlarFlow](2026/Towards%20Resiliency%20in%20Large%20Language%20Model%20Serving%20with%20KevlarFlow.pdf)
- 身份：预印本（文内明确标注 “Preprint. February 2, 2026”，同时为 arXiv:2601.22438v1）；首页未标示正式发表 venue。
- 简介：KevlarFlow 通过解耦模型并行初始化、动态流量重路由和后台 KV cache 复制，使部分节点失效时健康资源仍可继续服务，并让进行中的请求在存活节点上延续。论文报告将节点故障 MTTR 从约 10 分钟降至 30 秒，并在所测故障条件下显著改善延迟和 TTFT，且声称正常运行开销可忽略。
- 与 AegisKV 的关系：这是范围内与 AegisKV 最直接的对比工作之一，因为两者都在故障前复制 KV 状态、故障后迁移/恢复请求。KevlarFlow 是实现并实测的服务架构，而 AegisKV 当前是未物理校准、最高 E2 的模拟证据；比较时应区分运行时复制策略、故障域和证据类型。

#### [GhostServe: A Lightweight Checkpointing System in the Shadow for Fault-Tolerant LLM Serving](2026/GhostServe%3A%20A%20Lightweight%20Checkpointing%20System%20in%20the%20Shadow%20for%20Fault-Tolerant%20LLM%20Serving.pdf)
- 身份：正式会议论文；首页标明发表于 MLSys 2026。
- 简介：GhostServe 面向长上下文和智能体任务中的 LLM 服务故障，用纠删码为持续增长的 KV cache 生成冗余分片，并将其保存在主机内存。设备故障后，系统可重建丢失的 KV cache 并继续推理，避免完整重算或全量复制；论文报告了检查点与恢复延迟方面的原型评测收益。
- 与 AegisKV 的关系：它与 AegisKV 同样直接研究故障后的 KV 状态保护和恢复，是检查点编码、恢复成本与故障影响建模的重要对照；其真实系统结果也可用于界定 AegisKV 当前模拟证据尚未覆盖的实现层面。

#### [Making MoE-based LLM Inference Resilient with TARRAGON](2026/Tarragon%20-%20Making%20MoE-based%20LLM%20Inference%20Resilient.pdf)
- 身份：arXiv 预印本（arXiv:2601.01310v2，2026-01-06）；首页未标示正式发表 venue。
- 简介：TARRAGON 面向解耦注意力与专家计算的 MoE 推理，把注意力工作器和专家工作器划为独立故障域，并通过可重配置数据路径将流量绕开失效工作器。它针对有状态注意力侧使用异步增量 KV cache 检查点和逐请求恢复，针对无状态专家侧利用残余显存部署 shadow experts；文中报告相对 MegaScale-Infer 将故障停顿从约 64 秒降至 0.3–0.4 秒。
- 与 AegisKV 的关系：这是直接相关的故障恢复系统：两者都利用 KV 状态保护来减少推理故障后的回滚与重算。TARRAGON 专注 MoE 的注意力/专家故障域和在线恢复，而 AegisKV 的当前证据是对 Peer-HBM/Store 保护、恢复资格与失败计划的确定性事件模拟，系统边界和证据层级不同。

#### [Concordia: JIT-Compiled Persistent-Kernel Checkpointing for Fault-Tolerant LLM Inference](2026/Concordia%3A%20JIT-Compiled%20Persistent-Kernel%20Checkpointing%20for%20Fault-Tolerant%20LLM%20Inference.pdf)
- 身份：arXiv 预印本（arXiv:2606.23521v1）；PDF 中 ACM 引用信息的 DOI/会议信息仍为占位符，不能据此认定正式发表。
- 简介：Concordia 以设备常驻 persistent kernel 作为 LLM 推理容错底座，在 PTX/SASS 层插入检查点与暂停钩子，并为 KV 块等状态 JIT 编译增量检查点处理器。它在 GPU 上检测脏页，将已提交增量追加到 CPU 可见日志，并据此恢复服务。
- 与 AegisKV 的关系：这是直接的 GPU 状态检查点与恢复机制，可与 AegisKV 的故障注入、检查点开销、可恢复 KV 比例及恢复时间模型逐项对照。

#### [CacheFlow: Efficient LLM Serving with 3D-Parallel KV Cache Restoration](2026/CacheFlow%3A%20Efficient%20LLM%20Serving%20with%203D-Parallel%20KV%20Cache%20Restoration.pdf)
- 身份：明确标注为 Preprint 的 arXiv 预印本（arXiv:2604.25080v1）。
- 简介：CacheFlow 将 KV 恢复分解为 token、层和 GPU 三个维度的并行执行，并在批处理条件下联合分配计算与 I/O。其调度器根据降低重算成本的边际收益协调多个请求，以缓解资源竞争和拖尾。
- 与 AegisKV 的关系：它直接定义了 KV 恢复的多维并行与批量资源竞争模型，是 AegisKV 模拟恢复路径、TTFT 和计算/I/O重叠时的关键相关工作。

#### [AnchorTP: Resilient LLM Inference with State-Preserving Elastic Tensor Parallelism](2026/AnchorTP%3A%20Resilient%20LLM%20Inference%20with%20State-Preserving%20Elastic%20Tensor%20Parallelism.pdf)
- 身份：arXiv 预印本（arXiv:2511.11617v1，PDF 标注日期为 2025 年）。
- 简介：AnchorTP 在 GPU 故障或链路退化后，以不等宽弹性张量并行重组服务，并通过独立 daemon 保留幸存 GPU 上的模型参数和 KV 缓存。其带宽感知迁移规划器尽量减少从主机重载的数据量，并流水化 P2P 迁移与重载。
- 与 AegisKV 的关系：这是与 AegisKV 高度直接的状态保留式故障恢复方案，可用于比较恢复时间、KV 保留比例、迁移量和弹性并行重构假设。

#### [ReviveMoE: Fast Recovery for Hardware Failures in Large-Scale MoE LLM Inference Deployments](2026/ReviveMoE%3A%20Fast%20Recovery%20for%20Hardware%20Failures%20in%20Large-Scale%20MoE%20LLM%20Inference%20Deployments.pdf)
- 身份：arXiv 预印本（arXiv:2602.21140v1，2026-02-24），内容描述 Huawei Cloud 内部系统实现与部署。
- 简介：ReviveMoE 面向大规模 MoE 推理，在不重启整个 serving instance 的情况下隔离故障、迁移活跃序列、用日志恢复 block table，并重建通信域和计算图。论文称在 xDeepServe/Ascend 环境中把典型恢复时间从 83.1 秒降至 10.2 秒，同时利用 DP 与冗余专家减少权重重载。
- 与 AegisKV 的关系：ReviveMoE 是故障恢复的直接对照，尤其覆盖序列状态、block table、通信和权重的联合恢复。AegisKV 可与其比较 KV 专属恢复机制的通用性、恢复粒度及对不同并行架构和硬件的依赖。

#### [LLM KV-cache: To Restore or To Recompute, That Is the Question](2026/LLM%20KV-cache%20-%20To%20Restore%20or%20To%20Recompute%2C%20That%20Is%20the%20Question.pdf)
- 身份：本地匿名投稿稿；首页明确标为 “ACM HotStorage 2026 Anonymous Submission #9”，其中 DOI、ISBN 等为占位内容，不能视为已正式发表。
- 简介：论文研究 KV cache 被驱逐到 DRAM、本地或远端存储后，应恢复还是在 GPU 上重算的动态选择问题。它提出 I/O 感知策略，根据 GPU、存储层性能和 SLO 按块决策，并给出模拟器上的初步理论结果。
- 与 AegisKV 的关系：该问题与 AegisKV 的故障后恢复/重算选择直接重合，可作为恢复策略和分层存储成本的近邻基线；其证据同样主要来自模型或模拟，而非完整生产部署。

#### [From Detection to Recovery: Operational Analysis on LLM Pre-training with 504 GPUs](2026/From%20Detection%20to%20Recovery%3A%20Operational%20Analysis%20on%20LLM%20Pre-training%20with%20504%20GPUs.pdf)
- 身份：Lablup Technical Report；同时发布为 arXiv 技术报告（arXiv:2605.09370v5）。
- 简介：报告基于 63 节点、504 张 B200 GPU 的生产训练集群监控与运维日志，分析故障前兆、检查点 I/O、节点排除和自动重试链。其证据显示故障类型需要多信号检测，恢复加载和检查点写入受存储路径与排队影响，并量化了自动重试的成功率和间隔。
- 与 AegisKV 的关系：虽然对象是预训练而非推理 KV，报告提供了大规模真实故障、检测、存储瓶颈和恢复链数据，可用于校准 AegisKV 故障分布与恢复基础设施假设。

<a id="2026-workflow"></a>
### Agentic Workflow 与工作流调度

这组工作以 agent 程序或工作流 DAG 为调度对象，为 AegisKV 的关键路径、slack、JCT 和工具调用连续性建模提供参照。

#### [TOPAS: Workflow-Aware Prefix-State Scheduling for Multi-Agent LLM Serving](2026/TOPAS%3A%20Workflow-Aware%20Prefix-State%20Scheduling%20for%20Multi-Agent%20LLM%20Serving.pdf)
- 身份：arXiv 预印本（arXiv:2608.25523v1，2026-08-26）；首页未标示正式发表 venue。
- 简介：TOPAS 研究共享 KV 预算下多 agent 工作流中的 prefix residency 与请求准入联合决策，平衡长前缀复用、批处理容量和任务级关键路径进展。它在 SGLang 中实现分层状态搜索、面向 JCT 的效用函数及防饥饿 aging；论文报告在合成 DAG 上最高降低 mean/p99 JCT 39.8%/49.4%，并在两类 MetaGPT 工作流上取得较小但稳定的改善。
- 与 AegisKV 的关系：TOPAS 处理的是无故障条件下前缀状态的保留和调度，AegisKV 处理的是故障前保护布局与故障后恢复。其“驻留前缀占用会压缩批容量”的权衡可用于约束 AegisKV 保护副本的 HBM 压力和恢复收益建模。

#### [HEXAGENT: Efficient Agentic LLM Serving via Workflow- and Heterogeneity-Aware Scheduling](2026/HexAGenT%3A%20Efficient%20Agentic%20LLM%20Serving%20via%20Workflow-%20and%20Heterogeneity-Aware%20Scheduling.pdf)
- 身份：arXiv 预印本，arXiv:2605.16637v1；首页未给出正式发表信息。
- 简介：HEXAGENT 将在线逐步显露的智能体工作流表示为 DAG，面向异构、prefill-decode 解耦集群联合决定 prefill 放置、decode 放置和本地队列优先级。它以工作流级完成时限和违约风险为调度信号，并显式考虑 KV 容量及跨阶段传输开销。
- 与 AegisKV 的关系：该文可为 AegisKV 的工作流并发、异构部署和 KV 容量压力建模提供相邻调度基线，但重点是正常运行时的工作流 SLO，而不是故障恢复。

#### [SAGA: Workflow-Atomic Scheduling for AI Agent Inference on GPU Clusters](2026/SAGA%20-%20Workflow-Atomic%20Scheduling%20for%20AI%20Agent%20Inference%20on%20GPU%20Clusters.pdf)
- 身份：arXiv 预印本（arXiv:2605.00528v2，2026-06-19）。
- 简介：SAGA 主张把整个代理工作流而非单次 LLM 调用作为调度单位，以 Agent Execution Graph 预测工具调用间的 KV 复用，并结合 session-affinity batching、work stealing 和任务级公平性。论文报告在 64-GPU 的 SWE-bench 与 WebArena 工作负载上缩短任务完成时间，但也明确量化了相对吞吐最优调度约 30% 的峰值吞吐代价。
- 与 AegisKV 的关系：SAGA 可向 AegisKV 提供工作流级 KV 连续性、关键会话和任务完成时间目标，用于制定故障保护与恢复优先级。其端到端代理指标也可补充仅看 TTFT/TPOT 的容错评估。

#### [MARS: Efficient, Adaptive Co-Scheduling for Heterogeneous Agentic Systems](2026/MARS%3A%20Efficient%2C%20Adaptive%20Co-Scheduling%20for%20Heterogeneous%20Agentic%20Systems.pdf)
- 身份：arXiv 预印本，arXiv:2604.26963v2；首页未给出正式发表信息。
- 简介：MARS 联合调度智能体工作负载中的 GPU 推理和 CPU 工具执行，通过统一信息流和外部控制面避免异构资源过载。其内部调度器优先保障关键路径上的续执行，并仅在热恢复确有延迟收益时保留 KV cache，作者还将其接入 OpenHands 进行端到端评测。
- 与 AegisKV 的关系：MARS 对工具暂停期间 KV 留存/驱逐、工作流关键路径和 GPU-CPU 耦合的处理可丰富 AegisKV 的智能体负载模型；它的“恢复”指会话热续执行，而非硬件故障恢复。

#### [Pythia: Exploiting Workflow Predictability for Efficient Agent-Native LLM Serving](2026/Pythia%3A%20Exploiting%20Workflow%20Predictability%20for%20Efficient%20Agent-Native%20LLM%20Serving.pdf)
- 身份：arXiv 预印本（arXiv:2604.25899v2，2026-05-14）。
- 简介：Pythia 利用多代理工作流的拓扑和角色语义，预测请求传播、前缀复用、资源需求与突发负载，而不是把代理调用视为一般黑盒流量。论文基于生产轨迹指出低缓存命中、长上下文竞争和反应式扩缩容的局限，并据此设计工作流感知服务优化。
- 与 AegisKV 的关系：Pythia 的工作流可预测性可为 AegisKV 提供未来 KV 使用概率和关键路径信息，用于选择备份、保留和优先恢复对象；其本身没有以硬件故障恢复为主要目标。

#### [ThunderAgent: A Simple, Fast and Program-Aware Agentic Inference System](2026/ThunderAgent%3A%20A%20Simple%2C%20Fast%20and%20Program-Aware%20Agentic%20Inference%20System.pdf)
- 身份：arXiv 预印本（arXiv:2602.13692v3，2026-06-30）；首页未标示正式发表 venue。
- 简介：ThunderAgent 将跨多次 LLM 调用与工具执行的 agent 工作流抽象为持久的“LLM Program”，统一跟踪 KV cache、程序状态和工具资源。其程序感知调度器在内存压力下协调暂停、KV 保留/驱逐和跨数据并行节点迁移，工具资源管理器则异步准备并回收执行环境；论文报告服务吞吐提升 1.5–3.6 倍、RL rollout 吞吐提升 1.8–3.9 倍。
- 与 AegisKV 的关系：它为 AegisKV 提供了很相关的 agentic 工作负载与 KV 驱逐/重算压力模型，但核心目标是正常运行时的吞吐和资源生命周期管理，而非硬件故障后的 KV 保护与恢复。AegisKV 可把这类多轮工具间隙和跨节点不平衡作为故障恢复评估的补充场景。

#### [Efficient Serving for Agentic LLM Workflows via Micro-Task-Level Parallelism](2026/Efficient%20Serving%20for%20Agentic%20LLM%20Workflows%20via%20Micro-Task-Level%20Parallelism.pdf)
- 身份：本地论文稿；可读首页未标注 arXiv 编号、正式 venue 或“保密/匿名投稿”，因此不推断发表状态。
- 简介：论文提出 Grape，以 TaskFlow 表达 agentic 工作流并将任务拆分为微任务，暴露原本被任务边界遮蔽的并行性。其微任务调度器以 SLO 约束组织执行，内存管理器则根据执行关键路径抢占 KV 缓存以缓解并发带来的压力。
- 与 AegisKV 的关系：Grape 的细粒度依赖图和 KV 抢占机制可用于构造 AegisKV 的并发工作流场景；AegisKV 还需单独建模故障导致的状态丢失和恢复。

#### [FATE: Future-State-Aware Scheduling for Heterogeneous LLM Workflows](2026/FATE%3A%20Future-State-Aware%20Scheduling%20for%20Heterogeneous%20LLM%20Workflows.pdf)
- 身份：明确标注为 Preprint 的 arXiv 预印本（arXiv:2605.07238v1）。
- 简介：FATE 调度异构 LLM 工作流 DAG 时，不仅考虑当前队列和放置成本，还预测决策对模型驻留、父输出局部性、前缀复用和后续设备可达性的影响。它以 CP-SAT 支持的有限前视规划反复处理当前 ready frontier，并只提交当前阶段决策。
- 与 AegisKV 的关系：其“未来状态保留”目标与故障后 KV/模型状态连续性密切相关，可作为 AegisKV 的状态感知调度对照；论文实验本身不等同于故障恢复研究。

#### [Maestro: Workload-Aware Cross-Cluster Scheduling for LLM-Based Multi-Agent Systems](2026/Maestro%3A%20Workload-Aware%20Cross-Cluster%20Scheduling%20for%20LLM-Based%20Multi-Agent%20Systems.pdf)
- 身份：arXiv 预印本，arXiv:2606.12950v1；首页未给出正式发表信息。
- 简介：Maestro 面向 GPU 预算受限的多集群 LLM 多智能体服务，用智能体语义预测各阶段输出长度、运行时间和 KV 内存需求。其分层调度器联合处理节点内多模型共置、集群间路由和工作流级优先级，以降低冷启动、内存过量预留和队首阻塞。
- 与 AegisKV 的关系：它可为 AegisKV 的工作流并发、KV 预留、跨节点路由与异构资源压力提供调度侧参照；论文并未把故障恢复作为核心问题。

#### [Agentix: An Efficient Serving Engine for LLM Agents as General Programs](2026/Agentix%3A%20An%20Efficient%20Serving%20Engine%20for%20LLM%20Agents%20as%20General%20Programs.pdf)
- 身份：正式会议论文，收录于 USENIX NSDI 2026 会议论文集。
- 简介：Agentix 将由多次 LLM 调用和外部中断组成的动态 agent 程序视为一等调度对象。它利用程序级上下文进行抢占和优先级调度，以降低单次调用及整个程序的队首阻塞和累计等待时间。
- 与 AegisKV 的关系：Agentix 给出了工作流级调度基线和端到端程序延迟指标；AegisKV 可进一步研究故障及 KV 状态丢失/复用如何改变这类调度结果。

#### [Efficient LLM Serving for Agentic Workflows: A Data Systems Perspective (Extended)](2026/Efficient%20LLM%20Serving%20for%20Agentic%20Workflows%3A%20A%20Data%20Systems%20Perspective.pdf)
- 身份：arXiv 预印本（arXiv:2603.16104v1），标题明确标注为扩展版本。
- 简介：论文提出 Helium，将 agentic 工作流建模为查询计划、将 LLM 调用视为一等算子，并跨调用与跨工作流主动缓存提示、KV 状态和结果。它结合缓存感知调度，强调端到端工作流优化而非孤立调用优化。
- 与 AegisKV 的关系：Helium 的工作流 DAG、跨调用 KV 复用和缓存感知调度可作为 AegisKV 工作负载与无故障基线；其摘要未主张处理故障恢复。

#### [Ceres: Low-latency Multi-Agent Serving with Shared LLMs via Perceiving Differences across Agents](2026/Ceres%20-%20Low-latency%20Multi-Agent%20Serving%20with%20Shared%20LLMs%20via%20Perceiving%20Differences%20across%20Agents.pdf)
- 身份：本地匿名/保密投稿稿件；首页标注“ICS 2026 Submission #24 – Confidential Draft – Do NOT Distribute”，并含占位 DOI/ISBN。
- 简介：Ceres 面向多个 agent 共享同一 LLM 的服务场景，以工作流感知的优先级调度降低整体排队时间，并按请求内存需求进行时隙分派以避免 GPU 过载。其目标是降低多 agent 应用的端到端延迟。
- 与 AegisKV 的关系：它可提供共享 LLM 工作流、内存压力和调度策略的比较对象；AegisKV 则可补充故障、KV 状态保存和恢复过程对这些指标的影响。

#### [NALAR: A Serving Framework for Agent Workflows](2026/Nalar%3A%20A%20Serving%20Framework%20for%20Agent%20Workflows.pdf)
- 身份：arXiv 预印本（arXiv:2601.05109v1，2026-01-08）。
- 简介：NALAR 将代理工作流的规格与执行分离，用自动生成的轻量 stub 把代理和工具调用表示为携带依赖与上下文元数据的 future。其托管状态层和全局策略/本地事件执行的两级控制架构支持状态复用、迁移、重试以及动态路由和调度；摘要报告在三个代理工作负载上降低尾延迟并扩展到大量 future。
- 与 AegisKV 的关系：NALAR 从工作流运行时角度提供状态连续性和重试语义，可作为 AegisKV 面向故障时 KV 状态保护与恢复机制的上层互补系统，也可提供代理工作负载与调度场景。

#### [Weaver: Efficient Agentic Workflow Serving via Dependency-Aware Overlap and Prefill Co-location](2026/Weaver%20-%20Efficient%20Agentic%20Workflow%20Serving%20via%20Dependency-Aware%20Overlap%20and%20Prefill%20Co-location.pdf)
- 身份：本地匿名稿/未标明发表状态的论文稿；首页无作者、单位、arXiv 编号或 venue，正文参考文献仍有访问日期占位内容，因此不能据此认定为正式论文。
- 简介：Weaver 针对多阶段 agentic 工作流，将上游逐 token decode 与下游增量 prefill 做依赖正确的流水重叠，并把多个阶段的 prefill 共置在共享 GPU 上。系统以依赖感知执行器、争用感知部署器和 headroom-aware 调度器控制共置干扰；文中报告端到端延迟最高降低 37.1%、满足 SLO 的峰值吞吐最高提高 39.1%。
- 与 AegisKV 的关系：Weaver 主要优化无故障工作流的阶段依赖、prefill/decode 重叠和 GPU 配置，不提供 KV 故障恢复机制。其多阶段依赖和共置争用可作为 AegisKV 评估故障影响传播、恢复流量与正常计算竞争时的工作负载背景。

#### [Maze: A Distributed Framework for Large Language Model Agents](2026/Maze.pdf)
- 身份：本地稿件；首页未列作者、arXiv 标识或正式出版信息，也未明确标注已录用，故不推断 venue 或保密状态。
- 简介：Maze 将智能体逻辑编译为带资源语义的细粒度任务 DAG，并通过异构感知的关键度调度减少 GPU、CPU 和 I/O 队列之间的队首阻塞。框架还结合弹性推理引擎扩缩容、零显存待机、DAG 感知上下文管理及闭环容错，以支持多租户智能体服务。
- 与 AegisKV 的关系：Maze 在 DAG 感知 KV 复用、弹性调度和智能体级容错方面与 AegisKV 邻近，但论文首页和摘要未表明其容错机制专注于 KV 状态恢复，因此不应视作直接同类方案。

#### [AAFLOW: Scalable Patterns for Agentic AI Workflows](2026/AAFLOW%20-%20Scalable%20Patterns%20for%20Agentic%20AI%20Workflows.pdf)
- 身份：arXiv 预印本（arXiv:2605.02162v1）。
- 简介：AAFLOW 将检索、嵌入、推理、记忆和索引更新建模为可编译的分布式算子，并以 Apache Arrow/Cylon 构建零拷贝数据平面。其性能收益主要来自数据流、批处理和通信优化，而非加速 LLM 内核本身。
- 与 AegisKV 的关系：它提供了 agentic 工作流结构与跨阶段状态流动的上层背景，可用于构造 AegisKV 的工作流负载；但论文重点不是 KV 缓存容错或恢复。

<a id="2026-kv"></a>
### KV Cache 管理、复用与分层存储

这组工作覆盖 KV 的复用、放置、驱逐、压缩、路由及跨 HBM/DRAM/SSD/CXL 层流动，为 AegisKV 的容量与传输权衡提供基线。2026 年本组 32 篇，按下述子类排列，更接近 AegisKV 存储与恢复建模的子类在前。

本组子类：[分层存储](#2026-kv-store) · [Offload 与预取](#2026-kv-offload) · [亲和路由](#2026-kv-route) · [压缩与复用](#2026-kv-reuse)

<a id="2026-kv-store"></a>
**分层存储、解耦与一致性（11）**

#### [Strata: Hierarchical Context Caching for Long Context Language Model Serving](2026/Strata%3A%20Hierarchical%20Context%20Caching%20for%20Long%20Context%20Language%20Model%20Serving.pdf)
- 身份：正式会议论文，USENIX OSDI 2026 论文集收录。
- 简介：Strata 为长上下文服务构建跨 GPU HBM、CPU 内存和 SSD 的分层 context cache，针对碎片化布局、小传输、cache loading stall 和 delay hit 问题设计 GPU-assisted I/O 与 cache-aware scheduler。论文称其已集成进 SGLang 并部署于生产，且相对所选分层缓存基线提高吞吐。
- 与 AegisKV 的关系：Strata 是 AegisKV 多层 KV 存储与 I/O 调度的重要性能基线，也暴露了故障恢复可能面对的碎片化和并发加载问题。AegisKV 可在其层级布局上比较副本放置、恢复优先级与恢复流量。

#### [SYMPHONY: Enabling Compute-Memory Disaggregation in LLM Serving Systems](2026/SYMPHONY%3A%20Enabling%20Compute-Memory%20Disaggregation%20in%20LLM%20Serving%20Systems.pdf)
- 身份：正式会议论文，USENIX NSDI 2026 论文集收录。
- 简介：SYMPHONY 将计算与 KV cache 存储解耦，通过来自用户交互或工作负载结构的 advisory request 提前预取状态，并支持请求级负载均衡。为应对预测不可靠，它采用优先级式 KV 管理和与 serving framework 协作的 GPU 内存管理；论文报告在 ShareGPT 和 BurstGPT 上降低端到端延迟并提高承载量。
- 与 AegisKV 的关系：SYMPHONY 是分离式 KV 存储和预取的直接系统基线，其远端状态层也适合作为 AegisKV 的故障域与恢复来源。AegisKV 需要进一步处理该架构下存储节点、计算节点和传输路径故障时的状态可用性与一致性。

#### [Tutti: Making SSD-Backed KV Cache Practical for Long-Context LLM Serving](2026/Tutti%3A%20Making%20SSD-Backed%20KV%20Cache%20Practical%20for%20Long-Context%20LLM%20Serving.pdf)
- 身份：arXiv 预印本（arXiv:2605.03375v1，2026-05-05）；首页未标示正式发表 venue。
- 简介：Tutti 提出 GPU-centric 的 HBM–SSD KV cache 对象存储，把 CPU 移出关键数据与 I/O 控制路径，并用 GPU-native 对象抽象、GPU io_uring 和 slack-aware I/O 调度提升 SSD 恢复效率。其 vLLM 原型相对启用 GDS 的 SSD-backed LMCache 报告 TTFT 降低 78.3%、可承载请求率提升 2 倍，性能接近 DRAM-backed 方案。
- 与 AegisKV 的关系：Tutti 不是故障容错系统，但直接涉及从低层存储恢复 KV 的传输、排队和 GPU 停顿成本，可为 AegisKV 的 Store 恢复路径提供实现侧参照。AegisKV 还需单独处理故障一致性、兼容性校验和恢复资格，不能把 Tutti 的正常缓存命中结果等同于故障恢复证据。

#### [KVDrive: A Holistic Multi-Tier KV Cache Management System for Long-Context LLM Inference](2026/KVDrive%3A%20A%20Holistic%20Multi-Tier%20KV%20Cache%20Management%20System%20for%20Long-Context%20LLM%20Inference.pdf)
- 身份：arXiv 预印本，arXiv:2605.18071v1；首页 ACM 引用信息仍为占位符，不能据此认定正式发表。
- 简介：KVDrive 联合管理 GPU HBM、主机 DRAM 和 SSD 中的长上下文 KV cache，以注意力感知的缓存复用、选择/取数/计算流水化及跨层协同减少数据移动和停顿。论文实现了可运行原型，并报告在保持精度时相对既有方案的吞吐收益。
- 与 AegisKV 的关系：该文与 AegisKV 的多层 KV 放置、驱逐、传输和 Store 节点建模高度相关，可作为无故障情况下的存储层基线；其核心目标不是失效后的状态重建。

#### [A CXL Memory Rack for Multi-Turn LLM Serving](2026/HyMCache%3A%20A%20KV%20Cache%20Framework%20for%20Multi-Turn%20LLM%20Serving%20with%20CXL-Hybrid%20Memory.pdf)
- 身份：arXiv 预印本，arXiv:2607.18141v3；文件名使用 HyMCache，但首页论文题目为 “A CXL Memory Rack for Multi-Turn LLM Serving”。
- 简介：HyMCache 使用带少量设备 DRAM 和大容量 SSD 后端的 CXL 混合内存构建共享 KV cache 机架，服务多轮及智能体上下文复用。它利用访问的读多写少、可预测和追加式特征，以请求级前缀预取和机会式写缓冲在较低成本下提供大容量 KV 复用。
- 与 AegisKV 的关系：该文为 AegisKV 的 Store/远端 KV 层、跨节点传输和多层介质成本提供直接相关的系统设计参照，但不处理 GPU 故障后的协调恢复。

#### [ITME: Inference Tiered Memory Expansion with Disaggregated CXL-Hybrid Memories](2026/ITME%3A%20Inference%20Tiered%20Memory%20Expansion%20with%20Disaggregated%20CXL-Hybrid%20Memories.pdf)
- 身份：arXiv 预印本，arXiv:2606.12556v2；首页未给出正式发表信息。
- 简介：ITME 以解耦的 CXL 混合内存提供 TB 级、字节可寻址的远端内存扩展，用于容纳模型权重和长上下文 KV cache。其多级 DMA 预取流水线协调 SSD、设备 DRAM、主机和 GPU 之间的数据移动，并以硬件原型及生产级部件评估可行性。
- 与 AegisKV 的关系：ITME 对 AegisKV 的多层 KV 存储、远端扩展和传输流水线建模有参考价值；它主要解决容量与性能，不提供故障恢复算法。

#### [Position: Disaggregated LLM KV-Cache Storage Requires Coordination-Free Consistency Abstractions](2026/Position%20-%20Disaggregated%20LLM%20KV-Cache%20Storage%20Requires%20Coordination-Free%20Consistency%20Abstractions.pdf)
- 身份：本地匿名稿；版面声称对应 HotStorage 2026，但作者为 “Anonymous Author(s)”，不据此视为可核验的正式发表版本。
- 简介：该立场论文把分离式 KV cache 视为带模型语义约束的分布式存储，强调“数据存在”不等于“可安全复用”。它以 CALM 定理分析 LMCache、Mooncake 和 vLLM 操作的单调性，主张 admission 可无协调，而 eviction、compaction、恢复等操作需要明确协调边界；文中也明确将部分竞态列为预测而非已复现实证。
- 与 AegisKV 的关系：这篇稿件直接提醒 AegisKV 在故障恢复和副本复用时验证前缀闭包、位置、模型版本等语义不变量，而不能只检查 KV 字节是否可达。其分析可用于审视 AegisKV 恢复协议的一致性边界。

#### [From Tensor Buffer to Distributed Memory Hierarchy: A Survey of KV Cache Management for LLM Serving](2026/From%20Tensor%20Buffer%20to%20Distributed%20Memory%20Hierarchy%3A%20A%20Survey%20of%20KV%20Cache%20Management%20for%20LLM%20Serving.pdf)
- 身份：arXiv 预印本/综述（arXiv:2607.02574v1）。
- 简介：该综述以局部性、生命周期、所有权和承载介质四个轴分类三十余种 KV 管理系统，并归纳出本地分页、分离流水线、共享存储、内存池和混合分层五类架构。它还审计现有评测，指出与容错、隔离、分层淘汰和共享缓存语义相关的 KV 专项测量缺口。
- 与 AegisKV 的关系：综述为 AegisKV 的系统分类、模拟维度和指标选择提供直接框架，尤其支持明确 KV 所有权、生命周期、故障语义及恢复测量缺口。

#### [Predictive Multi-Tier Memory Management for KV Cache in Large-Scale GPU Inference](2026/Predictive%20Multi-Tier%20Memory%20Management%20for%20KV%20Cache%20in%20Large-Scale%20GPU%20Inference.pdf)
- 身份：个人署名预印本/技术报告（v2，2026-08；正文明确标注 Preprint，部分实现细节因专利申请暂不披露）。
- 简介：报告提出统一 attention 架构感知的 KV 容量计算、从 HBM 到并行文件系统的六级内存层次，以及基于 Bayesian reuse prediction 的放置、驱逐和预取。其缓存命中率来自组件级 trace replay，而集群级 TTFT、吞吐和成本收益被作者明确标为解析投影、无误差条。
- 与 AegisKV 的关系：该报告可作为多层 KV 容量和预测式放置的设计参考，但其集群级结论不是实机容错证据。AegisKV 可借鉴其分层状态价值判断，同时需独立验证故障恢复时延与可靠性。

#### [PAM: Processing Across Memory Hierarchy for Efficient KV-centric LLM Serving System](2026/PAM%3A%20Processing%20Across%20Memory%20Hierarchy%20for%20Efficient%20KV-centric%20LLM%20Serving%20System.pdf)
- 身份：arXiv 预印本（arXiv:2602.11521v1，2026-02-12）。
- 简介：PAM 是面向 KV 密集型服务的全栈分层内存方案，协调多种具备近数据计算能力的 PIM 设备，以同时满足 attention 的带宽需求和 KV 容量需求。它利用上下文局部性进行分层放置、跨设备并行 attention、KV 迁移与在线调度。
- 与 AegisKV 的关系：PAM 的异构层级放置和迁移机制可扩展 AegisKV 的 KV 状态位置与恢复路径设计空间；论文主要优化性能与成本，并未给出面向设备故障的恢复协议。

#### [Prefill-as-a-Service: KVCache of Next-Generation Models Could Go Cross-Datacenter](2026/Prefill-as-a-Service%3A%20KVCache%20of%20Next-Generation%20Models%20Could%20Go%20Cross-Datacenter.pdf)
- 身份：arXiv 预印本（arXiv:2604.15039v2，2026-04-22）。
- 简介：论文提出 PrfaaS，将长上下文 prefill 选择性卸载到跨数据中心的独立计算集群，再经普通以太网把较小的混合注意力模型 KV cache 送回本地 decode 集群。系统结合带宽感知调度和缓存感知放置，文中内部 1T 混合模型案例报告吞吐与 P90 TTFT 改善。
- 与 AegisKV 的关系：PrfaaS 把 KV 状态跨故障域传输和放置，扩大了 AegisKV 需要考虑的链路故障、远端副本与恢复调度场景；它本身聚焦异构资源效率而非故障容忍。

<a id="2026-kv-offload"></a>
**Offload、预取与块传输（7）**

#### [SolidAttention: Low-Latency SSD-based Serving on Memory-Constrained PCs](2026/SolidAttention%3A%20Low-Latency%20SSD-based%20Serving%20on%20Memory-Constrained%20PCs.pdf)
- 身份：正式会议论文，USENIX FAST 2026 论文集收录。
- 简介：SolidAttention 面向内存受限 PC，把动态稀疏 attention 与 SSD KV 存储协同设计，通过粗粒度 KV block、推测预取和计算/I/O 编排降低随机 I/O 与阻塞。论文报告在 128K 上下文下提升推理速度并大幅减少内存中的 KV 占用，同时维持其测试中的准确率。
- 与 AegisKV 的关系：SSD 持久层天然提供不同于 HBM/DRAM 的故障与恢复特性，SolidAttention 可作为 AegisKV 研究持久 KV 副本、恢复带宽和块粒度权衡的存储基线。其目标平台是本地 PC，与集群级故障模型不同。

#### [No Buffer, No Bottleneck: Efficient Zero-Copy KV Cache Offloading for Long-Context LLMs](2026/No%20Buffer%2C%20No%20Bottleneck%3A%20Efficient%20Zero-Copy%20KV%20Cache%20Offloading%20for%20Long-Context%20LLMs.pdf)
- 身份：正式会议论文，USENIX OSDI 2026 论文集收录。
- 简介：论文提出 DirectKV，面向 GH200/GB200 等 NVLink-C2C CPU-GPU 平台，让 GPU kernel 直接访问 CPU 中的 KV cache，消除 HBM staging buffer。它通过 CPU-memory-aware tiling、warp 级流水和 KV 生成/attention 融合减少传输与停顿，摘要报告降低 GPU 内存占用并获得最高 1.2× 端到端加速。
- 与 AegisKV 的关系：DirectKV 研究正常运行时的零拷贝分层存储与访问路径，可作为 AegisKV 故障保护之外的 KV 放置/传输基线；其 CPU 驻留 KV 也可能构成恢复时可利用的状态副本。

#### [ECHO: Efficient KV Cache Offloading with Lossless Prefetching for Serving Native Sparse Attention LLMs](2026/ECHO%3A%20Efficient%20KV%20Cache%20Offloading%20with%20Lossless%20Prefetching%20for%20Serving%20Native%20Sparse%20Attention%20LLMs.pdf)
- 身份：正式会议论文，收录于 USENIX OSDI 2026 会议论文集。
- 简介：ECHO 面向原生稀疏注意力模型，将 KV 缓存卸载到主机内存，并以兼容 GPU Graph 的缓存管理器处理动态淘汰和召回。它利用索引分数的可预测性进行无损预取，并以融合流水线重叠召回与索引计算。
- 与 AegisKV 的关系：它提供稀疏注意力下 KV 驻留、卸载与召回的系统基线，可扩展 AegisKV 对不同注意力机制和内存层级恢复成本的覆盖。

#### [FlexiCache: Leveraging Temporal Stability of Attention Heads for Efficient KV Cache Management](2026/FlexiCache%3A%20Leveraging%20Temporal%20Stability%20of%20Attention%20Heads%20for%20Efficient%20KV%20Cache%20Management.pdf)
- 身份：正式会议论文，PDF 标注发表于第 9 届 MLSys 会议（2026）。
- 简介：FlexiCache 根据不同 KV head 的重要页面集合在解码过程中的时间稳定性，将 head 分类为稳定和不稳定。稳定 head 只在 GPU 保留 top-K 页面并周期性重排，其余页面卸载到主机；不稳定 head 则保留完整 KV 以避免频繁传输。
- 与 AegisKV 的关系：它提供 head 级分层 KV 驻留与迁移模型，可帮助 AegisKV 表达部分状态保留、恢复优先级和主机/GPU 数据量；其目标主要是容量与解码性能。

#### [Bidaw: Enhancing Key-Value Caching for Interactive LLM Serving via Bidirectional Computation–Storage Awareness](2026/Bidaw%3A%20Enhancing%20Key-Value%20Caching%20for%20Interactive%20LLM%20Serving%20via%20Bidirectional%20Computation--Storage%20Awareness.pdf)
- 身份：正式会议论文，收录于 USENIX FAST 2026 会议论文集。
- 简介：Bidaw 面向主机内存与 SSD 两级 KV 存储，使计算引擎按 KV 所在层级和大小调度请求，同时让存储侧利用对话模式改进淘汰预测。它还选择性缓存存储效率更高的历史张量，以平衡空间占用和避免重算的收益。
- 与 AegisKV 的关系：论文的分层 KV 状态、加载延迟和请求阻塞模型可为 AegisKV 的正常态与恢复态存储行为提供基线；其核心并非故障容错。

#### [ContiguousKV: Accelerating LLM Prefill with Granularity-Aligned KV Cache Management](2026/ContiguousKV%3A%20Accelerating%20LLM%20Prefill%20with%20Granularity-Aligned%20KV%20Cache%20Management.pdf)
- 身份：arXiv 预印本（arXiv:2601.13631v1）。
- 简介：ContiguousKV 用统一的 ContiguousChunk 对齐语义剪枝、存储、传输和缓存粒度，以减少 SSD KV 读取放大。它利用跨层重要块索引的相似性进行异步预取，并以注意力分数指导上层缓存保留。
- 与 AegisKV 的关系：其块粒度、读取放大和预取流水线可细化 AegisKV 的分层 KV 传输成本；研究重点是正常 Re-Prefill 性能而非故障语义。

#### [ScoutAttention: Efficient KV Cache Offloading via Layer-Ahead CPU Pre-computation for LLM Inference](2026/ScoutAttention%3A%20Efficient%20KV%20Cache%20Offloading%20via%20Layer-Ahead%20CPU%20Pre-computation%20for%20LLM%20Inference.pdf)
- 身份：arXiv 预印本（arXiv:2603.27138v1，2026-03-28）；稿件带 DAC 2026 版式，但 DOI/ISBN 仍为占位符，故不据此认定为最终正式版本。
- 简介：ScoutAttention 通过 GPU-CPU 协作的 block-wise sparse attention 降低 KV offloading 的 I/O 和 CPU 计算瓶颈。其 layer-ahead CPU pre-computation 与异步周期性 recall 尝试把 CPU attention 提前一层执行，论文报告在小幅精度差异下相对已有 offloading 方法获得加速。
- 与 AegisKV 的关系：该工作提供 CPU 后备 KV、异步回召和跨设备计算的场景，可用于评估 AegisKV 在复杂 in-flight 数据路径上的故障一致性。它优化正常路径性能，并未证明故障恢复能力。

<a id="2026-kv-route"></a>
**亲和路由与准入驱逐（3）**

#### [PEEK: Predictive Queue-Informed KV Cache Management for LLM Serving](2026/PEEK%3A%20Predictive%20Queue-Informed%20KV%20Cache%20Management%20for%20LLM%20Serving.pdf)
- 身份：预印本（正文明确标注 “Preprint”，并给出 arXiv:2607.02525v1）。
- 简介：PEEK 从等待队列增量 radix tree 中提取请求间前缀共享结构，联合进行 cluster-aware admission、queue-aware eviction 和带公平性的多 lane 调度。作者在 SGLang 与 vLLM 上报告前缀丰富负载中的缓存命中、延迟和吞吐提升，并称在缺少共享结构时基本不回退。
- 与 AegisKV 的关系：PEEK 可作为无故障场景下 KV 感知调度和驱逐策略的对照；其“未来队列需求”信号也可用于 AegisKV 判断哪些 KV 状态更值得优先保护或恢复。

#### [CacheRoute: Planned Prefix-Affinity Routing for Large-Scale LLM Serving](2026/CacheRoute%3A%20Planned%20Prefix-Affinity%20Routing%20for%20Large-Scale%20LLM%20Serving.pdf)
- 身份：arXiv 预印本（arXiv:2608.19677v1）。
- 简介：CacheRoute 周期性地根据键的请求率规划稳定的前缀亲和路由，并以负载感知的放置和必要时的多目的地分配缓解热点。论文同时报告亲和性收益不足时性能可能下降，并建议部署前进行影子回放验证。
- 与 AegisKV 的关系：它适合作为缓存亲和路由基线，并为 AegisKV 分析故障后路由重映射、热缓存丢失和负载偏斜提供现实对照。

#### [DualMap: Enabling Both Cache Affinity and Load Balancing for Distributed LLM Serving](2026/DualMap%3A%20Enabling%20Both%20Cache%20Affinity%20and%20Load%20Balancing%20for%20Distributed%20LLM%20Serving.pdf)
- 身份：正式会议论文，PDF 明确标注发表于 ICLR 2026。
- 简介：DualMap 使用两个独立哈希函数为请求生成两个候选实例，再依据系统状态选择，以兼顾前缀缓存亲和和负载均衡。它还加入 SLO 感知路由、热点重平衡和双哈希环弹性扩缩机制。
- 与 AegisKV 的关系：DualMap 可作为分布式 KV 亲和调度基线；AegisKV 可检验节点故障、实例缩容和缓存失效时双映射策略的恢复表现。

<a id="2026-kv-reuse"></a>
**压缩、稀疏与跨请求/跨模型复用（11）**

#### [KVServe: Service-Aware KV Cache Compression for Communication-Efficient Disaggregated LLM Serving](2026/KVServe%3A%20Service-Aware%20KV%20Cache%20Compression%20for%20Communication-Efficient%20Disaggregated%20LLM%20Serving.pdf)
- 身份：arXiv 预印本，arXiv:2605.13734v1；正文页眉出现 SIGCOMM’26，但首页未提供可确认正式录用/出版的书目信息，故不据此认定 venue。
- 简介：KVServe 面向 prefill-decode 解耦和远端 KV 存储中的通信瓶颈，把多种 KV 压缩组件组织成可组合策略空间。其离线贝叶斯剖析生成 Pareto 候选集，在线控制器再依据带宽、负载、SLO 和质量约束选择压缩配置并修正离在线偏差。
- 与 AegisKV 的关系：它可直接启发 AegisKV 对 KV 传输体积、网络压力和服务目标之间权衡的建模，也提示恢复流量可采用自适应压缩；论文没有验证故障恢复语义。

#### [High Throughput and Low Latency LLM Serving via Adaptive KV Caching](2026/High%20Throughput%20and%20Low%20Latency%20LLM%20Serving%20via%20Adaptive%20KV%20Caching.pdf)
- 身份：正式会议论文；首页标明发表于 EuroSys 2026，并给出 ACM DOI。
- 简介：论文提出 eLLM，以细粒度、按 token 的自适应 KV 缓存取代整请求粒度的全缓存或全重算。系统在解码时保留部分 token 的 KV、并行重算未缓存部分，并通过分层通信-计算重叠和内核融合改善吞吐与首 token 延迟。
- 与 AegisKV 的关系：eLLM 展示了“保留、驱逐或重算”之间可动态权衡，适合作为 AegisKV 故障后 KV 恢复/重算成本模型的正常运行态参照；其目标并非容错。

#### [Adaptive KV Cache Reuse for Fast Long-Context LLM Serving](2026/Adaptive%20KV%20Cache%20Reuse%20for%20Fast%20Long-Context%20LLM%20Serving.pdf)
- 身份：arXiv 预印本（arXiv:2605.24022v1）。
- 简介：论文提出 CacheTune，以频域分析识别非前缀复用中需要重算的语义关键 token，并复用其余 KV。系统进一步联合稀疏传输、异步计算与 I/O 重叠以及硬件感知的重算比例调节，以适配 GPU 外的多级缓存池。
- 与 AegisKV 的关系：它直接涉及跨存储层的 KV 恢复、传输与重算权衡，可作为 AegisKV 恢复代价模型和长上下文复用策略的重要对照。

#### [PrefillShare: A Shared Prefill Module for KV Reuse in Multi-LLM Disaggregated Serving](2026/PrefillShare%3A%20A%20Shared%20Prefill%20Module%20for%20KV%20Reuse%20in%20Multi-LLM%20Disaggregated%20Serving.pdf)
- 身份：arXiv 预印本（arXiv:2602.12029v1，2026-02-12）。
- 简介：PrefillShare 将模型拆为冻结的共享 prefill 模块和各自微调的 decode 模块，使多个任务模型能够共享同一输入的 prefill 计算与 KV cache。论文还在 vLLM 式分离服务中加入异构模型路由，并报告多模型代理负载上的尾延迟和吞吐收益。
- 与 AegisKV 的关系：共享 KV 会把单份状态的失效影响扩散到多个模型/代理，因此是检验 AegisKV 保护优先级和故障影响范围的有价值场景。AegisKV 也需区分可共享 prefill 状态与模型专属 decode 状态。

#### [DroidSpeak: KV Cache Sharing Across Fine-tuned Model Variants](2026/DroidSpeak%3A%20KV%20Cache%20Sharing%20Across%20Fine-tuned%20Model%20Variants.pdf)
- 身份：正式会议论文，收录于 USENIX NSDI 2026 会议论文集。
- 简介：DroidSpeak 研究架构相同但微调版本不同的 LLM 之间共享 KV 缓存，并通过仅重算少数层来控制质量损失。系统将逐层重算与远端 KV 加载流水化，以提高跨模型复用的吞吐和首 token 性能。
- 与 AegisKV 的关系：它为 AegisKV 引入跨模型变体的 KV 可兼容性和部分重算维度；故障后从其他模型实例借用状态也可参考其质量与传输约束。

#### [RetroInfer: A Vector Storage Engine for Scalable Long-Context LLM Inference](2026/RetroInfer%3A%20A%20Vector%20Storage%20Engine%20for%20Scalable%20Long-Context%20LLM%20Inference.pdf)
- 身份：正式期刊/论文集论文，PVLDB 19(5)，2026。
- 简介：RetroInfer 将长上下文 KV cache 构造成基于稀疏注意力的向量存储，引入 attention-aware wave index，在检索成本与 attention 精度间做有界权衡。其 wave buffer 协调 GPU-CPU 数据和计算，论文报告在 120K 到百万 token 场景中相对完整或既有稀疏 attention 的解码吞吐提升。
- 与 AegisKV 的关系：RetroInfer 展示了 KV 状态被索引化、分段并跨 CPU-GPU 管理的复杂布局；AegisKV 若支持此类系统，需要保护索引元数据与 KV 数据的一致恢复，而不只是复制连续缓存块。

#### [OPKV: A High-Throughput Plugin-Driven Framework for Recallable Sparsity in Paged KV Cache Systems](2026/OPKV%3A%20A%20High-Throughput%20Plugin-Driven%20Framework%20for%20Recallable%20Sparsity%20in%20Paged%20KV%20Cache%20Systems.pdf)
- 身份：正式会议论文，MLSys 2026 论文集收录。
- 简介：OPKV 用插件接口将可召回 KV 稀疏算法与模型及分页缓存管理解耦，解决 token 级稀疏与 page 级管理之间的粒度不匹配。其对象重聚合、热页命中和迭代内元数据管理旨在降低 CPU 回召开销，论文报告为已有方法带来 1.3–1.8× 解码吞吐提升。
- 与 AegisKV 的关系：OPKV 提供分页 KV、CPU 后备层与细粒度回召的实现基线；AegisKV 需要额外考虑这些稀疏/分页状态在故障、备份和恢复过程中的一致性。

#### [SkipKV: Selective Skipping of KV Generation and Storage for Efficient Inference with Large Reasoning Models](2026/SkipKV%3A%20Selective%20Skipping%20of%20KV%20Generation%20and%20Storage%20for%20Efficient%20Inference%20with%20Large%20Reasoning%20Models.pdf)
- 身份：正式会议论文，MLSys 2026 论文集收录。
- 简介：SkipKV 针对长 chain-of-thought 推理的 KV 膨胀，指出 token 级驱逐在多 batch 下会因评分不稳定和 padding 降低有效预算。它以句子级相似性选择性跳过 KV 生成与存储，并用 steering vector 抑制冗余生成，论文报告在相近压缩预算下改善准确率、生成长度和吞吐。
- 与 AegisKV 的关系：SkipKV 会改变需要保护的 KV 数量和语义粒度，可用于考察压缩/选择性生成是否降低 AegisKV 的备份与恢复成本。恢复时仍需保证保留句子及其位置语义与模型执行状态一致。

#### [Kitty: Accurate and Efficient 2-bit KV Cache Quantization with Dynamic Channel-wise Precision Boost](2026/Kitty%3A%20Accurate%20and%20Efficient%202-bit%20KV%20Cache%20Quantization%20with%20Dynamic%20Channel-wise%20Precision%20Boost.pdf)
- 身份：正式会议论文；首页标明发表于 MLSys 2026。
- 简介：Kitty 通过动态通道级精度提升，将大部分 KV cache 压到 2 bit，同时把少量敏感 Key 通道保留为更高精度，以控制长上下文推理的精度损失。系统配套设计分页内存布局、Triton 解量化内核和轻量运行流水线，论文报告接近 8 倍的 KV 内存缩减及吞吐提升。
- 与 AegisKV 的关系：KV 压缩会改变检查点大小、传输量和恢复时间，因此 Kitty 可为 AegisKV 的状态体积与恢复带宽敏感性提供参数化参照；它本身不研究故障。

#### [CacheSlide: Unlocking Cross Position-Aware KV Cache Reuse for Accelerating LLM Serving](2026/CacheSlide%3A%20Unlocking%20Cross%20Position-Aware%20KV%20Cache%20Reuse%20for%20Accelerating%20LLM%20Serving.pdf)
- 身份：正式会议论文，收录于 USENIX FAST 2026 会议论文集。
- 简介：CacheSlide 针对 agent 提示中复用片段相对顺序稳定但绝对位置变化的模式，提出相对位置依赖缓存。系统通过位置编码修正、少量 token 注意力重算和分层/溢出感知管理复用跨位置 KV。
- 与 AegisKV 的关系：它扩展了 AegisKV 可考虑的复用语义，不再局限于严格前缀；但论文主要解决位置正确性和性能，而非故障恢复。

#### [Learning Agent Execution for KV-Cache Management in Agentic Serving](2026/Learning%20Agent%20Execution%20for%20KV-Cache%20Management%20in%20Agentic%20Serving.pdf)
- 身份：本地作者稿/投稿稿；首页有作者，但 ACM 会议名、DOI 和引用信息均为占位符，未见可确认的正式发表信息。
- 简介：论文提出 CacheScout，通过在线学习智能体之间的执行转移来预测未来 KV cache 复用，而不要求预先声明工作流 DAG 或离线训练。它据此指导缓存驱逐和主动预取，并在 vLLM 上评估多智能体工作负载中的命中率、TTFT、单轮延迟和吞吐。
- 与 AegisKV 的关系：CacheScout 的在线工作流预测与 KV 留存决策可补充 AegisKV 对智能体并发及复用价值的建模；它关注正常执行中的缓存命中，不覆盖故障造成的 KV 丢失。

<a id="2026-serving"></a>
### LLM Serving 调度、内存与执行系统

这组工作提供通用推理调度、并行执行、attention、内存虚拟化和 PD 服务机制，用于校准 AegisKV 的正常态系统假设。

#### [Multi-stage Flow Scheduling for LLM Serving](2026/Multi-stage%20Flow%20Scheduling%20for%20LLM%20Serving.pdf)
- 身份：arXiv 预印本，arXiv:2603.17456v1；首页未给出正式发表信息。
- 简介：论文提出 MFS，统一调度 KV block 远端读取、集合通信和 prefill-to-decode 传输等相互依赖的多阶段网络流。它以 Defer-and-Promote 原则和反向多级队列近似最小松弛度优先，在共享链路争用下提高 TTFT SLO 达标率。
- 与 AegisKV 的关系：MFS 可为 AegisKV 的 KV 传输、共享网络争用和多阶段恢复流调度提供网络侧基线；其评测针对常规 prefill 路径的 TTFT，而非故障后的恢复完成时间。

#### [Efficient Multi-round LLM Inference over Disaggregated Serving](2026/Efficient%20Multi-round%20LLM%20Inference%20over%20Disaggregated%20Serving.pdf)
- 身份：正式会议论文，收录于 ICML 2026（PMLR 306）会议论文集。
- 简介：论文提出 AMPD，面向预填充/解码分离架构中的多轮推理，根据实时负载决定增量 prefill 在 decode 实例本地执行还是转发到 prefill 实例，并联合规划两阶段资源与并行策略。目标是在交错 prefill-decode 工作负载下提高 SLO 达成率。
- 与 AegisKV 的关系：AMPD 提供 PD 分离、多轮状态迁移和动态调度背景；AegisKV 可进一步模拟实例故障及 KV 状态可用性对增量 prefill 路由的影响。

#### [Prism: Cost-Efficient Multi-LLM Serving via GPU Memory Ballooning](2026/Prism%3A%20Cost-Efficient%20Multi-LLM%20Serving%20via%20GPU%20Memory%20Ballooning.pdf)
- 身份：正式会议论文，USENIX OSDI 2026 论文集收录。
- 简介：Prism 通过 GPU memory ballooning 在多模型服务中统一空间共享与时间共享，依据动态 bursty-group 工作集回收和重新分配显存。其 kvcached balloon driver 已开源，论文称该机制已用于超过一万张 GPU 的生产环境。
- 与 AegisKV 的关系：Prism 的动态显存回收会改变 KV 可用容量与驱逐压力，可作为 AegisKV 在多模型共置和突发负载下的资源竞争背景。它关注利用率和 SLO，不替代故障时 KV 状态保护与恢复。

#### [Simple is Better: Multiplication May Be All You Need for LLM Request Scheduling](2026/Simple%20is%20Better%3A%20Multiplication%20May%20Be%20All%20You%20Need%20for%20LLM%20Request%20Scheduling.pdf)
- 身份：正式会议论文，USENIX OSDI 2026 论文集收录。
- 简介：论文提出 LMETRIC，用“新增 prefill token 数”和“当前 batch size”两个指标的乘积，在无需工作负载特定超参调优的情况下联合考虑 KV 命中与负载均衡。作者给出乘法可能失效的数学条件，并报告真实聊天和 coding-agent 负载中的延迟改善以及生产 canary 结果。
- 与 AegisKV 的关系：LMETRIC 可作为 AegisKV 评估中的正常态 KV-aware 路由基线；故障后还可将恢复中的 KV 可用性反映到新增 prefill token 指标，但原论文未覆盖恢复成本。

<a id="2026-peripheral"></a>
### 资源管理、可靠性与外围参考

这组工作从通用资源控制、语义可靠性、软错误或上下文处理侧提供外围背景，不与 AegisKV 的 fail-stop KV 恢复直接等价。

#### [One Pool, Two Caches: Adaptive HBM Partitioning for Accelerating Generative Recommender Serving](2026/One%20Pool%20-%20Two%20Caches%20-%20Adaptive%20HBM%20Partitioning%20for%20Accelerating%20Generative%20Recommender%20Serving.pdf)
- 身份：arXiv 预印本（arXiv:2605.04450v1，2026-05-06）。
- 简介：论文针对生成式推荐服务中 embedding 热缓存与 KV cache 竞争同一 HBM 的问题，提出 HLEM 联合调整内存份额与请求路由。系统使用分层 PPO 控制器和 EMB-KV 感知调度，在文中所述 32 节点 A100 实验中改善 P99 延迟与 SLO 满足率。
- 与 AegisKV 的关系：该工作强调 KV 与其他常驻状态之间的动态容量竞争，可为 AegisKV 的容量压力和故障后资源重分配建模提供参考，但其目标不是容错或 KV 恢复。
