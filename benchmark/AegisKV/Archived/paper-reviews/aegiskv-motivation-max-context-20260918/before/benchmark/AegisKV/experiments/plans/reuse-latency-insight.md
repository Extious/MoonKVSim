# KV 复用层级的恢复延迟：Motivation 图设计

状态：2026-09-18 按用户最新指令暂停实机实验，Figure 2 先使用 AIConfigurator 数据与显式传输模型。已生成四模型 × 五种历史长度 × 三条路径的静态估计，并同步 Motivation 图文与 PDF。原生稀疏模型的同条件物理矩阵仍未完成，以下物理实验协议保留为后续计划，不能视为已执行。

## 当前交付：覆盖大规模、MoE 与稀疏注意力的估计版

- 数据与脚本：[`reuse-aiconfigurator-architecture-h100`](../data/reuse-aiconfigurator-architecture-h100/README.md)。AIConfigurator 0.9.0，commit `4b9d9dc51e02b5e9d4acc3688f3edf41693834c6`；H100-SXM 80 GiB、vLLM 0.19.0、HYBRID、batch 1、PP 1，主权重与 KV 均按 BF16。仅 CPU 静态查询，未启动实机实验。
- Qwen3-14B：稠密 GQA，TP 1；Llama-3.1-70B：稠密 GQA，TP 4；Qwen3-235B-A22B：235B 总量 / 22B 激活，稠密 GQA + MoE，TP/EP 16；DeepSeek-V3.2：671B 总量 / 37B 激活，DSA 稀疏注意力 + MoE，TP/EP 32。MoE 不等于稀疏注意力。四模型分别使用 1/4/16/32 张 GPU，只在同模型的三个路径间做配对比较，不能作等资源速度排名。
- H100 的 DSA 模块表包含相应 BF16 组合；A100 没有同样的 DSA 表和原生 FP8 索引器吞吐条件，因此本图统一采用 H100。原 `reuse-aiconfigurator-a100` 和 `reuse-aiconfigurator-multifamily-a100` 保留为历史数据，不混入当前曲线。
- 相同历史 M=8K/16K/32K/64K/128K，相同已知 64-token 尾部。HBM 为 `isl=M+64,prefix=M`；Recompute 为 `isl=M+64,prefix=0`；包含完整算子和及 GPU 通信。DSA 实际查询 `ContextDSAModule`，没有用稠密曲线替代。
- DRAM = 相同尾部时间 + 每 rank 所需历史状态 / 64e9 B/s。各 rank 假设并发恢复、主机无共享瓶颈、无传输计算重叠；64 GB/s 是 H100 YAML 的每 GPU 带宽假设，不是实测。GQA 按分片和头复制计算；DSA 每 rank 包含 BF16 MLA latent、RoPE key、FP8 indexer key 与 FP32 scale，不能直接套用 GQA 字节公式或只传 top-k 项。
- 128K，按上列模型顺序：HBM 22.208/24.307/56.362/52.333 ms；DRAM 357.752/192.079/154.928/212.740 ms；Recompute 14.084/15.100/12.279/20.059 s。所有20个形状均无最终容量警告，最大估计74.884 GiB。Qwen235B初始TP8在128K估计84.535 GiB，失败记录保留在 `capacity-initial-tp8.json`，最终TP16估计57.290 GiB。
- 配置长度：Qwen14B及235B为40960，Llama70B为131072，DeepSeek为163840；逐行按M+64保存超限标志。DSA性能表最大总长度为32768，因此32K历史加尾部及更长点涉及外推；HBM尾部采用SDK解析前缀修正。`op_sources` 的 `silicon` 只指底层表来源，不代表请求级恢复实测，尤其不能掩盖外推和前缀修正。
- 图为3.34×3.35 inch单栏单坐标，颜色表示三条恢复路径、线型/标记表示四模型，共60个值。保留曲线交叉、重合及DSA尾部时间的轻微非单调性；不为了规模趋势平滑。
- Figure 1(b)/(c) 保持 `631738ac…` 第20组、4分支、gap91.242 s；成本仍为已冻结 Qwen3-14B/A100/BF16/TP1/M+64，最大WCT loss32.180 s。已删除其与当前H100 Figure2“配置相同”的说法，数值与图像资产不变。

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
