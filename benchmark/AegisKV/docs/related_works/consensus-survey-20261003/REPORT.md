# AegisKV 相关论文增补：Consensus 检索与当前设计对照

- 检索/归档日期：2026-10-03。
- 入口：[总索引](../RELATED_WORKS.md)；[论文明细 CSV](LITERATURE.csv)；[补充 BibTeX](REFERENCES.bib)。
- 范围：围绕当前 AegisKV 的故障保护、Agent 工作流、原生稀疏 KV、层序恢复和容量控制进行探索性检索；不是系统综述，也不声明覆盖所有相关论文。
- 修改范围：仅 `docs/related_works/`；未修改 `paper/`、已冻结模型/trace 或实验数据。

## 1. 本次更新

| 项目 | 结果 |
|---|---|
| Consensus 检索 | 6 次、每次 20 个结果；未设置年份/学科/引用量等过滤 |
| 原始命中 | 120 条，按精确 Consensus URL 去重为 87 条记录；改名/出版版本仍需人工核对 |
| 本次精选 | 16 条：15 篇公开全文 + WaSMa 的摘要/正式 DOI 元数据 |
| 新增公开 PDF | 15 篇，全部通过来源、页数、可提取文本和 SHA-256 检查；不覆盖既有文件 |
| 既有库补索引 | 5 篇此前已有 PDF 但无索引条目 |
| 年份目录覆盖 | 从既有 102 篇增至 117 篇；总索引从 97 条补齐为 117 条 |
| 出版身份 | 正式论文集/出版社元数据与 arXiv 作者的接收声明分开记录 |

本次以“AegisKV fault tolerant LLM serving”搜索未返回同名论文；不能由一次检索推出 AegisKV 没有公开论文。研究关联依据项目当前设计，而不是把结果中名称相近的 Aegaeon 当作 AegisKV。

### 新增全文分组

- **稀疏 KV 与分层内存**：HiSparse [1]、SPIN [2]、SAC [3]、InfiniGen [10]、NOSA [11]。
- **Agent 工作流**：PBKV [4]、TokenCake [5]、CacheWise [6]、GraphFlow [7]、Parrot [12]。
- **搬运/复用基础设施**：LMCache [8]、CachedAttention [9]、MemServe [15]。
- **层放置与物理内存管理**：OrbitFlow [13]、PagedAttention/vLLM [14]。
- **仅参考线索**：WaSMa [16]；Crossref 已核对题名、作者、ICCCN 2026 和 DOI，但本次没有取得全文，不计入 117 篇本地 PDF。

本地 PDF 按首次 arXiv 年份放入年份目录。TokenCake/NOSA 因首发于 2025 年归在 `2025/`，不表示其 v5/v3 修订或正式发表也在 2025 年。旧文件目录不移动。

## 2. 对照的 AegisKV 版本

以 `benchmark/AegisKV/README.md`、`paper/system_design.tex` 及 `AGENTS.md` 最新修订为准：

1. Tracker 在 invocation 提交时预测 Agent 剩余时间，计算 guarded Slack；未来输出和最终调用次数不得作为特征。
2. 以完整重建延迟与 Slack 的差值决定保护 Agent，在独立 Peer DRAM 保留完整检查点；checkpoint 间隔为 Z=256 tokens。
3. Peer HBM 是加速副本：前 L 层各保留 Top-K 原生选择计数块，checkpoint 时衰减/重排并采用替换迟滞；不是修改 native selector。
4. 层序恢复包括按需 miss、必要辅助状态及 checkpoint 后尾部重建；L 按预期恢复并发下的有效 H2D 带宽校准。
5. Adapter 调整每 rank 总 Peer-HBM 配额。完整 DRAM backing 使缩减 HBM 副本无需假设额外迁移；DRAM 与 HBM 的分配及临时副本仍需计量。

本次对照不沿用历史的租金/credit、共享 SSD Store 或不完整 DRAM backing。既有总索引未逐篇重写，旧条目的设计关系可能反映历史版本，当前解读以本节为准。

## 3. 最值得精读的近邻

### 3.1 故障恢复：不能简单归为“只恢复已选的 KV”

DéjàVu 的增量 KV streaming/checkpoint 路线 [17]、LUMEN 的故障前放置与故障后分发/容量恢复 [19]、GhostServe 的 host-memory parity shards [18]、RaidServe 的 TP 状态备份与故障后非规则计算/内存平衡 [20]，以及 KevlarFlow 的后台复制和故障重路由 [21]，都应作为直接相关工作。

**写作建议**：区分“workflow slack 决定保护范围”和“已保护状态如何恢复”，但不要声称所有前作都不研究放置、负载或恢复调度。LUMEN 已包含协调放置与调度 [19]；GhostServe 的主要区别是编码冗余而非简单全量复制 [18]；RaidServe 已结合备份、权重恢复和 TP 内部的均衡 [20]。本次未复现任何一个系统，也没有新增 AegisKV 优于它们的测量。

### 3.2 HiSparse / SPIN：完整主机历史 + 小 GPU 工作集

HiSparse 将完整历史保存在 host memory，以有界 GPU cache、命中/替换/按需 H2D 和条件性跨层预取支持原生稀疏执行 [1]。SPIN 进一步讨论不同稀疏粒度的统一表示、每请求预算、GPU-friendly 替换和元数据布局 [2]。

这两篇直接约束“完整 DRAM + Top-K HBM”可以怎样实现，却**不等于跨故障域容错**。AegisKV 的差异应落在 Peer placement、Slack 驱动保护准入、checkpoint 一致性/尾部回放、以及复制对健康请求的影响；不能把“小 HBM + 大 DRAM”本身作为独有贡献。

建议对照：相同 native selections、相同 HBM/DRAM/临时空间预算下，比较 recency、checkpoint-decayed frequency 和受控 prefetch。分别报告 selected-access coverage、真实 H2D 字节、miss wait、普通执行开销和工作流完成时间；命中率不直接代表故障收益。

### 3.3 CachedAttention / InfiniGen / NOSA：层序搬运并非新概念

CachedAttention 已用逐层预加载、异步保存和 scheduler hints 将慢层 I/O 与计算重叠 [9]。InfiniGen 用轻量 rehearsal 推测下一层需要的 KV 并选择性预取 [10]。NOSA 将可 offload 的稀疏 pattern 纳入训练，NOSI 执行系统据此减少传输 [11]。

AegisKV 应明确：保留原生 selector，依历史选择次数决定保护副本，而不是通过近似选择省略 attention 需要的状态。辅助 selector metadata、miss fetch 和尾部回放必须计入；只有匹配硬件、并发和模型的有效带宽才可参数化 L。上述论文的吞吐改善不构成 AegisKV 的恢复加速证据。

SAC 的 CXL 细粒度远端访问也展示了稀疏需求与全前缀搬运之间的冲突 [3]，但 CXL load/store 与本项目 Peer DRAM H2D/RDMA 假设不同，不直接搬用其性能比例。

### 3.4 工作流近邻：预测目标、关键路径与正常态收益

Parrot 提供暴露应用级依赖的 Semantic Variable 抽象 [12]；KVFlow 以未来 activation 距离管理 prefix cache [22]；Continuum 围绕跨工具调用的驻留 TTL 和排队代价保持多轮连续性 [23]；TOPAS 结合最长剩余 service path 与 prefix residency [24]。

新增 PBKV 对未来调用/复用做保守预测 [4]，TokenCake 结合关键路径显存划分与调用间 offload/upload [5]，CacheWise 使用 coding-agent traces 与工具元数据 [6]。它们能够挑战“只按最近使用保留 KV”的假设，但**未来调用预测不等于剩余秒数预测**，关键路径内存调度也不自动提供容错。

建议实验：按 workflow 分组划分训练/验证；比较零 Slack、因果预测和离线 oracle；报告预测误差、保护决策误差、WCT 和预测开销。没有 tool metadata 的当前工作负载，不应用未来工具时长补造这些系统的运行条件。GraphFlow 的原子操作 wGraph [7] 与本项目 invocation/history、Agent 任务 Slack 的粒度也需分别说明。

### 3.5 OrbitFlow / LMCache：配额选择与工程执行

OrbitFlow 的动态层驻留优化 [13]可作为固定 first-L 放置的机制参照，LMCache 的 batched movement、pipeline、connector 和 control API [8]可作为工程集成参照。PagedAttention 的物理页共享 [14]及 MemServe 的 locality-aware 目录/放置 [15]有助于核算去重、瞬时迁移占用和路由成本。

需要分开比较普通执行 KV 管理与冗余保护内存。不能把普通 cache sharing 当成新增独立副本，也不能因某框架支持存取或 offload 就声称已完成故障 fencing、commit-before-publish 或 drain-before-release。

## 4. 推荐的匹配对照维度

| AegisKV 问题 | 相关工作 | 需要匹配的条件 / 不可直接推论 |
|---|---|---|
| 谁需要独立保护 | LUMEN [19]、工作流系统 [4–7,12,22–24] | 相同 DAG、失败时刻、Slack 有效性、完整 DRAM 容量；不用预测论文替代 Slack 验证 |
| 完整 checkpoint 与 replay | DéjàVu [17]、GhostServe [18]、KevlarFlow [21] | 模型/布局、TP ranks、token log、checkpoint 间隔、失败域；全系统 MTTR 不等于 KV-only 恢复 |
| HBM 热块与 misses | HiSparse [1]、SPIN [2]、InfiniGen [10]、NOSA [11] | 相同 native selector、块粒度、HBM 字节、辅助状态与真实队列；approximate 与 exact 边界分开 |
| 层序 overlap / first-L | CachedAttention [9]、OrbitFlow [13]、SAC [3] | 有效每恢复带宽、层计算、需求揭露时间、有限 workspace；不采用链路峰值推断收益 |
| quota 与正常态开销 | SPIN [2]、TokenCake [5]、PagedAttention [14] | 前台 batch/队列和临时副本占用；保护开销、恢复收益分别测量 |
| 可落地的数据搬运 | LMCache [8]、MemServe [15] | manifest、兼容、reader/copy leases、完成反馈和物理字节；接口存在不等于容错已经实现 |

这里是后续对照建议，不是已执行实验。内部 ablation 也不应命名为对某篇系统的完整 reproduction。

## 5. 身份纠正、版本与证据边界

- **FailSafe / RaidServe 去重**：Consensus 返回 arXiv:2511.14116 的旧题名 FailSafe [20]；本地 RaidServe 与 MLSys 2026 官方页面已核对，是同一工作，不重复下载/计数。
- **GhostServe**：Consensus 只给 arXiv 身份 [18]；MLSys 2026 官方论文集已确认正式题名及作者。保留本地正式 PDF。
- **LMCache / GraphFlow 作者信息**：聚合结果和所下载版本的作者列表/姓名呈现不同；正式引用优先该版本 PDF/原始页面，不直接复制 Consensus 摘要行的首作者。
- **TokenCake**：arXiv v5 为 2026-09-28 修订，页面声明 EuroSys '27 接收，PDF 给出未来会议引用信息；本次未核验最终论文集，BibTeX 仍按下载的 arXiv 版本引用。
- **NOSA**：本次下载 v3，页面/首页声明 EMNLP 2026 main；不自动把现有 v2 引用、模型 checkpoint 或旧 selector trace 升级为 v3 实验。
- **GraphFlow**：接收信息来自作者 arXiv 页面；“接收声明”不等于本次已核验正式论文集。
- **OrbitFlow**：下载的 PDF 首页有 PVLDB 19(5):1046–1059 和正式 DOI [10.14778/3796195.3796214](https://doi.org/10.14778/3796195.3796214)，已进一步用 Crossref 核验。文件没有 arXiv 水印，版本依据固定的请求/最终响应 URL 2601.10729v2 与匹配的题名/DOI。arXiv 摘要与下载 PDF 中 TPOT/TBT 改善百分比不同，本次没有采用这些数字。
- **CachedAttention / InfiniGen / Parrot / PagedAttention**：分别以官方 USENIX 页面或 Crossref 正式 DOI 核验发表身份；本地全文可以是 arXiv 版本，版本来源仍保留。
- **MemServe**：下载 v3 的首页题名为“Flexible Memory Pool for Building Disaggregated LLM Serving with Caching”，但 arXiv HTML/Consensus 保留旧题名“Context Caching for Disaggregated LLM Serving with Elastic Memory Pool”。按同一 arXiv ID 去重；引用采用 PDF 题名，保留下载文件名与旧题名作为别名。
- **WaSMa**：只具备检索摘要与 Crossref 元数据核验，不写为“已读全文”或“已归档 PDF”。
- **数据来源**：新条目依据原始摘要、出版元数据及 PDF 首页/第二页，不声称逐页精读或复现实验。原始文本、页数和 SHA-256 保留在 `sources/`、`SOURCES.json`。
- **机密材料**：既有匿名投稿/本地稿件不上传至外部检索服务；本次只发送学术主题查询并下载公开来源。
- **证据分离**：他文的实测/模型结果不转化为 AegisKV 测量。保留项目既有不利的 recency/Top-K、Slack 预测和成本结果；没有从文献中推算新加速比。

## 6. 文件与复核方式

- `search-01.json` … `search-06.json`：完整原始 Consensus 返回及查询。
- `CANDIDATES.json`：87 条去重记录及每次命中的排名。
- `SELECTION.json` / `ANNOTATIONS.json`：本次选择、原始标识与项目分析。
- `SOURCES.json` / `PUBLISHER_CHECKS.json`：arXiv 页面、版本、下载地址、PDF 哈希及出版核验。
- `LOCAL_BEFORE.json`：修改前 102 篇年份目录 PDF 的哈希，用于确认未覆盖。
- `LITERATURE.csv` / `REFERENCES.bib`：16 条精选明细与独立引用包；不替换正文 bibliography。
- `fetch_sources.py`：公开来源获取脚本，拒绝覆盖已有 PDF。
- `build_catalog.py`：从已保存元数据生成 CSV、BibTeX 和索引片段；不修改总索引或稿件。
- `validate.py` / `VALIDATION.json`：离线复核脚本与新 PDF、既有哈希、索引数量、本地链接的检查记录。
- `review/VISUAL_REVIEW.md`：15 篇新增 PDF 首页的视觉身份核对；不是整篇布局审查。
- `RELATED_WORKS.before.md` / `INDEX_CHANGES.json`：原索引快照与本次精确变更记录。

## 参考文献

下列 [1]–[24] 是本报告的稳定编号，便于跨查询去重；每条另列原始 Consensus 查询编号和结果编号。Consensus 链接原样保留，正式身份以本次原始/官方来源核验为准。原始检索中的动态引用量仅保存在检索返回中，不用来排序研究价值。

[1] [HiSparse: Scaling Sparse-Attention Decoding with Hierarchical KV Cache Management](https://consensus.app/papers/details/a1c12fd288035ed9b8af90f74bc33d97/?utm_source=unknown) — Xie, Zhiqiang and Huang, Zhangheng and Huang, Tingwei and Xu, Ziyi and Ma, Ruiyang and Kozyrakis, Christos；arXiv 预印本；本次未核验正式出版；[原始来源](https://arxiv.org/abs/2608.07009)；[本地 PDF](../2026/HiSparse%20-%20Scaling%20Sparse-Attention%20Decoding%20with%20Hierarchical%20KV%20Cache%20Management.pdf)。Consensus 检索 3 的结果 [16]。

[2] [Unifying Sparse Attention with Hierarchical Memory for Scalable Long-Context LLM Serving](https://consensus.app/papers/details/7a487eb29ac75833a220506e1afb373c/?utm_source=unknown) — Zhao, Zihan and Lu, Baotong and Lin, Shengjie and Chen, Yizou and Liu, Jing and Zhang, Yanqi and Miao, Ziming and Yang, Ming-Chang and Shen, Haiying and Chen, Qi and Yang, Fan；arXiv 预印本；本次未核验正式出版；[原始来源](https://arxiv.org/abs/2604.26837)；[本地 PDF](../2026/Unifying%20Sparse%20Attention%20with%20Hierarchical%20Memory%20for%20Scalable%20Long-Context%20LLM%20Serving.pdf)。Consensus 检索 3 的结果 [17]。

[3] [SAC: Disaggregated KV Cache System for Sparse Attention LLMs with CXL](https://consensus.app/papers/details/aa293487915f55339355c44f9a9efd79/?utm_source=unknown) — Ma, Ruiyang and Ma, Teng and Li, Junru and Zha, Hantian and Shang, Xuchun and Hu, Qingda and Liu, Zheng and Yang, Xinjun and Ma, Tao and Luo, Guojie；arXiv 预印本；本次未核验正式出版；[原始来源](https://arxiv.org/abs/2606.19746)；[本地 PDF](../2026/SAC%20-%20Disaggregated%20KV%20Cache%20System%20for%20Sparse%20Attention%20LLMs%20with%20CXL.pdf)。Consensus 检索 3 的结果 [14]。

[4] [Efficient Serving for Dynamic Agent Workflows with Prediction-based KV-Cache Management](https://consensus.app/papers/details/5a27ea94c2355da5a8121efb957e42ff/?utm_source=unknown) — Zheng, Haoyu and Fu, Fangcheng and Wu, Jia and Yuan, Binhang and Zhang, Yongqiang and Wang, Hao and Zhu, Yuanyuan and Yan, Xiao and Jiang, Jiawei；arXiv 预印本；本次未核验正式出版；[原始来源](https://arxiv.org/abs/2605.06472)；[本地 PDF](../2026/Efficient%20Serving%20for%20Dynamic%20Agent%20Workflows%20with%20Prediction-based%20KV-Cache%20Management.pdf)。Consensus 检索 2 的结果 [5]。

[5] [TokenCake: A KV-Cache-centric Serving Framework for LLM-based Multi-Agent Applications](https://consensus.app/papers/details/67280a0868b45209a125c8ce6940fa7d/?utm_source=unknown) — Bian, Zhuohang and Wu, Feiyang and Li, Zhuoran and Ma, Teng and Zhuo, Youwei；arXiv v5；作者页面声明 Accepted at EuroSys '27；未核验最终论文集；[原始来源](https://arxiv.org/abs/2510.18586)；[本地 PDF](../2025/TokenCake%20-%20A%20KV-Cache-centric%20Serving%20Framework%20for%20LLM-based%20Multi-Agent%20Applications.pdf)。Consensus 检索 2 的结果 [9]。

[6] [CacheWise: Understanding Workloads and Optimizing KVCache Management for Efficiently Serving LLM Coding Agents](https://consensus.app/papers/details/33d28a9787275c6cb72f4bc631014b5d/?utm_source=unknown) — Tiwari, Shubham and Chugh, Tapan and Rickert, Nash and Peter, Simon and Mahajan, Ratul and Shen, Haiying；arXiv 预印本；本次未核验正式出版；[原始来源](https://arxiv.org/abs/2606.16824)；[本地 PDF](../2026/CacheWise%20-%20Understanding%20Workloads%20and%20Optimizing%20KVCache%20Management%20for%20Efficiently%20Serving%20LLM%20Coding%20Agents.pdf)。Consensus 检索 2 的结果 [13]。

[7] [GraphFlow: A Graph-Based Workflow Management for Efficient LLM-Agent Serving](https://consensus.app/papers/details/3454ecaf7a425269ae2458110dda48a1/?utm_source=unknown) — Li, Ao and Yang, Shangpeng and Chen, Fahao and Xu, Tianheng and Li, Peng and Su, Zhou；arXiv v1；作者页面声明 Accepted to ICML 2026；未核验最终论文集；[原始来源](https://arxiv.org/abs/2605.22566)；[本地 PDF](../2026/GraphFlow%20-%20A%20Graph-Based%20Workflow%20Management%20for%20Efficient%20LLM-Agent%20Serving.pdf)。Consensus 检索 2 的结果 [16]。

[8] [LMCache: An Efficient KV Cache Layer for Enterprise-Scale LLM Inference](https://consensus.app/papers/details/65b7eca34ea6591cb1acd95c7c7741cd/?utm_source=unknown) — Liu, Yuhan and Yao, Jiayi and Cheng, Yihua and An, Yuwei and Chen, Xiaokun and Feng, Shaoting and Huang, Yuyang and Shen, Samuel and Zhang, Rui and Du, Kuntai and Jiang, Junchen；arXiv 预印本 v2；本次未核验正式出版；[原始来源](https://arxiv.org/abs/2510.09665)；[本地 PDF](../2025/LMCache%20-%20An%20Efficient%20KV%20Cache%20Layer%20for%20Enterprise-Scale%20LLM%20Inference.pdf)。Consensus 检索 1 的结果 [19]。

[9] [Cost-Efficient Large Language Model Serving for Multi-turn Conversations with CachedAttention](https://consensus.app/papers/details/1fa413fafddd5c8a8b3e90bdc80306ae/?utm_source=unknown) — Gao, Bin and He, Zhuomin and Sharma, Puru and Kang, Qingxuan and Jevdjic, Djordje and Deng, Junbo and Yang, Xingkun and Yu, Zhou and Zuo, Pengfei；USENIX ATC 2024；官方论文页面已核验；本地为 arXiv v3；[原始来源](https://arxiv.org/abs/2403.19708)；[本地 PDF](../2024/Cost-Efficient%20Large%20Language%20Model%20Serving%20for%20Multi-turn%20Conversations%20with%20CachedAttention.pdf)。Consensus 检索 3 的结果 [13]。

[10] [InfiniGen: Efficient Generative Inference of Large Language Models with Dynamic KV Cache Management](https://consensus.app/papers/details/95cf2a69c1ca5dac9ba6f8db382ffcaa/?utm_source=unknown) — Lee, Wonbeom and Lee, Jungi and Seo, Junghwan and Sim, Jaewoong；USENIX OSDI 2024；官方论文页面已核验；本地为 arXiv v1；[原始来源](https://arxiv.org/abs/2406.19707)；[本地 PDF](../2024/InfiniGen%20-%20Efficient%20Generative%20Inference%20of%20Large%20Language%20Models%20with%20Dynamic%20KV%20Cache%20Management.pdf)。Consensus 检索 3 的结果 [12]。

[11] [NOSA: Native and Offloadable Sparse Attention](https://consensus.app/papers/details/b25287d22a6356cd83253ca890337993/?utm_source=unknown) — Huang, Yuxiang and Wang, Pengjie and Han, Jicheng and Zhao, Weilin and Su, Zhou and Sun, Ao and Lyu, Hongya and Zhao, Hengyu and Wang, Yudong and Xiao, Chaojun and Han, Xu and Liu, Zhiyuan；arXiv v3；作者页面标记 EMNLP 2026 main；未核验最终论文集；[原始来源](https://arxiv.org/abs/2510.13602)；[本地 PDF](../2025/NOSA%20-%20Native%20and%20Offloadable%20Sparse%20Attention.pdf)。Consensus 检索 3 的结果 [20]。

[12] [Parrot: Efficient Serving of LLM-based Applications with Semantic Variable](https://consensus.app/papers/details/fa20fa415f5a5cb1936733f65fc146dc/?utm_source=unknown) — Lin, Chaofan and Han, Zhenhua and Zhang, Chengruidong and Yang, Yuqing and Yang, Fan and Chen, Chen and Qiu, Lili；USENIX OSDI 2024；官方论文页面已核验；本地为 arXiv v1；[原始来源](https://arxiv.org/abs/2405.19888)；[本地 PDF](../2024/Parrot%20-%20Efficient%20Serving%20of%20LLM-based%20Applications%20with%20Semantic%20Variable.pdf)。Consensus 检索 6 的结果 [3]。

[13] [OrbitFlow: SLO-Aware Long-Context LLM Serving with Fine-Grained KV Cache Reconfiguration](https://consensus.app/papers/details/a40f9d2da8d851dc9152c63a30842ca0/?utm_source=unknown) — Ma, Xinyue and Hong, Heelim and Um, Taegeon and Lee, Jongseop and Choy, Seoyeong and Lee, Woo-Yeon and Jeon, Myeongjae；PVLDB 19(5):1046–1059, 2026；PDF 首页与 Crossref 正式 DOI 已核验；下载自 arXiv v2；[原始来源](https://arxiv.org/abs/2601.10729)；[本地 PDF](../2026/OrbitFlow%20-%20SLO-Aware%20Long-Context%20LLM%20Serving%20with%20Fine-Grained%20KV%20Cache%20Reconfiguration.pdf)。Consensus 检索 3 的结果 [19]。

[14] [Efficient Memory Management for Large Language Model Serving with PagedAttention](https://consensus.app/papers/details/b03df83de2535d95aec8eea20e23d40b/?utm_source=unknown) — Kwon, Woosuk and Li, Zhuohan and Zhuang, Siyuan and Sheng, Ying and Zheng, Lianmin and Yu, Cody Hao and Gonzalez, Joseph E. and Zhang, Hao and Stoica, Ion；SOSP 2023；Crossref DOI 元数据已核验；本地为 arXiv v1；[原始来源](https://arxiv.org/abs/2309.06180)；[本地 PDF](../2023/Efficient%20Memory%20Management%20for%20Large%20Language%20Model%20Serving%20with%20PagedAttention.pdf)。Consensus 检索 1 的结果 [20]。

[15] [MemServe: Flexible Memory Pool for Building Disaggregated LLM Serving with Caching](https://consensus.app/papers/details/5338e095d7855781ba84605b64f798e6/?utm_source=unknown) — Hu, Cunchen and Huang, Heyang and Hu, Junhao and Xu, Jiang and Chen, Xusheng and Xie, Tao and Wang, Chenxi and Wang, Sa and Bao, Yungang and Sun, Ninghui and Shan, Yizhou；arXiv 预印本 v3；本次未核验正式出版；[原始来源](https://arxiv.org/abs/2406.17565)；[本地 PDF](../2024/MemServe%20-%20Context%20Caching%20for%20Disaggregated%20LLM%20Serving%20with%20Elastic%20Memory%20Pool.pdf)。Consensus 检索 1 的结果 [11]。

[16] [WaSMa: Workflow-Aware Scheduling for Multi-Agent LLM Systems](https://consensus.app/papers/details/8c17de5f42e15bddaf9d25d42d114631/?utm_source=unknown) — Rao, Uttam and Sadiq, Ali Zafar and Shen, Haiying and Yang, Yuqing and Hodges, Elijah-Amir Randall and Muntean, Marcus；ICCCN 2026；Crossref DOI/作者已核验；本次未下载全文；[原始来源](https://doi.org/10.1109/icccn69946.2026.11662938)。Consensus 检索 2 的结果 [4]。

[17] [DéjàVu: KV-cache Streaming for Fast, Fault-tolerant Generative LLM Serving](https://consensus.app/papers/details/8641c83c33dc57bfba1d9599506c392e/?utm_source=unknown) — Foteini Strati et al., ICML 2024；[PMLR 正式页面](https://proceedings.mlr.press/v235/strati24a.html)。arXiv DOI: 10.48550/arxiv.2403.01876；原检索 1 的结果 [2]，本地已收录。

[18] [GhostServe: A Lightweight Checkpointing System in the Shadow for Fault-Tolerant LLM Serving](https://consensus.app/papers/details/7fa352ee97cd5544a7fb016ad8b9dad5/?utm_source=unknown) — Shakya Jayakody et al., MLSys 2026；[正式论文集](https://proceedings.mlsys.org/paper_files/paper/2026/hash/d99e8e80a6c41e148db686918dd7eab3-Abstract-Conference.html)。arXiv DOI: 10.48550/arxiv.2605.00831；原检索 1 的结果 [1]，本地已收录。

[19] [LUMEN: Coordinated Failure Recovery for Distributed LLM Serving](https://consensus.app/papers/details/7c8bca08271652d3b7f2ac7fb2ea6c17/?utm_source=unknown) — Zhang Cao et al., arXiv 2026；DOI: 10.48550/arxiv.2606.17787。原检索 1 的结果 [5]，本地已收录。

[20] [FailSafe: High-performance Resilient Serving](https://consensus.app/papers/details/2592a6fe26ca5e0c97a78f456ce310bb/?utm_source=unknown) — Ziyi Xu et al.；正式题名为 RaidServe，MLSys 2026；[正式论文集](https://proceedings.mlsys.org/paper_files/paper/2026/hash/507b4aacefe5325908e24f042617b741-Abstract-Conference.html)。旧题名 arXiv DOI: 10.48550/arxiv.2511.14116。原检索 1 的结果 [6]，本地已收录，未重复计数。

[21] [Towards Resiliency in Large Language Model Serving with KevlarFlow](https://consensus.app/papers/details/128869ec37e859b8ab6172dc780d2f90/?utm_source=unknown) — Shangshu Qian et al., arXiv 2026；DOI: 10.48550/arxiv.2601.22438。原检索 1 的结果 [4]，本地已收录。

[22] [KVFlow: Efficient Prefix Caching for Accelerating LLM-Based Multi-Agent Workflows](https://consensus.app/papers/details/651c62cc66385b6f8a557260e5abcd6f/?utm_source=unknown) — Zaifeng Pan et al., arXiv 2025；DOI: 10.48550/arxiv.2507.07400。原检索 2 的结果 [1]，本地已收录。

[23] [Continuum: Efficient and Robust Multi-Turn LLM Agent Scheduling with KV Cache Time-to-Live](https://consensus.app/papers/details/f8ed913f8f52589c9b948eda9f13a745/?utm_source=unknown) — Han-Chen Li et al., arXiv 首发 2025；DOI: 10.48550/arxiv.2511.02230。原检索 2 的结果 [2]，本地已收录；下载修订版本见总索引。

[24] [TOPAS: Workflow-Aware Prefix-State Scheduling for Multi-Agent LLM Serving](https://consensus.app/papers/details/b3a41617a14a52c1bee835ca35b51fb4/?utm_source=unknown) — Hongqiu Ni et al., arXiv 2026；DOI: 10.48550/arxiv.2608.25523。原检索 2 的结果 [3]，本地已收录。
