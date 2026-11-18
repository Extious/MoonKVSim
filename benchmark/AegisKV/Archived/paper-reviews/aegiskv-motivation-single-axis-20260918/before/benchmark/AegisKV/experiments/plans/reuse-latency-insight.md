# KV 复用层级的恢复延迟：Motivation 图设计

状态：2026-09-18 按用户最新指令暂停实机实验，Figure 2 先使用 AIConfigurator 数据与显式传输模型。已生成三模型 × 五种历史长度 × 三条路径的静态估计，并同步 Motivation 图文与 PDF。原生稀疏模型的同条件物理矩阵仍未完成，以下物理实验协议保留为后续计划，不能视为已执行。

## 当前交付：暂定估计版

- 数据与可运行脚本：[`reuse-aiconfigurator-a100`](../data/reuse-aiconfigurator-a100/README.md)。AIConfigurator 0.9.0，commit `4b9d9dc51e02b5e9d4acc3688f3edf41693834c6`；A100-SXM、vLLM 0.14.0、HYBRID、BF16、batch 1、TP/PP 1。
- 使用 Qwen3-4B、8B、14B 的固定官方配置。AIConfigurator 当前没有此任务所需的 MiniCPM4/NOSA 原生稀疏实现，因此不借用稠密模型曲线冒充这三种模型。
- 相同历史 `M`（8K/16K/32K/64K/128K），相同已知 64-token 尾部。HBM：`isl=M+64,prefix=M`；Recompute：`isl=M+64,prefix=0`，均查询 `static_ctx` 的完整算子和。DRAM：HBM 计算时间加整段历史 KV 的串行 H2D。终点相同；未计额外采样后的 decode step。
- 传输字节 = `2 × layers × kv_heads × head_dim × 2 × M`。单向带宽取 AIConfigurator `a100_sxm.yaml` 的 `pcie_bw=32e9 B/s`，是明确的假设，不是有效带宽实测；不计 DMA/分配/绑定开销或传输计算重叠。三路径都不含检测、排队、权重加载和故障前复制。
- 128K：HBM 35.0/39.4/58.7 ms，DRAM 639.0/643.3/729.8 ms，Recompute 31.35/34.63/49.61 s（按 4B/8B/14B 顺序）。DRAM–HBM 增量为 604.0/604.0/671.1 ms。15 个模型/长度点均通过工具的容量检查，但这不是物理运行成功证据。
- 64K、128K 形状超过固定模型配置中的 `max_position_embeddings=40960`；只评估计算代价，不宣称已完成 RoPE 扩展、长上下文精度或生产引擎正确性验证。估计没有文本输入、重复计时或置信区间。
- Figure 1(b)/(c) 按最新要求改用 trace `631738ac…` 第 20 组：4 分支，gap 91.242 s，持续时间 60–152 s。该组来自相同 fan-in 集合，但不是其 workflow-max，正文明确区分。成本口径不变，由 `motivation-compact-cc/estimate_costs.py` 查询精确 M+64；A1–A4 的 WCT loss 为 0 / 32.180 / 17.610 / 17.007 s。Figure 2 数据和图像本轮不变。

## 已进行的预检与停止范围

在用户改为静态估计之前，诊断作业 `153195` 已在 RTX 4090 上检查三模型的 8K+64 缓存路径。记录位于 `../native-sparse/20260918-reuse/`，仅用于正确性排查；没有启动正式配对矩阵或 A100 测量作业。缓存长度满足预期，但缓存批量尾部与整段前向的输出明显不同，此差异尚未定位或修复，因此旧 replay 数字不能直接当作共同恢复终点已验证的数据。该诊断不进入 Figure 2。按最新指令不继续实机实验。

## 在论文中的作用

建议用这张单栏图扩展当前 Figure 2（只展示 full-prefill），回答：同一请求状态下，备份避免了多少历史重算，历史 KV 驻留在接管 GPU 的 HBM 又比 DRAM 恢复减少多少等待？它为分层保护提供动机；System Design 的三个 Insight 继续分别讨论时间估计、稀疏模型适用性和 retry KV 预测。

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
- 图为单栏、按模型纵向排列的三小面板，共用横轴 `Context length (tokens)`、纵轴 `Recovery latency (ms)`；纵轴对数，颜色/线型一致区分三路径，保留绝对值。图注说明完整历史驻留、64-token 尾部、设备与统计单位。DRAM/HBM 差距小时保留原结果，正文报告毫秒差，不截断坐标夸大。
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

MiniCPM4 32K 的历史 prefill 为 4.695 s，64-token 缓存重放为 91.83 ms，均为现有各自实验的中位数。它们只能说明已有测量覆盖范围，不能与 Figure 6 的带宽假设拼成三条实测曲线。当前尚缺三种原生稀疏模型的同条件 DRAM 恢复数据和完整配对运行。正文现在插入的是上文明确标注的 Qwen 静态估计版，不能视为这项物理矩阵的结果。

原始结果建议保留字段：`model_revision, hardware_id, input_id, input_hash, context_tokens, tail_tokens, path, repetition, latency_ms, transferred_bytes, selector_state_bytes, correctness, status, failure_reason`。保留逐次值与失败记录，作图源必须能追溯到测量脚本和运行配置。
