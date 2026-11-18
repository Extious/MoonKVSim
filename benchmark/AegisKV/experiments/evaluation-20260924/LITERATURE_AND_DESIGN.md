# AegisKV Evaluation：原文依据、比较契约与实验矩阵

核验日期：2026-09-24。本文是**实验设计依据**，不将推荐矩阵计作已执行实验，不引用其他系统的性能数字作为 AegisKV 结果。所有主张最终以本目录实际运行的 manifests、配置、日志、统计和图表为准。当前任务只做模拟；严谨的模拟可以支持有边界的机制和系统结论，但文献学习、实验数量或模型评审的同意均不能保证 EuroSys 接收。

## 1. 当前设计与本次 Evaluation 的问题

本次读到的权威输入是 `paper/system_design.tex` 和 `AGENTS.md` 最后两个 2026-09-24 修订段。读取时 SHA-256：

```
system_design.tex cfb92dcfc6c40c7d3a5c996d1628cc94318af863b74b7f04b6546a714fa5fff3
AGENTS.md         da2837c53731044f094a4dd4fad20bcb30ffb1bb1f7fcad4d05ea191548c815f
```

实现和实验必须对应以下机制，而不是历史三层互斥、partial-DRAM、租金或 complete-plan J(P) 版本：

1. 固定、预先知道的 Agent-task DAG；Agent 内 invocation 数未知。每次 invocation 提交时做一次因果剩余时长预测，按提交时间更新剩余量；失效估计触发整个 workflow 零 Slack。
2. `E_a=max(T_a−s_a,0)>λ` 才保护 Agent，有限 Peer DRAM 按 E 排序，完整 checkpoint 包括全部层、TP shards 和必要元数据。
3. `Z=256`，物理 KV block=64 tokens；只在 checkpoint 更新 Top-K，逐 token 仅累加按 query/head union 定义的计数。更新含 decay β、入集合阈值 1+ε，Peer 本地 DRAM→HBM 复制新成员，元数据也计费。
4. 前 L 层的 Top-K 额外驻留 HBM；L 由每次恢复的有效 H2D 带宽离线确定。恢复中实际 demand miss 必须从 DRAM 补取，不能把 Top-K 当作全部需求。
5. HBM admission 按增量 `G_a=[T_a^D−s_a]^+−[T_a^H−s_a]^+`，不是只按 `[T_a^D−s_a]^+`；AIMD 调节总配额，缩小时按低 G 丢弃额外 HBM 副本，保留完整 DRAM。
6. 执行/retry 位于不同保护故障域；一个 worker/host 失败影响其全部请求和资源。HBM、DRAM、pending copy、metadata、workspace、leases、foreground reservations 均有物理账本。

主问题为：**相同资源、负载和故障条件下，两级选择是否降低故障后的 workflow completion time，同时控制无故障服务开销？** DRAM 避免 full reconstruction 与 HBM 减少暴露传输等待是两项独立贡献；后者必须相对匹配的 DRAM-only 对照证明。

历史文件 `experiments/eurosys27/EVALUATION_LITERATURE_20260923.md` 的文献部分可作定位线索，但其“当前设计”与若干实验项仍含旧租金/三层/segment 假设。本文不继承这些设计项。

## 2. EuroSys 官方规范与最佳论文的可借鉴方法

### 2.1 当前投稿规范

[EuroSys 2027 官方 CFP，Submission Instructions](https://2027.eurosys.org/cfp.html) 在本次核验时规定：技术内容最多 12 页，参考文献页不限；补充材料单独上传、审稿人可不读，主文须自洽。纸张 A4/US Letter，内容区 178×229 mm，两栏间距至少 8 mm；正文、图中文字和图注至少 10 pt，行距至少 12 pt；灰度打印不放大也应可读，所有页编号。使用双盲提交及匿名 artifact 链接；AI 工具使用须按 CFP 披露。秋季 abstract 截止 2026-09-17、全文截止 2026-09-24，均为 AoE。当前任务不修改前文，故完整稿格式是否合规应单列审计，不能通过压缩 Evaluation 字体解决。

### 2.2 实际阅读的原文与适配

原文的实验规模是方法案例，不能原样移植为本项目可信度门槛。下表的“适配”是本文建议。未核实的奖项不标为最佳论文；arXiv 版本不冒称已被会议录用。

| 原文、版本与定位 | 实际实验方法 | 对当前 AegisKV 的适配 |
|---|---|---|
| **CacheBlend，EuroSys 2025 Best Paper**。[官方奖项](https://2025.eurosys.org/awards.html)；[作者 arXiv v2，§7.1–7.3](https://arxiv.org/html/2405.16444v2#S7) | 三种模型、四类任务；比较 full recompute、prefix/full reuse 等；同时评价延迟和生成质量，另扫请求率、chunk 数/长、batch、重算比例与存储条件。 | 采用 E2E→机制→操作范围组织。AegisKV 不改 attention/输出语义，不能借其近似融合策略作为“同语义 fault tolerance”基线。 |
| **SpInfer，EuroSys 2025 Best Paper**。[官方奖项](https://2025.eurosys.org/awards.html)；[作者 PDF，§5，PDF pp.10–12](https://www.cse.ust.hk/~weiwa/papers/eurosys25-fall-spinfer.pdf)；[作者 artifact](https://github.com/HPMLL/SpInfer_EuroSys25) | kernel 与 E2E 分开；两种 GPU 平台；kernel ablation 解释底层瓶颈，E2E 改 batch、GPU 数和输出长度；E2E 取 100 次平均。 | native demand/overlap 诊断和 workflow recovery 分开，不把访问集中度或 kernel 加速直接当作 WCT 改善。本文不把重复同一确定性模拟 100 次当独立样本。 |
| **Avicenna，EuroSys 2026 Best Paper**。[官方奖项](https://2026.eurosys.org/eurosys-awards.html)；[作者 PDF，§5，PDF pp.9–13；附录 B p.23](https://khiemn.com/publication/avicenna/avicenna-eurosys26.pdf) | 同代码基线；normal-case、故障种类/强度、优化贡献、目标函数和吞吐–延迟分别评估；两个地域布局；给强基线快速切换能力；明确保留吞吐代价。 | 公平 baseline 不应因人为较慢 detection/retry 而输；F0 与 failure 两边都报告；保留 dense、快 H2D、低负载下的小收益/负收益。 |
| **LUMEN，arXiv:2606.17787v1**。[§6.1–6.3](https://arxiv.org/html/2606.17787v1#S6) | prototype 与 Vidur simulator 分开；No-Failure、Stop-and-Restart、Fixed-Checkpointing；ShareGPT/Splitwise；五次运行；mean/p99 TTFT/TPOT；中断与未中断请求拆分；负载、失败数、固定失败数/比例扩容。 | 匹配 F0、故障影响窗口和 collateral latency 必须有。LUMEN 含 load-aware placement、locality-aware retry 和 draft-assisted progressive recovery，不能把只移植前两项的模拟称完整 LUMEN。 |
| **DéjàVu，ICML 2024**。[作者 PDF，§5.2.3，PDF pp.8–9](https://www.pdl.cmu.edu/PDL-FTP/BigLearning/2024-icml-strati.pdf)；[arXiv](https://arxiv.org/abs/2403.01876) | 故障部分用 OPT-66B、四 pipeline stages、microbatch=8；同时展示按 token 进度的累计延迟，以及多次 wall-clock failure 后的完成过程。 | 故障逻辑进度对齐与集群 wall-clock kill 是两个互补实验；checkpoint-and-replay 策略可借鉴，但不能把共同 runtime 的全量 DRAM 策略标原系统复现。 |
| **Mooncake，FAST 2025**。[官方 PDF，§5.1–5.4，PDF pp.9–13](https://www.usenix.org/system/files/fast25-qin.pdf) | 两个生产 trace 加 synthetic；joint TTFT/TBT SLO、有效请求比例、cache hit、prefill GPU time、transfer；请求序列容量分析与实际缓存运行分开。TBT 特指最慢 10% token intervals 的均值。 | 使用原始分母的 completed/SLO goodput，严格分开 token-hit、request-hit 和潜在 prefix 覆盖。不能把它的 TBT 当通常 TPOT，也不能把 DRAM-only adaptation 叫 Mooncake 复现。 |
| **Llumnix，OSDI 2024**。[官方 PDF，§6.1–6.5，PDF pp.10–15](https://www.usenix.org/system/files/osdi24-sun-biao.pdf) | 两种模型大小/TP，16-GPU testbed；迁移机制与 serving、priority、autoscale 分解；synthetic/trace workload，含尾延迟与突发。 | 同样资源和 foreground scheduler；动态 HBM budget 要用负载阶跃/突发解释，不能只展示 recovery 快而略去正常服务排队。 |
| **KVFlow，作者 arXiv:2507.07400v1**。[§4.1–4.2](https://arxiv.org/html/2507.07400v1#S4) | 单 workflow 的 10-Agent sequential synthetic prefix workload；Llama-3.1-8B/A10G 与 Qwen2.5-32B/H100；再测并发 workflow；控制固定与动态 prompt 长度。 | sequential/cache reuse 是重要负对照：没有并行 slack 时 O1 收益可能消失。其 prefix eviction/prefetch 为健康 serving，对故障需接上统一 recovery 才能比较。 |
| **TOPAS，arXiv:2608.25523v1**。[§V-A–V-C](https://arxiv.org/html/2608.25523v1#S5) | 同 SGLang backend、同 sampled Poisson arrival；Qwen2.5-32B；chain/fork-join/wide synthetic DAG，加两个 MetaGPT 工作流；mean/p99 JCT 与组件消融。 | 整个 workflow 到达过程固定，拓扑干预保持工作量可比；真实 prompt 和结构化 DAG 各有角色。不能把 dynamic/tool 工作流不经转换称本设计的固定 Agent-task DAG。 |
| **Autellix，作者 arXiv:2502.13965v1**。[§6.1–6.5](https://arxiv.org/html/2502.13965v1#S6) | 从 ShareGPT/BFCL/LATS 按 program 而非单 call 抽样，另有 mixed；多种模型/TP；共同 max batch；强 vLLM-opt 与 MLFQ；program latency、tails、waiting breakdown。 | 主统计单位是 workflow/program。主指标用原始 WCT，补 token-normalized 值时不能替代 WCT 或掩盖长工作流。强前台策略必须在各 protection policy 间一致。 |
| **Vidur，MLSys 2024**。[会议 PDF，§4–6](https://proceedings.mlsys.org/paper_files/paper/2024/file/b74a8de47d2b3c928360e0a011f48351-Paper-Conference.pdf)；[作者代码](https://github.com/microsoft/vidur) | operator profiling 加 runtime prediction，细化 batching/scheduling；单独验证 simulator fidelity，再做大规模 deployment search；不同 model/trace 可有不同最优配置。 | 线性每 token 时间和 FCFS 队列不足以验证实际 serving saturation。采用现有 profile 仍需核对模型/设备/TP/batch 范围；误差和外推必须显式保存。 |

## 3. Trace 与模型选择：先过准入条件，再扩大数量

### 3.1 Trace 的三种用途

| 用途 | 首选内容 | 准入条件与限制 |
|---|---|---|
| 主 WCT replay | 能证明注册时已知固定 Agent-task DAG 的真实 workflow；保留完整 invocation histories | 必须有 workflow/Agent IDs、显式依赖、提交/完成、tokens 或可验证 prefix IDs。不能依据时间重叠补造依赖，也不能把事后完整 DAG 作为在线已知信息。每 workflow 原样执行一次。 |
| 决策机制控制 | chain、balanced fork-join、skewed fork-join、wide、co-bottleneck 五类构造 DAG | 明确 synthetic；对照固定 token work、prefix locality、资源；分别改变 slack 或 fan-out。含同 Agent 多调用，但不能由此自行假定 exact-prefix reuse。 |
| 背景流量/外部有效性 | Azure Splitwise、Mooncake request traces、CC Weka agentic traces | 原 schema 无 DAG 时只作为 request/background trace；动态图或工具等待应标观察/转换范围，不能声称固定 DAG 的自然端到端 replay。 |

已核实的两个公开数据边界：

- [CC Weka 官方数据卡](https://huggingface.co/datasets/semianalysisai/cc-traces-weka-062126) 给出 393 sessions、98,827 model requests，以及 main/subagent 信息；`in` 是 64-token hash-block 数乘 64，不是真 tokenizer count。卡中记录了重缓存长尾过计和筛除 >990,016 的策略；它也讨论动态子 Agent 的标注问题。因此它适合真实 invocation/history 分布研究，但主 DAG 语义、长度误差和静态化转换需逐项审计。
- [Azure Splitwise 原始说明](https://github.com/Azure/AzurePublicDataset/blob/master/AzureLLMInferenceDataset2023.md) 只有 timestamp、context token count、generated token count，因隐私不含 prompt。适合真实到达和长度驱动背景流量，不能验证 exact-prefix identity、semantic predictor 或 Agent-task DAG。

建议主 WCT 至少覆盖两种经过审计的真实 family，加一个结构干预 family；若现有数据只能支持一类，不制造第二类标签。报告可用/排除 workflow 数和原因、实际 invocation 数、Agent 数、每 Agent 调用数、fan-out/depth、输入/输出/历史长度 p50/p95/max，以及潜在与实际 token-hit。源 trace 的绝对完成时间含原 serving/工具行为，不应直接当新模型的 GPU service time。

固定 Agent DAG 但未知 invocation count 的训练/测试管线中，最终调用总数、未来输出长度、最终结束时间只作为标签；任何运行时 predictor 输入不得包含它们。跨 Agent completion 的依赖可以是固定结构，Agent 内新增调用必须随因果执行提交。非模型间隙如需保留，只能作为明确的外生等待，不虚构工具执行机制。

**本次已落盘资产审计。** 已读取 [FanOutQA bundle](inputs/fanoutqa-bundle.json)、[native-context selection](inputs/fanoutqa-native-40960-selection.json) 和 [Weka episode audit](inputs/weka-episode-audit.json)：

- FanOutQA 为 160 个完整 workflow、1,304 个独立单 invocation Agent task。DAG 来自公开人类 decomposition/depends_on，final aggregation 是 normalizer 构造；prompt 是 evidence-provided 构造输入，output 是源答案的固定 tokenization，**不是实际 Agent运行trace**。输入 prompt IDs、固定答案的 tokenization、源顺序和一次执行已核对，无 synthetic token IDs/截断；运行中只核查固定 token 回放的 emitted 数量与去重，不独立生成或验证恢复输出的数值 identity。Qwen3-8B 与 32B 仅在清单指定 revision 下验证 tokenizer 等价。
- 若限制每个请求 prompt+output≤40,960，并保持整workflow不裁切，只剩 74 workflows、598 invocations；另 86 workflows 排除，不能把长上下文结果外推为同一受支持配置。全部语料 output 长度 p50=5、p95=58、max=420，无法单独覆盖长期 decode 中反复 checkpoint/hot-set 更新，也没有同 Agent follow-up reuse。80% total-token fault 常落在 prefill，要显式记录故障时阶段；不能声称这是长解码阶段评价。
- Weka 审计索引含 1,688 个已完成、时钟一致的 subagent episodes、41,854 invocations、174 个源workflow。其中 509 episodes 有 overlapping invocation intervals、333 有 model changes。因此“单Agent顺序循环”的转换也必须处理/报告这些不匹配，不能把signed inter-call gap静默截为0。该数据目前支持源时钟下的Tracker/history诊断，尚无源观测的跨Agent固定任务DAG或target-model service time。
- 三者应按 **构造DAG replay / 真实Agent episode诊断 / 原生稀疏选择诊断** 交付，不能拼接后计为三套真实完整静态DAG系统trace。主实验还需明确标 synthetic 的多调用/长decode/phase-shift控制，以覆盖这些缺失机制。

### 3.2 模型集合与 native demand

模型选择以本地可核验资产决定，而非挑三个知名模型名。建议两层证据：

1. **语义/内存形状层**：至少一个 dense GQA 对照，加至少一个有原生 per-layer/per-query selection 的 sparse checkpoint。当前稿的 NOSA-8B、NSA-8B、MiniCPM4.1-8B 可形成 native-selector 差异，但必须绑定各自权重 revision、forward path 和 trace manifest。主 E2E 模型不一定等于三种诊断模型，图题需分清。
2. **成本层**：至少两个 KV-bytes/token 与层数/TP 配置；有匹配 profile 才命名为某 GPU/model 的 calibrated configuration。单纯将 8B 时间按参数量乘常数得到 70B，只能叫 modeled scaling scenario。

官方模型源：[MiniCPM4.1-8B](https://huggingface.co/openbmb/MiniCPM4.1-8B)、[Qwen3-8B config](https://huggingface.co/Qwen/Qwen3-8B/blob/main/config.json)。不要将 dense Qwen3-8B 的模型形状与另一个 sparse 模型的 demand trace 拼接后称原生 Qwen。MiniCPM4 与 4.1 的 checkpoint/上下文配置也不可互换。

对每个模型记录：layers、Q/KV heads、head dim、KV dtype、64-token block 的 all-head 字节数、TP shard 布局、权重/固定 runtime workspace、max context、native selector 的 sink/local/compressed 状态。按真实物理 KV heads 计算，不使用 query heads 冒充 KV heads；TP>KV heads 时要计复制而非简单均分。

`experiments/native-sparse/20260921-concentration-new-models/protocol.json` 明确现有 PG19 资产是三个文学文档、512 suffix queries 的 retrospective concentration diagnostic，非 Agent trace，非预测命中率。用于本 Evaluation 必须按时间切分 prefix/warmup 与 suffix/test；Top-K 只能从 test query 之前已提交的计数产生。全 test window 排序是未来 oracle，单列。跨文档 split 优先；nested 256/512 windows 不是独立样本。对新 query 读取到的重算 KV、辅助 selector 元数据和 demand reveal 时刻照原生语义处理。

## 4. 基线公平契约

下表兼列已实施对照和设计建议；执行状态以各行说明及实际 PLAN/AUDIT 为准，不能把未实施建议列为已完成基线。

所有实现共享同一个 runtime、foreground scheduler、模型 service profile、到达序列、请求/输出工作量、host/worker 拓扑、检测/fencing 延迟、失败后的容量损失、物理预算和共享链路。不同策略的训练/调参用相同 calibration 范围。不要用 baseline 不支持的优先级或慢检测制造优势。

| 图中标签 | 定义 | 解释目的 |
|---|---|---|
| Recompute | 无保护副本，保留相同 token log，失败后 full-prefix reconstruction；仍有相同本地正常 reuse | 故障保护的总体价值；不是完整 vLLM 或 SGLang 对照 |
| All-DRAM（已实施阈值对照） | 仅绕过 E>λ；固定 Z 的完整 checkpoint，有限 DRAM、统一恢复与 peer safety；容量不足仍按 E 排序 | 不是 no-Slack；显式 zero-Slack 另见32-run控制，且同时影响 E/G |
| Load-aware checkpoint（未实施建议） | 完整 DRAM、负载感知 checkpoint holder/retry，统一 Z/容量；无 workflow Slack | 对 LUMEN 最近邻思想的强对照；若没有 progressive speculation，只标 modeled policy adaptation |
| AegisKV-DRAM | 与 AegisKV 完全相同 Tracker、λ、admission、checkpoint、route、layer overlap，关闭额外 HBM | **必须有**，隔离 HBM 的净增益 |
| AegisKV | 当前完整机制：E、checkpoint-only Top-K、增量 G、AIMD | 主系统 |
| 组件/上界 | no-slack、random hotset、static quota、oracle future-demand/Slack 等 | 单列机制消融；oracle 不作为可部署方法 |

主图若只有 Recompute/All-DRAM/AegisKV-DRAM/AegisKV，需在文字中说明尚未含负载感知外部政策对照。KVFlow/TOPAS 可作 foreground cache/scheduler 参考，但不能将其少量 heuristic 的 adaptation 标为原系统复现；接入后必须给每种 protection policy 同样的健康 scheduling 能力。

预算比较用相同 `[foreground+backup HBM, host DRAM, NIC, H2D, D2H, host-memory bandwidth]` 向量。未用的 HBM 是否返还前台需固定；“DRAM-only”若获得更多可用 serving HBM是合理资源机会成本，不应偷偷限制它。若另设专用 protection pool 对照，应分图标清。对每种策略都执行其自己的 F0，另提供共同 Recompute F0 作正常成本参照。

同模型下固定 L/K 的等额 HBM 假设需要覆盖 history blocks<K 的短请求及元数据差异；跨模型的 copy size不同，按 G 排序不等于 byte-knapsack最优。共同 source失败时多个co-bottleneck Agent的个人G也不等于真实联合WCT边际值。实现仍遵循当前设计；Evaluation应通过短history、heterogeneous-config和co-bottleneck控制披露近似的有效范围，不能由单Agent公式宣称全局最优。

## 5. 配置、统计单位与故障协议

### 5.1 实验配置必须记录

- 软件 commit + dirty diff hash、Design hash、trace/model/profile hashes、policy version、所有有效参数，不仅命令行覆盖项。
- 每 DP 的 host ID/TP rank；模型权重之外可分配 HBM和各类别占用；DRAM 是每物理主机容量，多个 worker 不可重复乘算。
- 独立/共享 NIC、fabric、H2D、D2H、DRAM 路径；传输分片、启动/调度费用、queue/workspace 上限及带宽公平算法。
- Z、K、L、λ、β、ε、guard、predictor、AIMD 窗口/增量/减幅/ceiling、telemetry delay；配置由 calibration 选择、test 固定。
- 计算 profile 的模型/硬件/TP/batch/length 范围；不同阶段 interpolation/extrapolation；正常复制/统计计数对 GPU memory bandwidth 的干扰假设。

负载先用共同 F0 搜索可持续区间，再预注册低负载、接近 knee、接近饱和三点，例如共同参考容量的 40%/70%/90%，另加 overload 点。百分比是建议，必须从实际模型运行推导，不能根据每种策略各自容量归一化造成不同 offered load。到达为 open-loop whole-workflow arrivals；在同一点所有策略读同一份时间戳。自然时间序列与 rescaled/Poisson replay 分开。

### 5.2 两种互补故障实验

**主机制实验：同 ID、同逻辑进度。** 预选 workflow/Agent/invocation，主点为逻辑 total-token 进度 80%，补 20%/50%/95%。每策略在该 ID 达到点位时杀其实际 source worker/host；所有 colocated 请求同时受影响。选择策略间不可达点位应报告，不能删除。逻辑进度对齐保证阶段可比，但不同策略故障时钟和周围负载可能不同，故还需要下述集群实验。

**集群 robustness：固定外部事件。** 相同 wall-clock、故障 worker/host 集合和恢复期，对比外部 outage。固定一个失败与固定 25% worker 失败分别画规模曲线；增加 worker 数而固定一次失败时 failure fraction 降低，不能直接解释为算法扩展性更好。

共同保留 token log，明确 worker crash 与 host loss 会丢哪些 HBM/DRAM。至少覆盖 source crash、same-host multiworker loss、source+checkpoint-holder co-failure，以及复制/发布中的 failure。永久故障和 finite downtime 分开；没有 reload 模型不能声称恢复集群 serving capacity。

**复制滞后边界必须保留。** Design 文本写 tail≤Z，但异步复制的实际尾部是 `accepted_tokens−latest_committed_frontier`。若没有 pacing/backpressure 保证，它可以超过 Z。模拟不能裁成 256；应报告 backlog/tail p95/max、`tail>Z` 频率及对应 recovery/WCT。由于当前用户要求前文不改，该偏差应由 Evaluation 的配置/边界说明和 review issue 明确呈现。

### 5.3 统计与指标

主指标：`WCT=workflow completion−external arrival`；按同策略同 workflow ID 配对计算 `ΔWCT=WCT_F1−WCT_F0`。同时给绝对 F1 WCT 和各策略 F0，防止用更差 F0 人为缩小“故障增量”。HBM 边际值用 AegisKV 与 matched AegisKV-DRAM 的 paired WCT差，不将 DRAM checkpoint 的 Prefill 节省计入 HBM。

样本单位按层级说明：原始独立 workflow、独立 arrival/fault campaign、campaign 内共享一次故障的 requests。主要不确定性从 campaign/trace 重采样，不把同 campaign 内相关请求当独立重复。固定真实 trace 变 arrival seed 是调度情景重复，不增加独立内容样本数。确定性参数扫描不画假 CI。

建议从五个独立 campaign seeds 开始，预先定义扩样规则（如 paired CI 的半宽、尾部有效样本数），有必要扩到十个；不能运行直到 p 值过线。按 campaign→workflow 分层 paired bootstrap 或先求每 campaign 指标再给 CI；留出整个 workflow 的 train/calibration/test。p95/p99 必须保留原始统计，少量 workflow 的 p99 只作描述，不能由 160 条请求插值出的 p99 强证 tail improvement。每格至少约 1,000 个 workflow 才有约十个 1% 尾部观察，仍需报告实际尾部数和区间，不能将此数字视为自动充分。

次指标：failure-to-first-new-accepted-token、恢复 pause、TTFT、ITL/TPOT、completed-workflow rate、SLO goodput、无故障 overhead、保护/恢复 bytes、HBM/DRAM峰值、copy backlog、replay tokens、controller decision work/time。重叠阶段报告 critical-path exposed wait，不能把全部 transfer/compute durations 相加。故障影响窗口可采用共同 F0 超出 5% 后直到连续三个窗口恢复的规则作为诊断，但主比较窗口必须预注册/共同固定，不能各策略自行截短窗口以改变分母。

分组至少有 interrupted、同 DAG 的 dependency-delayed、共享资源的 collateral、其他 healthy workflows；保留成员 ID 和分母。失败、超时、OOM、不可恢复和 censored workflow 不能从结果中静默删除。所有负差值、跨零区间、平局保留。

## 6. 建议实验矩阵与规模

下表是覆盖需求，不是已完成的 run list。运行器最终把每个 cell 的 configuration、seed、F0/F1、结果路径及状态写进可审计 manifest；不把 planned/failed/censored cell 合并为成功样本。主矩阵优先共享 F0 以省计算，但共享 F0 的多个 F1 不是额外 F0 重复。

| ID / 问题 | 建议覆盖 | 对照与报告 |
|---|---|---|
| E0 Simulator validity | service-time/bandwidth/TP-byte arithmetic；已有匹配 profile 的 holdout 检查；小状态事件重放与资源守恒 | 预测误差 p50/p95/max 与外推占比；无匹配物理数据则明确 uncalibrated，并用 E10 做参数不确定性 |
| E1 End-to-end WCT | 3 workload families × 3 可验证 model/configurations × 3 loads × 5 policies × 5 seeds × F0/F1：**1,350 个建议运行** | paired ΔWCT ECDF、absolute WCT mean/p95/p99、completion；真实不足三 family 时减小并报告，不补造标签 |
| E2 Recovery attribution | E1 同批日志；interrupted/collateral/healthy；至少一个长上下文和一个低收益 cell | detect/fence、admission queue、H2D exposed stall、replay、remaining generation、join wait；DRAM vs HBM increment |
| E3 O1/Tracker/λ | zero-slack、role-duration prior、训练预测+guard、oracle（单列）；λ sweep 含 0、默认及趋向无保护 | train/calibration/test；time error、slack overestimate、错误不保护、WCT、DRAM/bytes；不以 MAE 单独判好坏 |
| E4 O2 Top-K | causal decayed count、无 decay、无 hysteresis、recency/random、retrospective oracle；K∈{0,0.5K0,K0,2K0} 适当取整 | future demand coverage、miss bytes/stall、hotset churn、本地复制 bytes、WCT；counts query/head union 与实际物理块一致 |
| E5 Depth L / bandwidth | effective H2D 覆盖 B/B*∈{0.25,0.5,0.75,1,1.5,2}；fixed calibrated L、L=1、深度 sensitivity | 稠密/稀疏、短/长 tail；miss-inclusive replay 与公式预测偏差。test 中不逐点重调 L后仍叫固定方案 |
| E6 O3 Adapter | 固定低/高 quota、AIMD、即时合法 ceiling reference；stable、load step、burst、no telemetry | F0 p95/p99、quota/occupied/reserved/high-watermark timeline、拒绝/等待、缩配释放延迟；HBM收益–健康代价曲线 |
| E7 Checkpoint trade-off | Z∈{64,128,256,512,1024}；copy 0.25×/0.5×/1×/2×速度，含 backlog>Z | 正常 bytes/transfer count、metadata/rank barrier、tail与lag分布、恢复与WCT；pending不计coverage |
| E8 Capacity boundaries | DRAM覆盖 0.25/0.5/1/2 倍 working demand；额外 HBM 0/2/5/10% 可分配池；共享主机 | no-space/fallback、actual serving capacity、bytes once accounting；保留 DRAM足够/不够、HBM全被overlap隐藏等反例 |
| E9 Fault stage/topology | early/mid/late；worker/host；固定一故障 vs 25%；DP∈{4,8,16,32,64}；TP∈{1,2,4,8} 可行组合 | rate/worker保持、failure fraction标明；成员ID、capacity loss、备份域共失、完成/失败；无支持的TP组合不硬跑 |
| E10 Model uncertainty | prefill/decode/profile scalar ±10/25/50%；link ±25/50%；copy与GPU interference 0/5/10%；prediction stale/bias | 结论翻转面、符号/排名稳定性，和统计CI分开；这些是显式假设范围，不冒称实测干扰 |
| E11 Factorial interactions | Slack×DRAM pressure、Top-K×L/bandwidth、AIMD×bursty load、Z×copy lag，每组至少2×2 | 同种子因子差分，解释机制协同/冲突，避免只报告各自最好点 |
| E12 Correctness/scalability | TP提交屏障、epoch fence、partial copy、reader lease、same Agent history/model mismatch、host ledger、host loss | event invariants与counterexamples；对象/worker/workflow规模下模拟 wall time、peak RAM、事件数和控制器work，不称CPU生产开销 |

小规模 smoke 只验证 E0/E12 的可运行性；先冻结 E1 协议再运行，避免看结果选故障/trace。扩大规模采用独立 workflow ID/真实 trace 分区或清楚标明的 workload resampling，绝不把同一 DAG 循环多遍后称更多独立 workflows。1,350 是建议预算示例，不是“顶会级”条件，也不应成为规避真实 trace 或 fidelity 问题的数量替代物。

## 7. 仅模拟时的证据边界与完成要求

当前 `docs/current-design-simulation.md` 在本次读取时记录单 DP FCFS、线性 token service、未建模 GPU kernel/DMA memory interference；这些限制会直接影响 queueing、healthy overhead、Adapter价值与规模结果。若这一 runtime 仍作为主引擎：

- 所有性能数称 modeled/simulated，service-time常数来源/敏感性入配置。相同 F0 不支持“实机零开销”。
- 若无法给出校准，E0 可以证明实现不变量和模型内部一致性，但不能写 validated simulator fidelity；E10 的 robustness 也不是校准替代。
- 有公开/既有 GPU profile 可在本次只做 CPU 模拟的范围内使用；先验证绑定、范围和误差，不能把另一个 GPU/模型数据换标签。
- native selector trace 与 Agent workload 若分开采集，E2E 是组合模型，native evidence只支持访问模式；不声称真实 Agent inference 的联合 native trace。
- 符号 token/hash replay 可验证 exact-prefix metadata 行为，不验证浮点 KV/logit 等价或真实生成质量。逻辑输出去重测试与真实故障恢复的 token equality分开。
- Controller运行的 wall-clock microbenchmark 可测这份 Python 实现的开销；若没有把该开销反馈到DES，模拟 WCT 不含这项延迟。scatter-add kernels若仅按常数收费，应如实标 modeled，不说实测 GPU 开销。

把“顶会级”转成可复核要求：每项主张有当前版本数据；核心 comparator 足够强且预算一致；结果不依赖未来信息；每个失败任务可追溯；关键机制有因果消融；反例与 validity 充分；可一键重跑指定图；主文读者能从方法、分母、误差和图看出结论的适用范围。完成这些仍不能由代理替代 PC 做录用判断。

## 8. 主文/补充材料与评审交付

新建独立 `paper/evaluation.tex`，仅在 `main.tex` 引入，不改 Background/Motivation/Design 内容。建议六个紧凑段落群：Methodology；End-to-End Workflow Recovery；Where Recovery Time Is Saved；Mechanism Contributions；Healthy Cost and Robustness；Limitations。主文必要图可选：

1. paired WCT Δ 与 absolute tail（主结论）；
2. interrupted/collateral 分解或真实模拟事件时序（因果链）；
3. offered load–WCT/F0 overhead（运行范围）；
4. DRAM/HBM容量与有效H2D的增量价值（资源边界）；
5. O1/O2/O3消融与checkpoint trade-off（机制）；
6. 规模/预测robustness中能改变结论的一张（泛化）。

不规定必须六张；一种图若没有独立问题就移到补充数据包。原始 CSV、逐 workflow pairs、所有 tails/negative points、runs/seeds、图脚本、editable source、source hashes 与 review记录都保留。不要在空白 planned cells填性能数字；不要将旧设计图重新命名后充作当前实测。

Cursor Agent / Claude Opus 5.5 评审应提供：当前 Design、Evaluation.tex、明确 simulation model说明、E1有效矩阵/统计、baseline mapping、所有图、数据和源hash，以及本协议。让它逐项核验假设、未来信息、分母、统计单位、recovery真实性与反例，不只润色。模型身份、具体命令、原始评审响应、发现与处理均归档；如果所请求模型不存在/不可用，必须如实报告，不能用另一模型冒名通过。重要更改后重新审对应代码/结果/渲染，而不是复用旧“通过”。

科研图最终使用 ≥10 pt 和实际 column-sized color/grayscale PDF 检查；若整个稿的旧 Overview 等前文不符合当前CFP，作为未修改前文的独立问题记录，不把 Evaluation的合规视为整稿已达投稿规范。
