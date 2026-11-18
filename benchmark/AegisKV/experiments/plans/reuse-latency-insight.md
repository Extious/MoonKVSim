# KV 复用与 Prefill 填充时间：Motivation 图设计

共享文件系统四路径完整实测已完成。作业 **1517208** 在同一次 2×A100-PCIe-40GB 分配测量 Qwen2.5-7B-Instruct-1M、TP2、BF16、batch1。DRAM 和 Shared FS 都不与计算重叠。Shared FS 为实际 DPC 文件系统，直接读取真实历史 KV，再串行 H2D 和 1-token EXTEND；不是 SSD 介质测量。Linux 文件页在读前/后均未驻留，但 DPC/服务端缓存不受控。

| 总上下文 | HBM (s) | DRAM，无重叠 (s) | Shared FS，无重叠 (s) | Full Prefill (s) |
|---|---:|---:|---:|---:|
| 8192 | 0.090570 | 0.101757 | 0.183352 | 0.661433 |
| 65536 | 0.550348 | 0.680444 | 1.201179 | 20.125282 |
| 262144 | 0.893231 | 1.259789 | 3.451808 | 96.329280 |
| 1010000 | 1.305004 | 2.663166 | 10.156143 | 571.212672 |

HBM/DRAM 各三次取中位数和 min–max；Shared FS/Full Prefill 各一次，共 32 次正式计时，一个固定合成文本流。所有恢复、全文件哈希和串行时序校验通过；末尾 KV 文件已删除且作业已退出。原三路径 1517055 和早期失败结果保留，不与本次样本混合。

协议：[SHAREDFS_PROTOCOL.md](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/SHAREDFS_PROTOCOL.md)。原始数据和校验：[1517208](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1517208)。成本面板为 Figure 1(c)，更新 Markdown、LaTeX 和 canonical main.pdf。

累计实际使用 18227 GPU·秒（5.0631 GPU·小时），当前台账上限 5.5 GPU·小时。

## 历史：稀疏三路径完整矩阵

状态（2026-09-20）：**稀疏三路径完整实测已完成并更新论文。** 用户最新要求 DRAM 仅使用无 Overlap 路径。作业 **1517055** 在同一次 2×A100-PCIE-40GB 分配上完成 8K–1.01M，Slurm 为 COMPLETED；使用 Qwen2.5-7B-Instruct-1M、TP2、BF16、batch1，C=M+1。图中没有重叠 DRAM 曲线。

| 总上下文 | HBM reuse (s) | DRAM reuse，无重叠 (s) | Full Prefill (s) |
|---|---:|---:|---:|
| 8,192 | 0.087696 | 0.098522 | 0.664835 |
| 65,536 | 0.542814 | 0.649302 | 19.768273 |
| 262,144 | 0.848706 | 1.183545 | 95.996849 |
| 1,010,000 | 1.265548 | 2.516522 | 565.933926 |

HBM 相对串行 DRAM 在 1.01M 降低延迟 **49.71%**。三条路径都采用同一 MInference vertical/slash 配置与 DCA；请求长度超过 32K 时包括最后单 token 在内都使用稀疏 EXTEND。8K 使用 grouped dense DCA。Full Prefill 以至多 8K 分块生成相同历史，再执行同一末尾 token；HBM 和 DRAM 复用这份历史 KV。DRAM 在计时内搬运全部 M-token KV，复制同步后才计算。终点均为模型主体完成且全部 C-token KV 就绪，不含 lm_head。

**验证与样本。** 28 次正式计时、8 次复用预热均成功。HBM/DRAM 各三次正式计时，中位数与 min–max；Full Prefill 各长度一次；只有一个固定重复文本流。两 rank 各七组算子检查包含 1M／8K-query 最大形状，与原始稀疏算子的最大差值均为 0。64K 完整模型参考的 hidden 和新 KV 差值为 0；各长度检查新 KV、hidden、greedy token，以及复用后的完整历史 KV 逐字节一致性。256K／1.01M 不另跑完整 Prefill 预热，算子预检和短前向预热已披露。这些检查不构成长上下文任务质量评估。

**实现与失败保留。** 直接共享 GQA K/V，去掉重复展开副本；前缀每组最多两个 query heads，单 query 合并全部 heads；稀疏索引生成后及时释放分数张量及视图，使用 expandable CUDA allocator segments。1517028 在原始算子参考校验时 OOM，1517033 在 1M Full Prefill 的稀疏选择器处 OOM；均保留失败及部分结果。1516928、1517015 和 1517033 的 overlap 结果只作历史诊断。当前图全部来自 1517055，没有拼接短测或失败运行的数据。

**与旧 dense 结果的关系。** 此前 1516685 的 64K／256K／1.01M Full Prefill 为 7.49／58.76／655.41 s，本次为 19.77／96.00／565.93 s。因此这套分块稀疏实现并非在所有长度都更快。两组来自不同分配和实现配置，不能当作同次配对消融或宣称普适加速；当前图只回答同一稀疏配置下的 KV 复用比较。

累计实际用量 **15882 GPU·秒（4.4117 GPU·小时）**，低于最新总上限 **5.5 GPU·小时**；本轮新增使用 1.0306 GPU·小时，剩余总额度 1.0883 GPU·小时。所有本实验作业均已退出。

[协议与最新选取要求](../data/reuse-physical-qwen25-1m/SPARSE_OVERLAP_PROTOCOL.md)、[三路径 CSV](../data/reuse-physical-qwen25-1m/blsc/results/1517055/published-three-paths.csv)、[完整原始记录](../data/reuse-physical-qwen25-1m/blsc/results/1517055/trials.jsonl)、[发布校验](../data/reuse-physical-qwen25-1m/blsc/results/1517055/publication-validation.json)。当前成本面板为 Figure 1(c)，Markdown、LaTeX、图注和 `paper/main.pdf` 已同步。

## 历史：grouped dense 1-token 完整矩阵

状态（2026-09-20）：**优化后的 1-token Prefill 完整矩阵已完成，成本图已切换为本次完整实测。** 作业 **1516685** 同一次分配的 2×A100-PCIE-40GB、TP2、BF16、batch1，测量8K、64K、256K、1,010,000，总上下文C=M+1。三条路径统一使用SGLang 0.5.10rc0的显式分组head DCA，修正多head LSE布局，固定num_splits=1、pack_gqa=False，关闭稀疏加速。未修改已安装框架，源码哈希与快照已归档。

| 总上下文 | HBM reuse (s) | DRAM reuse (s) | Full prefill (s) | HBM 相对 DRAM 降低延迟 |
|---|---:|---:|---:|---:|
| 8,192 | 0.08535 | 0.09690 | 0.75896 | 11.92% |
| 65,536 | 0.10138 | 0.19175 | 7.48964 | 47.13% |
| 262,144 | 0.32260 | 0.67825 | 58.76442 | 52.44% |
| 1,010,000 | 1.13897 | 2.51615 | 655.41018 | 54.73% |

HBM/DRAM各三次正式计时取中位数、误差线为min–max；Full prefill每长度一次，一个固定重复文本流。DRAM实际传输M个token的KV后再做相同1-token EXTEND，无传算重叠；计时终点为同步后的模型主体forward完成、全部C个token的KV可用，不含lm_head。完整HBM驻留不是有限Peer策略。

所有28次正式计时及配对校验通过。原生完整模型参考覆盖8K/64K，同历史KV上的原生/优化1-token比较覆盖全部长度；这些检查中KV和hidden最大绝对差值为 **0**，greedy token一致。每rank的八种随机算子形状覆盖DCA分块边界及1M单query。长历史每个位置没有另做原生完整重建，也未评估长上下文模型质量。

预热如实区分：短kernel和算子检查先行；8K/64K额外有原生完整Prefill预运行；256K/1.01M没有重复完整上下文预热，完整Prefill可能含首次形状相关开销。不可将计时重复当成独立workload或将范围当置信区间。

原生1-token矩阵1516148、旧64-token矩阵1516025、首个未通过真实模型校验的自动split候选1516661，以及通过验证的短pilot1516669均独立保留。原生/优化比较来自不同分配，未混合为同次重复样本。独立随机BF16带宽1516171仍为HBM1079.20GB/s、pinned H2D23.98GB/s，它不是整个Prefill的加速比。

最终累计实际用量 **12172 GPU·秒（3.3811 GPU·小时）**，包括资源检查、加载、失败、pilot和全部测量，低于用户确认的 **3.5 GPU·小时**；剩余 **428 GPU·秒**，该实验无运行或等待作业。1516685初始硬时限15分钟；在既有总预算内尝试延至17分钟被Slurm拒绝，时限未改变。

调度退出与数据完成分别记录：Slurm的批处理预终止警告出现在1M预热期间，worker继续完成全部正式计时及校验，并于10:03:58 UTC写入原始`COMPLETE`；延后的batch TERM trap在10:04:03 UTC退出，Slurm最终为FAILED/124。未重标调度状态，未伪造完成标记；全部28次正式记录、四个context标记、原始完整标记及哈希均通过独立审计，见`termination-audit.json`。无额外GPU重跑。

[优化说明与失败记录](../data/reuse-physical-qwen25-1m/OPTIMIZATION.md)、[完整矩阵](../data/reuse-physical-qwen25-1m/blsc/results/1516685/measured.json)、[CSV](../data/reuse-physical-qwen25-1m/blsc/results/1516685/measured.csv)、[逐次计时](../data/reuse-physical-qwen25-1m/blsc/results/1516685/trials.jsonl)、[发布校验](../data/reuse-physical-qwen25-1m/blsc/results/1516685/publication-validation.json)、[与原生实现的独立运行对照](../data/reuse-physical-qwen25-1m/blsc/results/1516685/native-comparison.json)。

## 历史：原生 1-token 完整矩阵

状态（2026-09-20）：**1-token Prefill 完整矩阵已完成并用于更新论文成本图。** 作业 1516148 同次分配、2×A100-PCIE-40GB、TP2、BF16、SGLang 原生 DCA，C=M+1；HBM/DRAM 仅做一个新 token 的 EXTEND，Full prefill 从空 KV 填充全部 C。四长度共 28 次正式计时，全部新 token KV、hidden 和 DECODE hidden 最大绝对误差为 0，greedy token 一致。HBM/DRAM 各三次取中位数；Full prefill 每长度一次。完整上下文预热限制见协议。

| 总上下文 | HBM reuse (s) | DRAM reuse (s) | Full prefill (s) |
|---|---:|---:|---:|
| 8,192 | 0.287 | 0.296 | 1.036 |
| 65,536 | 1.110 | 1.189 | 10.586 |
| 262,144 | 4.238 | 4.550 | 91.733 |
| 1,010,000 | 15.785 | 16.989 | 1089.444 |

随机 BF16 的单卡 1 GiB 带宽复测 1516171：**HBM 1079.20 GB/s，pinned H2D 23.98 GB/s，相差45.00倍**。此前常量数据 1516138 独立保留，不用其61.54倍作为主结果。纯带宽不等于模型加速比。

累计计费 **9958 GPU·秒（2.7661 GPU·小时）**，含所有加载、失败、pilot及带宽复测，低于最新授权 **3 GPU·小时**；所有实验作业已结束，剩842 GPU·秒。

[新协议](../data/reuse-physical-qwen25-1m/PREFILL_ONE_PROTOCOL.md)、[完整矩阵 JSON](../data/reuse-physical-qwen25-1m/blsc/results/1516148/measured.json)、[CSV](../data/reuse-physical-qwen25-1m/blsc/results/1516148/measured.csv)、[原始计时](../data/reuse-physical-qwen25-1m/blsc/results/1516148/trials.jsonl)、[发布前校验](../data/reuse-physical-qwen25-1m/blsc/results/1516148/publication-validation.json)、[随机数据带宽](../data/reuse-physical-qwen25-1m/blsc/results/1516171/bandwidth.json)。旧64-token实验及全部失败记录保留于下文，不作为当前口径。

## 历史协议及前期计划

# KV 复用层级的恢复延迟：Motivation 图设计

> 新协议（2026-09-20）：用户将指标改为 **Prefill 填充 KV 的时间**，不是故障恢复尾部时间。HBM/DRAM 复用 M=C−1 个 token 的 KV 后只做 1-token EXTEND；空缓存 Prefill 填充 C 个 token。旧 64-token 曲线保留历史标签，等待新矩阵替换，不能直接重标或除以 64。另行比较 HBM 读与 pinned H2D 的实测带宽。新脚本、执行预算和终点定义见 [1-token 协议](../data/reuse-physical-qwen25-1m/PREFILL_ONE_PROTOCOL.md)。


状态（2026-09-20）：**BLSC-A100 实测完成并更新到论文。** 同一次 TP2 分配完成 Qwen2.5-7B-Instruct-1M 的 8K、64K、256K、1,010,000 三路径配对，共 12 个正式点；每点单输入、单次计时，预热和正确性检查通过。1,010,000 tokens 的 HBM/DRAM/Recompute 分别为 15.895/17.373/1088.527 秒。原 Figure 2 恢复成本资产现位于 Figure 1(c)，Markdown、LaTeX、图注与 `paper/main.pdf` 同步。累计实际用量 1.846 GPU·小时，未超授权 2 GPU·小时，实验作业均已结束。[数据、协议与预算记录](../data/reuse-physical-qwen25-1m/README.md)。下述四模型 AIConfigurator 版本保留作历史记录，未改标实测。

最终预算调整（2026-09-20）：累计上限 2 GPU·小时。1516002 在 8K–128K 获得五个完整上下文、每路径三次计时，随后为最大上下文让出预算。1516025 使用相同模型/精度/TP 配置，在一次新分配内测 8K、64K、256K、1,010,000，单输入、每路径单次正式计时；参考构造作 Recompute 预热，其他路径分别预热。固定 M/64 分块边界，保留普通合并尾部分块的失败诊断。完整数据最终以测量目录为准，不能将不同作业的数据悄悄拼接。当前论文另一任务已将原 Figure 2 成本图移至 Figure 1(c)，按资产 `recovery-cost.pdf` 更新，保留新编排。

## 归档静态版本：每个模型的最大上下文

- 数据与脚本：[最大上下文矩阵](../data/reuse-aiconfigurator-max-context-h100/README.md)。四模型分别为 Qwen3-14B（YaRN，128K）、Llama-3.1-70B（128K）、Qwen3-235B-A22B-Instruct-2507（原生256K，扩展1,010,000）、DeepSeek-V3.2（官方开源配置160K）。官方配置和模型卡已按revision固定；上下文上限、默认配置和原生训练范围分别说明。
- 共同条件保留 H100-SXM80GiB、BF16、batch1、PP1、vLLM0.19.0、AIConfigurator0.9.0 HYBRID；TP依次1/4/16/32，两个MoE的EP16/32。不同GPU数不支持等资源排名。
- 横轴为总长度 C=M+64，在各自上限处结束，避免把“最大历史+尾部”画成支持范围内的点。HBM和DRAM均重建相同64-token尾部；DRAM完整历史传输按每rank64GB/s假设并发、无共享主机瓶颈、无传算重叠。
- Recompute统一使用8K连续分块，从空缓存开始，后续块使用已重建KV，全部路径排除不参与KV重建的词表投影。所有25个形状无静态容量告警，最大77.817GiB/卡；未作实机验证。此前整段Prefill容量告警保持在长上下文诊断中，不覆盖原记录。
- Qwen2507大于256K仅为全注意力成本外推，AIConfigurator未实现DCA位置处理或其稀疏内核加速。DSA性能表只覆盖32K总长度，较长形状与所有cached-prefix查询仍涉及外推/解析前缀修正。图注与正文明确这些限制；不把silicon标签或假设带宽当实测。
- 1,010,000总tokens下，Qwen2507全注意力估计为HBM70.162ms、DRAM829.634ms、分块Recompute219.951s。128K总长度下四模型范围为HBM22–56ms、DRAM155–357ms、分块Recompute14.5–21.0s。
- Figure2保持3.34×2.35inch单栏单坐标；颜色表示路径，线型/标记表示模型。图和Markdown、LaTeX、图注、PDF同步。Figure1资产和A100反事实数据保持原样。
- 原8K–128K矩阵及脚本冻结在 `reuse-aiconfigurator-architecture-h100`，更早A100矩阵同样保留。该历史图仅引用这一静态矩阵。

## 已进行的预检与停止范围

此前诊断作业 `153195` 在 RTX 4090 上检查三种原生稀疏模型的 8K+64 缓存路径。记录位于 `../native-sparse/20260918-reuse/`，仅用于正确性排查。缓存长度满足预期，但缓存批量尾部与整段前向的输出明显不同，尚未定位或修复，因此旧 replay 数字不能直接当作共同恢复终点已验证的数据。该诊断不进入 Figure 2。本轮另行测量用户指定的 Qwen2.5-7B-Instruct-1M，不将旧诊断数据并入。

## 在论文中的作用

恢复成本图将原 full-prefill 代价扩展为三路径比较；当前编排为 Figure 1(c)，回答：同一请求状态下，备份避免了多少历史重算，历史 KV 驻留在接管 GPU 的 HBM 又比 DRAM 恢复减少多少等待？它为分层保护提供动机；System Design 的三个 Insight 继续分别讨论时间估计、稀疏模型适用性和 retry KV 预测。

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

## 其他原生稀疏模型的候选物理矩阵（本轮先执行上述 Qwen 模型）

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

MiniCPM4 32K 的历史 prefill 为 4.695 s，64-token 缓存重放为 91.83 ms，均为现有各自实验的中位数。它们只能说明已有测量覆盖范围，不能与 Figure 6 的带宽假设拼成三条实测曲线。当前尚缺三种原生稀疏模型的同条件 DRAM 恢复数据和完整配对运行。上述含 MoE/DSA 的 H100 静态估计已归档；当前正文恢复成本图采用另行测量的 Qwen2.5-7B-Instruct-1M，不能视为这三个原生稀疏模型的实测矩阵。

原始结果建议保留字段：`model_revision, hardware_id, input_id, input_hash, context_tokens, tail_tokens, path, repetition, latency_ms, transferred_bytes, selector_state_bytes, correctness, status, failure_reason`。保留逐次值与失败记录，作图源必须能追溯到测量脚本和运行配置。
