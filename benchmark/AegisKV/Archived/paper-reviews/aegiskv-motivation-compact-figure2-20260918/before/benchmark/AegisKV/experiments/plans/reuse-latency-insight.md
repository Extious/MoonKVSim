# KV 复用层级的恢复延迟：Motivation 图设计

状态：2026-09-18 按用户指令继续采用 AIConfigurator CPU 静态估计，不进行实机实验。Figure 2 现延伸至各模型的上下文上限：共25个形状、75个路径值。原生稀疏模型的同条件物理矩阵仍未完成，以下物理协议保留为后续计划。

## 当前交付：每个模型的最大上下文

- 数据与脚本：[最大上下文矩阵](../data/reuse-aiconfigurator-max-context-h100/README.md)。四模型分别为 Qwen3-14B（YaRN，128K）、Llama-3.1-70B（128K）、Qwen3-235B-A22B-Instruct-2507（原生256K，扩展1,010,000）、DeepSeek-V3.2（官方开源配置160K）。官方配置和模型卡已按revision固定；上下文上限、默认配置和原生训练范围分别说明。
- 共同条件保留 H100-SXM80GiB、BF16、batch1、PP1、vLLM0.19.0、AIConfigurator0.9.0 HYBRID；TP依次1/4/16/32，两个MoE的EP16/32。不同GPU数不支持等资源排名。
- 横轴为总长度 C=M+64，在各自上限处结束，避免把“最大历史+尾部”画成支持范围内的点。HBM和DRAM均重建相同64-token尾部；DRAM完整历史传输按每rank64GB/s假设并发、无共享主机瓶颈、无传算重叠。
- Recompute统一使用8K连续分块，从空缓存开始，后续块使用已重建KV，全部路径排除不参与KV重建的词表投影。所有25个形状无静态容量告警，最大77.817GiB/卡；未作实机验证。此前整段Prefill容量告警保持在长上下文诊断中，不覆盖原记录。
- Qwen2507大于256K仅为全注意力成本外推，AIConfigurator未实现DCA位置处理或其稀疏内核加速。DSA性能表只覆盖32K总长度，较长形状与所有cached-prefix查询仍涉及外推/解析前缀修正。图注与正文明确这些限制；不把silicon标签或假设带宽当实测。
- 1,010,000总tokens下，Qwen2507全注意力估计为HBM70.162ms、DRAM829.634ms、分块Recompute219.951s。128K总长度下四模型范围为HBM22–56ms、DRAM155–357ms、分块Recompute14.5–21.0s。
- Figure2保持3.34×3.35inch单栏单坐标；颜色表示路径，线型/标记表示模型。图和Markdown、LaTeX、图注、PDF同步。Figure1资产和A100反事实数据保持原样。
- 原8K–128K矩阵及脚本冻结在 `reuse-aiconfigurator-architecture-h100`，更早A100矩阵同样保留。当前图只引用新矩阵。

## 已进行的预检与停止范围

在用户改为静态估计之前，诊断作业 `153195` 已在 RTX 4090 上检查三模型的 8K+64 缓存路径。记录位于 `../native-sparse/20260918-reuse/`，仅用于正确性排查；没有启动正式配对矩阵或 A100 测量作业。缓存长度满足预期，但缓存批量尾部与整段前向的输出明显不同，此差异尚未定位或修复，因此旧 replay 数字不能直接当作共同恢复终点已验证的数据。该诊断不进入 Figure 2。按最新指令不继续实机实验。

## 在论文中的作用

这张单栏图将原 Figure 2 的 full-prefill 代价扩展为三路径比较，回答：同一请求状态下，备份避免了多少历史重算，历史 KV 驻留在接管 GPU 的 HBM 又比 DRAM 恢复减少多少等待？它为分层保护提供动机；System Design 的三个 Insight 继续分别讨论时间估计、稀疏模型适用性和 retry KV 预测。

待检验的结论是：DRAM 备份可避免历史重算，HBM 驻留进一步减少暴露传输等待；增量受模型、上下文和传输/计算重叠影响。不能预设 DRAM–HBM 差距一定很大，也不能由这张单请求图直接推出有限 Peer 容量下的 WCT 收益。

## 同一计时终点

冻结一个请求的已提交历史 `M` 和已知但未提交的 64-token 尾部。三条路径使用同一模型、权重版本、输入 token、选择器、精度与接管设备，模型权重已加载。计时从恢复执行获准开始，到尾部的全部 KV 重建完成且可继续正常 decode 为止。

| 路径 | 起点状态 | 计时包含 |
|---|---|---|
| HBM reuse | 历史 KV 及选择器必要状态已在实际接管 GPU | 绑定/恢复状态、64-token 尾部前向；不是零延迟 |
| DRAM reuse | 相同历史状态仅在存活主机的 pinned DRAM | 实际 H2D、必要状态恢复、相同尾部前向；允许已实现的层间传输/计算重叠 |
| Recompute | 无可用历史状态，保留相同 token ID | 从空缓存重建历史与相同尾部；同一计时区间内执行并保留全部 KV |

这里的 HBM 曲线是**完整历史驻留**的参照，不等于 AegisKV 的有限热块 Peer 方案。主图固定 host-local DRAM；若要研究远端池，单列网络路径和实测竞争条件，不把 6.25 GB/s 或 25 GB/s 的假设当成传输测量。

检测、排队、故障前复制与模型加载不在这个微基准计时内，在图注中说明。冷状态若不影响尾部完成，可在终点后继续复制，但所有路径必须满足相同的继续 decode 正确性契约。

## 后续物理实验矩阵与作图（本轮不执行）

- 模型：MiniCPM4-8B、NOSA-1B、NOSA-3B。每种模型使用自身真实权重、层数、KV 格式与 native sparse 路径，不借用其他模型的重放时间。
- 主硬件：同一 A100 80GB PCIe、BF16、batch 1、独占测量；记录 GPU/CPU、NUMA、驱动、CUDA、框架、内核与模型 hash。若换成其他硬件，整组配对重测。
- 历史规模：8K、16K、32K、64K、128K；固定尾部 64 tokens。超出原生长度的模型需明确配置和有效性限制。OOM 或不支持的点保留为缺失原因，不外推为成功运行。
- 输入：至少 5 份固定文本/agent 历史，每个模型内三路径逐条配对；同一形状各自预热。每份输入每路径 5 次计时，顺序交错，重置缓存，同步 GPU。先求输入内计时中位数，再跨输入汇总；重复计时不是独立 workload。
- 核对缓存和选择器状态完整迁移、真实 H2D 字节、空缓存重算、计时内 CUDA 完成及后续输出一致性。不得把另一次 prefill 与 replay 中位数相加后称为单次恢复实测。
- 图为单栏单坐标图，横轴 `Context length (tokens)`、纵轴 `Recovery latency (ms)`；纵轴对数，颜色区分路径、线型及标记区分模型，保留绝对值。图注说明完整历史驻留、64-token 尾部、设备与统计单位。DRAM/HBM 差距小时保留原结果，正文报告毫秒差，不截断坐标夸大。
- 附加并发/带宽敏感性放 Evaluation；Figure 6 继续解释在 DRAM 路径上如何通过层序、预取和有限 Peer 驻留减少等待。

## 已有数据核对（2026-09-18）

输入均位于 `../native-sparse/20260915/`。

| 文件 | 已有证据 | 不能替代的测量 |
|---|---|---|
| `prefill-latency-minicpm4-8b-a100-152626.json` | A100 PCIe，6 个历史规模，保留 KV 的 native prefill，5 次计时 | 不是从空缓存恢复 M+64 的共同终点 |
| `replay-latency-minicpm4-8b-a100-152626.json` | 同型号 GPU，6 个历史规模 × 尾部 1/64/512，缓存已在 GPU，5 次计时 | 不含从 DRAM 恢复，也不含生产引擎绑定/接管开销 |
| `prefill-latency-nosa-{1b,3b}-retained-kv-151751.json` | RTX 4090 上的 native prefill | 缺对应的 A100 replay 与 DRAM 恢复 |
| `prefill-latency-nosa-8b-retained-kv-151751.json` | 失败运行及失败前的部分计时 | 不能当完整模型/长度曲线 |
| `measured-loading.json` | 权重加载 key 的校验报告 | 不是 KV H2D 延迟 |

MiniCPM4 32K 的历史 prefill 为 4.695 s，64-token 缓存重放为 91.83 ms，均为现有各自实验的中位数。它们只能说明已有测量覆盖范围，不能与 Figure 6 的带宽假设拼成三条实测曲线。当前尚缺三种原生稀疏模型的同条件 DRAM 恢复数据和完整配对运行。正文现在插入的是上文明确标注的 上述含 MoE/DSA 的 H100 静态估计版，不能视为这项物理矩阵的结果。

原始结果建议保留字段：`model_revision, hardware_id, input_id, input_hash, context_tokens, tail_tokens, path, repetition, latency_ms, transferred_bytes, selector_state_bytes, correctness, status, failure_reason`。保留逐次值与失败记录，作图源必须能追溯到测量脚本和运行配置。
