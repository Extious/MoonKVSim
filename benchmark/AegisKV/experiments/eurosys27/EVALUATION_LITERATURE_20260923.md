# AegisKV Evaluation：文献依据与实验组织建议

核对日期：2026-09-23。本文是实验设计依据，不是新实验结果。已读取当前 `benchmark/AegisKV/AGENTS.md` 全部修订和 `paper/system_design.tex`；以下适配建议以现行机制为准。没有运行 AegisKV 实验，也没有从他人论文复制结果、误差棒或性能结论。

## 1. 当前 Evaluation 应回答什么

AegisKV 的主问题是：**在相同的推理、存储和故障预算下，按工作流恢复紧迫性分配 KV 状态，能否减少故障带来的工作流完成时间，同时控制正常服务代价？** 单请求 KV 读取变快、访问集中、潜在前缀重用多，都只是机制依据；必须沿着“保护/保留决策 → 实际恢复路径和排队 → 受影响的 DAG → WCT”建立结果链。

现行 Design 包含以下实验对象，旧结果不可自动替代：

- Peer、DRAM、shared storage 的稳定 managed ownership 互斥；三者并集覆盖已提交 checkpoint。迁移期间两份物理字节都计费，Peer 淘汰需要实际下迁。
- 固定每兼容 model/layout 的 `L/K/Z`；运行时调整 Peer request membership 和 hot-block identity，Adapter 只调总配额。Peer 采用 guarded zero-slack 候选与 incumbent-preserving tie rule，不参与租金。
- DRAM/storage 有独立 pressure clocks 和逐 Agent renewable credit；正常复用价值独立于 Slack，实际使用才 renewal，value refresh 和移动保留 paid rent。
- selected-query / causal-visibility 的稀疏需求估计；bounded low-key + rotating scans 的 lazy materialization。它不是精确全局最小 victim，也不是 complete-plan WCT search。
- Router 的 source/takeover failure domains、物理 leases、reserve/copy/commit/redirect/drain，以及丢失 sole owner 后的有效 fallback。

因此，完整 Evaluation 的逻辑顺序应为：**实验设置与证据级别 → 端到端收益 → 恢复与连带影响解释 → 各机制贡献 → 资源/预测边界 → 正常代价与正确性**。无需把每个参数单独写成同等长度的论文小节。

## 2. 六篇核心原文：实际 Evaluation 与可借鉴之处

以下章节和图号以链接所指版本为准；LUMEN 与 TOPAS 在本次核验中作为 arXiv v1 使用，不把它们标为已在 EuroSys/OSDI/SOSP/NSDI 发表。

| 论文与原文 | 已核对的章节、图表 | 对 AegisKV 的直接启示 |
|---|---|---|
| **LUMEN: Coordinated Failure Recovery for Distributed LLM Serving**, arXiv:2606.17787v1。[全文 HTML](https://arxiv.org/html/2606.17787v1)，[PDF](https://arxiv.org/pdf/2606.17787v1) | §6.1 methodology；§6.2 prototype；§6.3 simulator。Fig.6 按 request-ID bucket 画 mean/p99 TTFT/TPOT 与 No-Failure；Table 2 拆 interrupted/uninterrupted；Fig.7 机制拆分；Fig.8/9 分别扫描负载/失败数；Fig.12 固定失败比例扩容，Fig.13 固定一次失败扩容。 | 物理原型与仿真各自陈述。故障影响包含健康请求排队；恢复时间应有明确回归 F0 的判据。分别做“固定一故障”和“固定失败比例”的规模实验，不能用故障占比下降冒充伸缩收益。 |
| **Fast State Restoration in LLM Serving with HCache**, **EuroSys 2025**。[DOI](https://doi.org/10.1145/3689031.3696072)，[PDF](https://arxiv.org/pdf/2410.05004) | §6；Fig.9–10 为 ShareGPT4/L-Eval 的 TTFT/TBT 随负载变化；Fig.11 扫 GPU、传输速度和历史长度；§6.3 的 Fig.12–14 分别拆 scheduler、state partition、state saving；Fig.15 联合 GPU cache reuse。 | 将恢复速度与健康 decode 代价同时报告；在 compute-sufficient、I/O-sufficient、balanced 三种资源关系下拆 overlap。论文注明部分带宽配置用 DRAM 模拟磁盘，AegisKV 同样必须保留真实设备与模拟传输的边界。 |
| **CacheBlend: Fast Large Language Model Serving for RAG with Cached Knowledge Fusion**, **EuroSys 2025**。[DOI](https://doi.org/10.1145/3689031.3696098)，[PDF](https://arxiv.org/pdf/2405.16444) | §7.1 setup、§7.2 overall、§7.3 sensitivity；Fig.12 联合 TTFT/quality；Fig.14 为 request-rate/TTFT 曲线；Fig.15 扫 chunk 数、长度和 batch；Fig.16/17 检查 recompute ratio、存储设备。 | 主曲线须在可比输出语义和资源下比较；标明冷启动/预热与请求分布。AegisKV 不改 native attention，因此应验证等价恢复而非直接采用 CacheBlend 的近似质量容忍值；选择性融合也不等于容错 checkpoint。 |
| **Mooncake: Trading More Storage for Less Computation—A KVCache-centric Architecture for Serving LLM Chatbot**, **FAST 2025**。[会议页](https://www.usenix.org/conference/fast25/presentation/qin)，[PDF](https://www.usenix.org/system/files/fast25-qin.pdf) | §5.1 setup、§5.2 E2E、§5.3 cache、§5.4 transfer。Fig.6–7 同时约束 TTFT/TBT 的有效请求能力；Fig.9 为仅考虑请求序列的容量/命中分析；Fig.10 为实际 cache hit/prefill GPU time；Fig.12–13 为 transfer/bandwidth。 | SLO goodput 不应把丢弃、超时请求排除出分母。严格区分 locality-only 分析与运行时命中；带宽实验需要“传输已经不如重算”的交叉点。其 tool&agent trace 本身不证明拥有完整 DAG、tool 时间或故障恢复证据。 |
| **TOPAS: Workflow-Aware Prefix-State Scheduling for Multi-Agent LLM Serving**, arXiv:2608.25523v1。[HTML](https://arxiv.org/html/2608.25523v1)，[PDF](https://arxiv.org/pdf/2608.25523v1) | §V-A setup、V-B E2E、V-C ablations；Fig.3 三种 synthetic DAG 的 mean/p99 JCT；Fig.4 MetaGPT-SOP/TL；Fig.5 component ablation。同一 SGLang backend 和固定到达轨迹用于各策略。 | 工作流级主指标与 DAG 类型并列；synthetic 用于隔离拓扑，真实 prompt 用于外部有效性。共同 backend 上的策略对照应明确称 policy adaptation。其无故障 JCT 优化不是 AegisKV 的故障收益证据。 |
| **Parrot: Efficient Serving of LLM-based Applications with Semantic Variable**, **OSDI 2024**。[会议页](https://www.usenix.org/conference/osdi24/presentation/lin-chaofan)，[PDF](https://www.usenix.org/system/files/osdi24-lin-chaofan.pdf) | §8.1 setup；§8.2 chain/map-reduce；§8.4 multi-agent；§8.5 mixed workloads。Fig.12–14 E2E；Fig.18 同时报告 multi-agent latency 与 KV memory，并比较 latency/throughput 两种 baseline 配置；Fig.19 mixed workloads。 | 不以 request-centric 的弱配置代表最佳 baseline。对 DAG workload 同时给 WCT 与容量变化，分开检查交互请求和吞吐型后台任务。由脚本固定响应长度的 replay 与在线生成应分别说明。 |

**原文图像观察。** 已实际渲染并查看本地原文的 LUMEN Fig.6、HCache Fig.12–14、CacheBlend Fig.14–15、Mooncake Fig.9–11、TOPAS Fig.3，以及作者 PDF 的 Parrot Fig.16–18。它们通常采用固定方法配色、同类子图共享标尺、曲线展示 operating range，并用机制图解释 E2E 曲线。不能照抄其密集多子图的尺寸：在 AegisKV 当前单栏和 10 pt 要求下，应将必要证据重新排为可独立阅读的单栏画布。

## 3. 建议主文结构与研究问题

下面是针对当前 AegisKV Design 提出的实验组织建议，**不是上述论文已经执行的 AegisKV 实验**。支持实验应完整保留在 experiment package，主文按论证需要选图，八类问题不等于必须发表八张图。

| 问题 | 核心比较与控制 | 主指标 / 推荐图形 | 结论边界 |
|---|---|---|---|
| RQ1：故障时是否真正改善 WCT？ | 同一 workload IDs、arrival trace、model、资源、故障域；每种策略都有 paired F0/F1；至少包含 rebuild、uniform checkpoint、matched hierarchical cache、AegisKV。 | 每 workflow 的 `WCT(F1)-WCT(F0)`；absolute WCT mean/p50/p95；paired ECDF 或分组点图。 | 主指标不能只取被中断 request；负收益与失败任务保留。 |
| RQ2：收益来自哪里？ | 固定 fault identity/progress、恢复调度和 checkpoint coverage；分别关闭 workflow urgency、Peer、layer overlap；共享队列/链路保持一致。 | timeline/decomposition：detect/fence、queue、storage、H2D、replay、blocked join；并报告 interrupted 与 collateral workflows。 | 并行阶段不可直接相加；exposed wait 不等于总传输量。 |
| RQ3：在哪些资源条件有效？ | `B_P/B_D/B_S`、storage bandwidth、H2D bandwidth、tail `N`、DAG slack 与 load；有限 staging workspace。 | 匹配预算下的 crossover curve/heatmap；Peer marginal ΔWCT 与健康成本。 | storage-bound、long-slack、fully hidden transfer 均应允许零/负 Peer 收益。 |
| RQ4：每个 priority/Peer 简化是否合理？ | zero-slack vs slack-blind；normalized visibility vs raw counts/recency；固定 slot vs adaptive quota reference；dense control；同一资源和信息预算。 | WCT + native demand miss + physical bytes；单机制 ablation 和少量二因子 interaction。 | retrospective top-k/oracle 只是信息上界，不可冒充 causal predictor。 |
| RQ5：renewal 与 lazy update 值得吗？ | same-value direct revaluation、GDS/Landlord adaptation、LRU、eager materialization；使用/score refresh/迁移事件一致。 | WCT、bytes moved、retained reuse、p50/p99 controller CPU、候选检查与 eager disagreement。 | 保留旧 rental 负例，但旧 additive scalar 比较不是当前 controller CPU 测量。 |
| RQ6：预测和固定 L/K/Z 能泛化吗？ | whole-workflow train/calibration/test；固定配置仅由 calibration 集选择；未知 DAG 和过期特征回退。 | segment-time error、slack overestimate/guard coverage、held-out WCT、L/K/Z sensitivity。 | whole-Agent error 不能验证 residual segment Slack；仅看 MAE 不足以证明决策有效。 |
| RQ7：正常服务付出多少？ | F0、相同 serving HBM 和上限；checkpoint/credit/Adapter 分拆；one-pass 真实 DAG；突发与稳定负载。 | WCT、TTFT、TPOT/ITL、SLO goodput、CPU/metadata/transfer/occupancy；quota timeline。 | quota 下降不是瞬时释放；prefix opportunity 不是实际命中。 |
| RQ8：正确性与规模如何？ | source loss、owner co-failure、copy/commit/redirect/drain 竞争、lease/cancel、DP/TP compatibility；固定一故障与固定比例故障分开。 | 安全性覆盖表 + observed violation counts；worker/object/Agent-share scale；完成率与 controller tail latency。 | finite state checks、simulator recovery、physical restart 各自陈述；不能由无失败小样本宣称永不失败。 |

建议论文小节为：`Methodology`、`End-to-End Workflow Recovery`、`Recovery Paths and Resource Boundaries`、`Policy Contributions`、`Prediction and Configuration Robustness`、`Healthy Cost, Scale, and Correctness`。每节开头一个问题；先写该节控制条件与单位，再解释数据，最后说适用范围。未执行的 campaign 应写在协议中；主文应明确标注当前图的 analytical / trace-derived / trace-driven-model / physical 属性。

## 4. Baseline 公平性：比较对象先于画图

### 4.1 最小可解释对照组

1. **F0 / no fault：** 每个策略自己的无故障对照，用于拆正常成本与故障增量；另提供共同的无保护 F0 作为系统成本参考。不能把拥有不同正常开销的 F1 都减去同一个 F0 后称“恢复开销”。
2. **Rebuild：** prompt/token log survives，丢失状态重建；相同 fencing、retry admission、batching 与模型装载假设。
3. **Uniform checkpoint + load-aware retry：** 给足可比的 checkpoint/recovery 能力，固定周期/容量/带宽，避免只与无备份方法比较。
4. **Workflow-unaware hierarchical policy：** 相同三层和 protocol，LRU/GDS 等保留，关闭 Slack；隔离 workflow awareness。
5. **AegisKV：** 当前 fixed-slot Peer + lower-tier renewable credit + lazy updates + Adapter；记录实际生效参数与版本。
6. **机制参考：** same-value direct、eager updates、adaptive-depth、small-instance clairvoyant bound；它们是组件对照，不应与完整外部系统混排。

### 4.2 外部系统的可比方式

- LUMEN 是最接近的 failure-recovery 参照，必须承认其 load-aware placement/routing。若只实现其一部分策略，应标 `LUMEN-inspired policy`，列出未实现的 progressive model reload/speculation，不能标成完整 LUMEN。
- Parrot/TOPAS/KVFlow 类工作流 serving 更适合作为 common-runtime scheduling/cache-policy 对照。若不能移植其完整 scheduler 和状态语义，则用可审计的 policy adaptation，并在表中列 mapping。
- HCache/CacheBlend 改变状态表示或 KV 融合方式，默认不是同语义的 AegisKV 整机 baseline。适合作为恢复引擎替代或方法参照；若加入比较，需额外控制计算工作、精度、存储字节和恢复语义。
- storage/HBM 总预算、working KV、model weights、temporary copies、TP objects、metadata、workspace 和 reservations 要一致计费。提供“相同 tier 向量”和“相同总资源成本”的结果时，应分别标名。
- 所有策略可使用同样的 causal telemetry。offline oracle 的未来信息单列；调参预算和训练样本一致。

## 5. Workload、故障和统计单位

### 5.1 Workload

- **自然 workload 为主证据：** 固定真实 workflow ID、Agent ID、DAG 与原始执行顺序；one-pass `rounds=1`。列 workflow 数、request 数、Agent 角色、fan-out/depth、tool wait、prompt/output/history 分布以及共享前缀覆盖。缺失的 DAG/tool labels 明确列出。
- **结构化 workload 为因果控制：** chain、balanced fork/join、skewed branch、recurrent coordinator、tool-heavy、high-sharing/low-sharing；保持 token/work 相近再改变 topology/slack，避免同时改变全部因素。
- **原生稀疏 workload：** 记录 model weights hash、forward path、selector、physical engine block、layer/TP layout、辅助状态。dense 是必要反例；不能把构造 top-k 访问称 trained-model native demand。
- **在线与 replay：** 冻结响应 token 流的 replay 可控制同等工作量，但不能证明在线生成品质。分别保留 natural F0、fault replay 和真实恢复生成验证。
- **负载覆盖：** 低负载、knee、near-saturation、overload；额外有 burst 与外部 tool 等待。Open-loop 到达避免 completion-throttled clients 掩盖过载。

### 5.2 故障设计

主 fault campaign 建议以同一 Workflow/Agent/request、同一 logical total-token progress 定位；例如主点 80%，辅助扫描 20/50/80/95%。这保证不同策略故障时处理的是同一个任务阶段。若某策略尚未达到点位，应等待该策略达到，而不是把同一 wall-clock 时刻当成同等工作。另设 wall-clock worker kill campaign 衡量集群整体恢复；两者不能混为同一统计实验。

必须包含：source worker 的全部 colocated requests 同时受影响；takeover/bandwidth/queue 竞争；故障检测与 fencing 的统一延迟；失去 serving capacity 的持续时间；checkpoint commit lag 导致 `N>Z`；sole Peer owner 丢失时的 older-checkpoint/log fallback；source 与 owner 共失的边界。单 request 删除 KV 不等于 worker failure。

对 storage 故障明确是请求错误、目录不可达、device failure 还是 host loss；`shared filesystem` 未核实不能写 `SSD`。断电耐久性不能由 process kill 推出。

### 5.3 Metrics 与统计

- `WCT = workflow finish - external arrival`，包括 queue、tool wait、retries。主故障增量为同策略 paired `ΔWCT=WCT_F1-WCT_F0`；同时报告 absolute WCT 和 workflow completion/censoring。
- `TTFT` 从原 arrival 算起，且另外报告 failure-to-first-resumed-token。已经开始 decode 的请求不能用原始 TTFT 单独反映恢复。
- 报 TPOT 时明确平均的 token 范围；用 ITL p95/p99 / 最大停顿补充故障卡顿。Mooncake 的 TBT 定义是最长 10% token intervals 的均值，不应直接当成普通 TPOT。
- 区分 interrupted requests、受相同 workflow 依赖影响的未中断 requests、共享队列的 collateral workflows、其余健康流量；记录成员与分母。
- 独立 campaign/arrival-seed/fault-seed 才是重复；每个 campaign 内的请求共享资源和故障，并非独立重复。统计可用 paired workflow bootstrap；若 campaigns 多，按 campaign→workflow 分层。不要给 deterministic analytical sweeps 画置信区间。
- 至少预注册若干独立 campaign，再按实际 CI 宽度判断样本是否足够；“5 次”是可操作起点，不是论文质量保证。小样本时不突出不稳定 p99。跨 workload 聚合先规定 equal-workflow/equal-family 权重，保留逐 workload 结果。
- 所有 timeout、OOM、fallback 与失败完成要报告，不能从延迟统计静默删除。负收益点、跨零 CI 和某 baseline 更好的区域都保留。

## 6. 当前机制必须补齐的具体实验

**Peer 的增量价值。** 用同样的完整 checkpoint coverage、恢复 target、并发和 finite workspace，比 DRAM/storage baseline 与增加 Peer 后的实际路径。扣除 Peer 占用 serving HBM 引入的健康排队，并测迁移 bytes/time；仅比较 H2D 与 HBM 耗时不足以证明 WCT 净收益。固定 L/K 由 calibration 选择，test 不能逐点重新优化；adaptive-depth/oracle 单列。

**选择概率。** 相同 quota 比较 causal normalized frequency、raw count、recency、random 和 future oracle。分 cold-start、growth、phase shift、layer、model，同时报 visible opportunities 与 misses；计 auxiliary state。不能只画累计 access concentration 来验证 next-query demand。

**Credit 与 lazy updates。** 构造和自然 trace 都要包含同 Agent 重复 use、不同 Agent sharing、只有 checkpoint growth 无 use、Slack/version 变化、迁移往返、lease 占用、hot-set churn。比较 same-value direct/eager，记录 paid rent 不被 score refresh/migration 清零、rejected previews 不前移 clocks、overlapping shares 不重复计 bytes。对 q/scan budget 做 WCT–controller-work Pareto；检查 unseen keys 下降时 bounded scan 的代价。

**Adapter。** 固定低/高配额、instant safe ceiling、AIMD 对照；负载阶跃与突发下画 `quota / occupied+reserved / serving high watermark / backlog`，并报告 foreground tail、overshoot duration、demotion cascade 和 physical release delay。没有 telemetry 时 growth disabled 必须有覆盖。

**Tracker。** 真正 residual-segment 标签、按 whole workflow split、held-out topology/model shift、guard 超估率和决策效用。当前 whole-Agent diagnostics 作为历史限制保留；无有效 segment calibration 时执行 zero-Slack fallback，不能由旧 CDF 声称已训练好在线 Tracker。

**Correctness。** 用可审计事件日志验证 complete manifest coverage、exactly one stable managed owner、commit-before-retire、drain-before-release、reservation reconciliation、epoch fencing、deduplicated acknowledgement、TP completeness、fallback prompt/token log 可达。物理恢复用 deterministic decode 做 token/logit 对照，必要时说明 floating-point 容差；加 tool side-effect 的调用去重检查。表格写“检验了哪些状态、多少次、在哪个 harness”，不写未验证的全局保证。

## 7. 图像与写作：从参考形式到本项目结果

主图优先突出一个问题，保持全章节方法顺序和色/marker/line-style 映射。ECDF 的基线 0 和负值区域不可裁掉；paired improvement 用点/区间优于只有汇总 speedup 的大柱图。Latency–load 用曲线；byte budget/bandwidth crossover 用原始物理单位；事件 timeline 用真实 timestamp；correctness 用表，不用虚构 100% 柱状图。

因 overlap 并行，分解图采用 wall-clock critical-path/exposed wait，或标明重叠区域的时间线；不能用将 storage+H2D+compute 总时长相加的堆叠柱冒充总恢复耗时。多级 data movement 同时给 logical coverage 与实际 physical bytes，shared physical bytes 只按副本计一次。

每个图注至少回答：统计单位、workload/model、资源、fault trigger、baseline、误差/区间定义和证据级别。正文按“问题 → 最重要观察 → 机制解释 → 例外/边界”写，只有完成数据才写 `we measure` / `we observe`。模型图写 `the model predicts`，数据分析写 `trace analysis shows`。不能以 `EuroSys-level` 替代真实校准和物理验证。

## 8. EuroSys 2027 官方要求

本次在线核实的 [EuroSys 2027 Call for Papers](https://2027.eurosys.org/cfp.html) 要求：技术正文最多 12 页；参考文献可额外分页；补充材料另文件提交且审稿人可不阅读。A4 或 US letter，内容区域 178×229 mm，双栏间距至少 8 mm；所有文字包括图内文字和图注至少 10 pt、行距至少 12 pt；图需灰度打印且无放大可读。建议使用 SIGPLAN 模板。当前用户授权先写完整研究稿，可以暂时超过页数，但交付时应区分“研究稿完整”和“满足投稿格式”。

据此，本项目当前约 84.7 mm 单栏图应从原生画布排版；检查实际 `includegraphics` 缩放后的字体和最终 PDF/PNG，不能靠源文件 `fontsize=10` 推定放入论文后合规。采用同时可辨的线型、marker 和灰度；避免仅红/绿区分。主图数量按独立科学作用选择，支持材料不能代替主文核心证据。

## 9. 阅读与来源记录

| 本地原文文件（位于 `benchmark/AegisKV/docs/related_works/`） | SHA-256 | 本次实际渲染页（PDF 页号从 1 开始） |
|---|---|---|
| `2026/LUMEN: Coordinated Failure Recovery for Distributed LLM Serving.pdf` | `9258028411f57d8cf1ecff9f8f06564695138ddda188f66cfabfe8dfabbfe97d` | 9，Fig.6 |
| `2026/TOPAS: Workflow-Aware Prefix-State Scheduling for Multi-Agent LLM Serving.pdf` | `4ef62ccdd332788e7d8346f3da37d01f66314c8d771444def92d7b21fc682741` | 6，Fig.3 |
| `2025/CacheBlend: Fast Large Language Model Serving for RAG with Cached Knowledge Fusion.pdf` | `d261a895e9cd82bdb69eb0b9734ef8dc09360dbb414dfa4039eac25d99753f18` | 11，Fig.14–15 |
| `2025/Fast State Restoration in LLM Serving with HCache.pdf` | `cc25066d2f1950bfdc7a3ed13352902897b298b38542fff8c123126df4b57451` | 12，Fig.12–14 |
| `2025/MOONCAKE: Trading More Storage for Less Computation---A KVCache-centric Architecture for Serving LLM Chatbot.pdf` | `543e56c541523c5e807d2231370f96749b2294bc901266397a7265b18ae2c130` | 12，Fig.9–11 |

Parrot 的官方全文/图注已经读取；另成功从[作者页面 PDF](https://chenc10.github.io/assets/pdf/2024_osdi_parrot.pdf)在内存中渲染含 Fig.16–18 的页面并检查，不为研究任务新增下载文件。所有本地原文均只读。文献中的结果值没有用于生成任何 AegisKV 图像。

## 10. 论文引用键

当前 `paper/references.bib` 已有 `cao2026lumen`、`gao2025hcache`、`qin2025mooncake`、`ni2026topas`、`lin2024parrot`。HCache 现有 entry 为 2024 author preprint 并注明 EuroSys 2025；正式会议 DOI 为 `10.1145/3689031.3696072`。CacheBlend 本次检查未见现成 entry，可新增以下已按作者 PDF 首页核对的最小元数据（此报告未修改 bibliography）：

```bibtex
@inproceedings{yao2025cacheblend,
  author = {Yao, Jiayi and Li, Hanchen and Liu, Yuhan and Ray, Siddhant
            and Cheng, Yihua and Zhang, Qizheng and Du, Kuntai
            and Lu, Shan and Jiang, Junchen},
  title = {{CacheBlend}: Fast Large Language Model Serving for {RAG}
           with Cached Knowledge Fusion},
  booktitle = {Proceedings of the Twentieth European Conference on Computer Systems},
  series = {EuroSys '25},
  year = {2025},
  publisher = {Association for Computing Machinery},
  doi = {10.1145/3689031.3696098},
  url = {https://doi.org/10.1145/3689031.3696098}
}
```
