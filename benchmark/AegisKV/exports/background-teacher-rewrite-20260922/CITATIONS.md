# 老师版 Background：引用与图像对应表

核查日期：2026-09-22。以用户提供的 `teacher-background-original.tex` 为准。正文保留老师的行文，补齐 3 个空引用，另为工作流调度、跨轮次 KV 复用和恢复路径添加直接依据。配图是原创概念示意，不是实测或 trace 回放。

## 原稿的三个空引用

| 原文位置 | 已填入的 LaTeX | 原始来源及适用范围 |
|---|---|---|
| `a tensor-parallel ... group` | `\cite{shoeybi2019megatron}` | [Megatron-LM](https://arxiv.org/abs/1909.08053)，2019，§3 / Figure 3：Transformer 层内张量并行，包括按 attention head 划分计算。这是 TP 原理来源，不把训练论文当作 KV checkpoint 实现证据。 |
| `model-parallel ... configuration` | `\cite{kwon2023vllm}` | [vLLM / PagedAttention，SOSP 2023](https://doi.org/10.1145/3600006.3613165)，[§4.6 Distributed Execution](https://arxiv.org/html/2309.06180v1#S4.SS6)：各 rank 处理同一批 token 位置，但仅保留所属 attention heads 的 KV。§4.1–4.2 解释 block table 等管理元数据。 |
| `accelerator, serving process, host, or communication fault` | `\cite{cao2026lumen,jayakody2026ghostserve}` | [LUMEN](https://arxiv.org/html/2606.17787v1)，§2 Failure model：GPU、进程、主机及跨节点通信故障在服务层表现为 worker 不可用；[GhostServe，MLSys 2026](https://proceedings.mlsys.org/paper_files/paper/2026/hash/d99e8e80a6c41e148db686918dd7eab3-Abstract-Conference.html) 支持长上下文服务的硬件／软件故障与 KV 状态恢复背景。LUMEN 当前按 arXiv 预印本引用。 |

## 补充的直接依据

| 插入位置 | Cite key | 支持内容 |
|---|---|---|
| runtime 按依赖释放调用、fork/join 段尾 | `lin2024parrot` | [Parrot，OSDI 2024](https://www.usenix.org/conference/osdi24/presentation/lin-chaofan)：暴露跨请求依赖，进行应用级服务调度。论文采用 DAG 作为本文工作流范围；并非声称所有 agent 程序天然无环。 |
| 后续 turn 复用匹配历史前缀 | `gao2024cachedattention,zheng2024sglang` | [CachedAttention，ATC 2024](https://www.usenix.org/conference/atc24/presentation/gao-bin-cost) 支持多轮历史 KV 保留；[SGLang，NeurIPS 2024](https://proceedings.neurips.cc/paper_files/paper/2024/hash/724be4472168f31ba1c9ac630f15dec8-Abstract-Conference.html) 支持 RadixAttention 的前缀 KV 复用。依赖前缀匹配与状态仍可用，不是无条件 cache-hit 保证。 |
| 无幸存 KV 时重新 prefill | `strati2024dejavu` | [DéjàVu，ICML 2024](https://proceedings.mlr.press/v235/strati24a.html)：生成推理是有状态的，状态丢失引入恢复成本；KV streaming / replication 支持故障恢复。 |
| 恢复已接受前缀 checkpoint，再重放其后 tokens | `strati2024dejavu,cao2026lumen` | DéjàVu 的 KV 复制；LUMEN §4.2 的完整页提交、有效前缀识别和缺失后缀重算。 |

共使用 8 个 cite key：原有 6 个，新增 2 个。`new-references.bib` 仅含新增条目；`background-citations.bib` 含本节使用的全部条目。它们供复制或审阅，主稿使用 `paper/references.bib`，无需同时加载这些子集以免重复 key。

## 保留为本文假设／定义的内容

- 工作流 DAG、已接受 tokens、已完成工具结果在故障 worker 之外保存，是 AegisKV 的恢复前提；引用不能代替实际持久化实现。
- 模型版本、并行配置、数值格式与布局一致，是本文直接复用／恢复的兼容性约束，不应推广成所有采用重分片／格式转换的系统都必须具有完全相同配置。
- “完整 checkpoint”及“partial copy 不能独立提供完整覆盖”是本文范围内的状态定义。仅有一部分层或 TP 对象，不能被图示为完整恢复能力。
- 本地主存／SSD 不应被画成自动跨主机故障域的幸存备份。新图只画逻辑 worker 边界，不虚构 host 拓扑或备份协议。

## 配图和主稿接入

- 新图 `fig:serving_model`：两条 fork/join 工作流 → ready requests → scheduler → 两个 TP2 model workers。B/E 与 C/F 混合到 worker 上；每个 rank 持有对应 KV shards。A1/A2、D1/D2 是同一协调 Agent 的不同 turn。底部显示后续 turn 的已缓存前缀与新增输入。
- 原 `agent-workflow-examples` 被这张新图替代，旧稿与旧图源保留。
- 旧故障统计与 KV 重建成本图仍被 Motivation 引用，因此将原 figure 环境移到 Motivation，对应数据与图注不变。故障统计保留生产训练集群／不可用记录的口径，不冒充 serving 故障率。
- WCT 定义随论证移至 Motivation 起始处，避免替换 Background 后术语失去定义。
- 图号由主稿编译结果确定，中文稿同步映射；英文正文按 label 引用，不手填图号。
