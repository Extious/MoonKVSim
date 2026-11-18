# Evaluation：实验协议与图稿设计

[论文初稿](Paper_Draft_BeforeDiagnosis_20260909.md) · [逐图审查](PAPER_FIGURE_REVIEW.md) · [历史协议](AGENT_LEASE_PROTOCOL.md) · [历史与诊断图](Old_Figures.md)

本设计对应 2026-09-09 的 Evaluation 重构。目标是检验正常执行的服务代价，以及固定故障下完整 Workflow 的恢复收益。算法 2 的实现仍按用户要求暂缓同步；本轮重新组织实验、绘制既有数据的诊断候选，并提供缺测图的空布局，未执行新实验。新协议状态为 DRAFT，下面的样本规模与阈值是事前方案，不能回填成已经完成的配置。

## 1. 主张、实验和图之间的对应

| 论文要回答的问题 | 必须观测的量 | 正文图稿 | 判据 |
|---|---|---|---|
| 正常保护是否影响服务 | 同一 Workflow 的 WCT、全体均值和 P95；TTFT P99、逐 token TBT P99；makespan / 吞吐 | E1 逐 Workflow 相对 WCT；正文服务表 | 预先定义服务非劣边界，不能用“不显著”证明零开销 |
| DRAM 准入是否损害复用 | 命中 token / prompt token、正常重算 token、prefill GPU 时间 | E2 配对命中变化；表内补重算与 GPU 时间 | 命中与时间共同解释，不把更少 GET 字节直接解释为更好 |
| Peer 与控制面有多少代价 | 分项 CPU、逐 GPU 前台 HBM 峰值、分配等待、调度等待、总/分类网络字节、逐链路利用率与 GET 延迟 | E3 分项资源图；表内保留绝对量 | 服务非劣与资源增量分别下结论 |
| 同一故障是否降低完整 Workflow 延迟 | 同一个故障实例、同一个 Workflow 的 F0/F1 WCT；失败与超时 | E4 F1 配对倍率 + E5 故障增量，独立文件并排 | 同例比较，不能用异质 Workflow 的原始 WCT 分布代替效应 |
| 收益为什么出现 | 检测、装入、重算、队列、resume、DAG 终点；提交前缀与丢失/重算 token | E6 恢复时序 + E7 恢复来源，独立文件并排 | 效果必须传递到 Workflow 终点；阶段相关性不自动证明机制因果 |
| 故障频率增加是否仍划算 | SLO goodput、响应时间尾部、完成比例、故障与停机暴露 | R1 / R2 两张独立扫描图 | 执行多故障轨迹，不把一次故障结果线性混合 |
| 并发提高后何时出现干扰 | 同一输入下 goodput、响应时间尾部、HBM/网络/CPU 瓶颈 | C1 / C2 两张独立扫描图 | 相同硬件、相同并发、相同故障计划配对 |

本版主文有七张 Evaluation 候选；它们属于两组主论证，并非七个独立实验矩阵。已有同配置 F0/F1 数据可以跨图复用，不能累计成更多独立样本。前四张 Motivation / Overview 保持不变。R1/R2/C1/C2 仅在本文末尾展示空布局；DP/TP/Model、其他 baseline、算法 2/3 消融仅保留文字位置。

## 2. 从实际论文中借鉴什么

已查看本地 PDF 的实际图页，正式身份由公开来源复核。这里借鉴实验结构与视觉编码，不移植其他论文的数字或收益。

| 参考与身份 | 具体章节 / 图 | 对本实验的启发 | 不直接沿用的部分 |
|---|---|---|---|
| [Mooncake，FAST 2025 Best Paper](https://www.usenix.org/conference/fast25/presentation/qin)；[原文](https://www.usenix.org/system/files/fast25-qin.pdf) | §5.2、§5.3；图 6–10；实际查看 PDF 第 12 页的图 9/10 | SLO 约束服务表现；命中率与 prefill 计算时间相邻解释；配置和负载写在图注外的方法表 | 它研究 KV 服务架构，不是本文的 Workflow 故障配对实验；不将 LRU 策略模拟称为完整 Mooncake 实测 |
| [Ensō，OSDI 2023 Best Paper](https://www.usenix.org/conference/osdi23/presentation/sadok)；[原文](https://www.usenix.org/system/files/osdi23-sadok.pdf) | §7.1–7.2；表 1、图 10–12；实际查看 PDF 第 12 页 | 用 CPU/cache/PCIe 计数解释服务表现；负载曲线保留容量拐点；说明重复和误差线 | 它的 NIC 工作负载与硬件计数不能当作 AegisKV 测量；本图不采用混合量纲双轴 |
| [DéjàVu，ICML 2024](https://proceedings.mlr.press/v235/strati24a.html) | §5.2.3；图 14/15；本地 PDF 第 11–12 页 | 固定 token 步注入；跟踪同一个 microbatch 的累积延迟及后续完成事件 | 本文终点扩展为 Workflow/DAG；不把 token 时序当作 WCT，不将该论文标成系统会议 Best Paper |
| [GhostServe，MLSys 2026 作者稿](https://arxiv.org/abs/2605.00831) | §6；图 5–8；实际查看本地 PDF 第 9–10 页 | 正常/故障分开；恢复分解与故障频率成本收益共同解释 | 图 7 的百分比 failure rate 不能直接换成每 GPU 故障概率；本协议用明确的 cluster-hour 单位。其设备内存故障与节点掉电不同 |

检索和实际图页记录见 [参考绑定](../../../output/evaluation-redesign-20260909/reference-review.json)。GhostServe 的公开作者页标注 MLSys 2026；未将其声明为 Best Paper。获奖信息只用于选择参考，不构成统一的会议绘图规则。

## 3. 公共实验条件

三条系列固定为 Mooncake、DRAM-only AegisKV、AegisKV。DRAM-only 使用相同 AegisKV DRAM 准入并关闭 Peer 备份，用于识别完整系统增量；它不是另一个无关产品。三者使用同一服务引擎、模型和精度、调度参数、路由规则、DRAM 容量、硬件拓扑及恢复目标选择规则。不能给 AegisKV 单独增加未计费的 GPU 或恢复节点。

当前历史原型为 Qwen3-8B BF16、DP8/TP1/PP1、8×40 GiB、1 TB Store、25 GB/s、4096-token chunk、Workflow 并发上限 16，160 个 FanOutQA-derived Workflow 各执行两轮精确重访。它是待标定模拟，不是八张实卡的完整服务测量。新的原生实验应冻结实际 SKU、互联、软件 commit、tokenizer、输入/输出 token、模型与分配器设置；40 GiB 模拟不能混用 L40S 48 GiB 组件结果作为统一平台。

默认保持上述模型和资源条件用于机制重跑；原生三系统数据另建 evidence_type，不能与模拟点聚合。F0 表示没有故障；F1 表示每次完整执行只注入一次预定 GPU/worker 故障。运行是处理一套输入的一次完整执行；图中的点是 Workflow 或故障实例。重复运行只用于估计不确定性，不作为主图横轴。

输入保留完整 DAG 和稳定 Workflow/span ID；正常 token 复用与恢复 token 分开计数。先做正确性校验：输出 token 身份、可读前缀、未确认副本不可读、故障域隔离、失败后无重复可见输出。冻结之前的试验只能用于检查可执行性和噪声，不能参与正式收益估计。

## 4. 正常场景：怎样检验“没有额外 Overhead”

“没有额外 Overhead”至少涉及两种不同量：用户可见的服务退化，以及增加的计算、存储、复制成本。异步复制可以被前台执行覆盖，但不会让实际 CPU 指令和传输字节消失。因此论文主张应限定为“在指定负载和资源条件下，服务退化低于预定边界”，并同时披露资源增量。

以完整 Workflow 的起始准入至 DAG 完成为服务 WCT；若外部输入在准入前等待，另报 release 至完成的响应时间和准入等待，不隐藏在并发限制外。跨系统按相同 ID 配对：

$$
O_{s,i}=100\left(W_{s,i}^{F0}/W_{M,i}^{F0}-1\right).
$$

E1 的零线是 Mooncake。按冻结的基准 F0 顺序排列所有 Workflow；不能各系统分别排序、选部分赢的 Workflow 或只画原始 WCT。全局服务均值使用“完整执行内均值之比”，与“逐 Workflow 百分比的均值”区分。

**事前非劣方案。** 暂拟服务主指标 WCT 均值和 P95 的单侧 95% 上界均低于 +2%；这是尚待正式冻结的验证目标，不是由旧数据推定的合格线。若用户调整阈值，应在新数据采集前记录。TTFT P99、逐 token TBT P99、SLO goodput 和完成率是共同报告的服务约束；不能只挑其中通过的指标下总体“无开销”结论。若只做探索，则报告效应与区间，不宣称非劣。严格双侧等效应另用事前的双侧等效检验，不能把单侧非劣改称等效。

每个物理配置预定 10 个完整测量块，每块重置进程和缓存、执行同一 warmup 与输入，并随机平衡三个系统的执行顺序。每块三个系统是一组配对，Workflow 为块内观测。对完整块聚合后的配对 log ratio 建区间，不把 160 个相互争用的 Workflow 当成 160 次独立部署。10 块是采集起点，不保证检验功效；先导噪声不足以达到预定精度时，在正式采集前一次性修改样本数。区间跨界即结论不确定，不反复加测到通过。模拟只报告其随机化因素所覆盖的变动。

E2 保留逐 Workflow token 命中变化，单位 pp；同时报告全体 token 加权命中率、重算 tokens 和 prefill GPU 时间。避免把命中减少、GET 字节减少共同误判为网络优化。

E3 的资源计量至少包括：

| 资源 / 延迟 | 原始采集与统计 | 不能替代它的指标 |
|---|---|---|
| CPU | 服务进程/线程实际 CPU 秒，按调度、价值/准入、提交、AIMD/回收归属；CPU 秒 / 完成 Workflow 与 CPU 秒 / 测量秒同时报 | Python 参考 CPU 或 DES 报价不能充当原生控制开销 |
| HBM | 每 GPU 的前台 active/reserved、备份 pending/committed/reclaiming、总峰值/时间占比；分配失败、OOM、抢占 | 八 GPU 总和可能隐藏某一 GPU 的压力；授权额度不是已物理释放内存 |
| 等待 | 逐请求 HBM 准入等待、GPU-ready 后队列等待；配对差值与 P95 | 平均 HBM 等待不能代表调度队列 |
| 网络/PCIe/NVLink | foreground GET、DRAM PUT、Peer PUT、恢复 READ 字节分别归属；逐物理路径实际忙碌时间和峰值利用率 | 不同路径的字节相加不是一个链路利用率；较少 GET 可能只是更多 miss |
| 复制干扰 | 相同 foreground shape、相同预分配条件的 copy on/off 随机交错微基准，实际 forward/TBT | 微基准用于组件原因，不能冒充三系统端到端 WCT |

## 5. 固定单故障：让“同一 Failure 影响的 WCT”可比较

### 5.1 主实验的受控干预

原来的“基准进度 25/50/75%”定位不够。当前日志只约束焦点 span 与总 token 进度，其他受影响请求、执行时刻和排队总体可能不同。新主实验冻结一个显式 intervention manifest：

实际 FAILURE_INJECT 日志中的人数如下；三例的 source GPU 分别固定为 gpu-6、gpu-2、gpu-0，但相同设备仍不足以固定受害者。表中分别按 Mooncake / DRAM-only / AegisKV 排列；活跃与排队按 span ID 分开计数，不能直接当作独立 Workflow 数。

| 历史实例 | 活跃受影响请求数 | 排队受影响请求数 |
|---|---|---|
| C1 | 2 / 4 / 2 | 5 / 7 / 3 |
| C2 | 1 / 1 / 3 | 2 / 3 / 2 |
| C3 | 1 / 1 / 1 | 1 / 0 / 0 |

这些日志中的 impact_contract_scope 是 OBSERVED_ONLY，字段为真不代表跨系统集合相同。新主实验的清单应满足：

1. 按输入属性预选 12 个焦点请求：上下文长度与 DAG 位置分层，选例规则只依赖输入/无故障特征，不读 AegisKV 故障收益。没有满足条件的层时明确标空，不用后验有利样本补齐。提交固定 case ID、Workflow/span ID、输入与输出 token 哈希。
2. 主控制条件使用已有模型副本中的固定 source GPU。该 GPU 在干预区间仅允许焦点请求持有易失 primary 状态；其他 foreground 请求和其可复用缓存不得留在该故障域。三系统使用完全相同的固定映射和资源份额，其余 Workflow 在剩余执行副本上运行。这样直接丢失的 primary 集合预定为同一个请求，仍可观察间接排队影响。
3. 故障触发固定为焦点请求 decode 第 8 个 token 完成后的 kernel 边界，输入选择要求至少 16 个输出 token。完整 prompt 与已生成 token 身份相同；控制回放使用固定输出，单独说明它与自由生成服务的范围。不要对 AegisKV 等待副本 ACK、排空 DMA 或延后到保护完成再杀进程。
4. 停止固定 worker 并使该故障域的 primary、正常 HBM cache 与本地 Peer 副本不可用；保持 DRAM Store 与其他 GPU 存活；不可用 120 s。检测延迟和恢复路由在三系统中采用同一规则。恢复目标从已有健康副本中预定，复用其已计费资源；修复和重新入池行为一致。
5. 每例检查实际 lost-primary IDs、source GPU、token 边界、故障类型、修复时长是否符合预定清单。备份集合、复制完成时间和保留策略允许不同，它们正是处理变量。受影响集合或触发进度不符时，整例保留为协议偏差，不仅删除一个系统，也不混入严格配对汇总。

这是一组**隔离直接受害者的受控 GPU 故障实验**，不是自然混部 GPU 掉线的总体影响估计。固定物理时刻通常无法同时固定每个 Workflow 的执行阶段；主实验明确选择语义边界。系统墙钟时刻可以不同，实际故障状态与间接受影响对象必须一并报告。允许的天然调度差异不是“所有物理状态完全相同”。

另留一个共同 foreground 回放的恢复微基准：相同 lost-primary 内容、目标设备与背景负载，分别使用各策略自然形成的已提交备份，测量恢复关键路径。它用于分离传输与重算原因；从预制状态开始的剩余完成时间只能标为 remaining WCT，不能替代包含正常保护成本的完整 WCT。

### 5.2 配对、统计与画法

每个 case、每个测量块执行三个系统的 F0/F1，形成六个执行；F0/F1 必须采用同一 case 路由布局、输出、输入顺序和种子。建议 12 个事前 case × 10 个配对块；每块 6 次执行，共 720 次 case 执行。它不是 720 个独立 Workflow，且不在算法调整期间启动。不同 case 的 F0 若路由不同不能复用。

令 M 为 Mooncake，对同一 case 的同一 Workflow：

$$
\Delta_{s,i}=W_{s,i}^{F1}-W_{s,i}^{F0},\qquad
R_{s,i}=W_{s,i}^{F1}/W_{M,i}^{F1},\qquad
D_{s,i}=100\Delta_{s,i}/W_{M,i}^{F0}.
$$

E4 画 R，1 为同例 Mooncake；E5 画 D，三系统分母相同。正文同时给 F0/F1 绝对秒和受影响范围。不要用自身近零或负的故障增量作分母计算“倍数改善”。若要报告故障代价降低，给 B = Δ_M − Δ_A 的绝对秒及区间；相对故障收益仅在预定分母严格为正且有实际意义时使用。

E4/E5 采用同一 case ID 顺序；异质的少量 case 用点和区间，连续 Workflow ID 展示可以用三条线，但连线只辅助对齐，不作趋势回归。重复不足时保留原始点，不能用图内多个 Workflow 伪造独立置信区间。先汇总每个 case 的配对块，再对预定分层作等权或明确加权汇总；全局区间按 case 和块的层级处理。

主终点是预定焦点 Workflow 的完整 WCT；同一个输入批次中的其他 Workflow、完成率、SLO goodput 和总体 makespan 为系统外部影响。间接受影响组必须在看结果前按输入或固定入场窗口定义；不得仅选事后变慢/恢复过的对象。原生 kill 或超时导致未完成时报告失败和删失，不能将它们当作零 WCT 或从均值里静默移除。

### 5.3 用原因链解释收益

E6 的正式版按同一个焦点 Workflow 画事件轨迹：故障发生 → 检测/重路由 → 前缀可读 → 后缀重算完成 → 首次恢复解码 → 分支完成 → DAG join 完成。当前两个聚合阶段只是候选，尚不足以填完整轨迹。

检测、CPU、传输、排队和 GPU 计算可能重叠。需要原始开始/结束时间和依赖事件，画并行时间区间或沿实际关键路径分解；不能把所有 span 时长相加当作端到端 WCT。分别记录故障前预计 Slack、实际关键路径和 join 等待，以检验节省的恢复时间是否传递到 Workflow 终点。

E7 在相同 case 顺序画 Peer 恢复、DRAM 恢复和剩余重算 token；同时表内给已提交可恢复前缀长度、失去的 primary tokens、ACK 与故障相对时间、传输字节。共享/冗余 token 必须去重，前缀区间要连续。若 Peer 恢复为零，保留零值，不能据此主张 Peer 恢复加速。算法 2/3 的因果消融以后补，本轮只给原因观测与其范围。

## 6. Failure rate 扫描

固定模型、DP8/TP1、资源与并发上限 16；预定测量窗口 H=3600 s，前置 300 s warmup。每个 cluster-hour 精确注入 K∈{0,1,2,4,8} 次故障，横轴为 K/H，不写未定义的“5% failure rate”。这是一组受控压力设置，不代表生产自然故障分布。

每个 K 冻结 10 条外部故障轨迹，包含 cluster 相对时刻、目标故障域、120 s 不可用时间；三系统逐条重放相同轨迹。故障由外部时钟触发，不依赖系统完成速度。注入必须成功并计数，即使目标恰好空闲；不能补抽有负载 GPU 来提高某系统的受灾概率。

本组先研究单 GPU、非重叠故障：在测量窗内划分 K 个可容纳 120 s 故障的间隔，按固定种子在间隔内选时刻并选目标，不以被测系统状态拒绝采样。报告 actual injections、lost requests、总 unavailable GPU-seconds 与 H×GPU 数之比。全系统受害对象可能不同；这正是外部时钟压力实验的范围，不能标成上节严格相同受害者配对。

提供固定外部到达轨迹，所有系统共用到达 ID/时刻；并发上限只控制准入，外部排队纳入响应时间。为一小时窗口提供足够输入，保留重访/共享结构并记录重复构造。窗口结束后的 drain 只追踪已到达对象；窗口内 goodput 的分母固定为 H，不能换成各自完成时间。尾部采用同一到达 cohort，未完成对象按统一观察终点删失并报告比例，不能只对完成者下结论。

R1：SLO-compliant Workflow/s 随注入频率；R2：Workflow 响应时间 P95 随注入频率。分别导出，共用横轴和系统编码，不用 goodput/时延双纵轴。SLO 使用事前固定的 workload-specific WCT/TTFT/TBT 阈值；没有绝对 SLO 时只报吞吐，不擅自叫 goodput。SLO 数值在正式运行前填写到清单。

## 7. Concurrency 扫描

固定模型、DP8/TP1、硬件和每次一例受控故障，扫描最大活跃 Workflow C∈{4,8,16,32,64}。C 不是单步 request batch size，也不是系统中排队的全部 Workflow 数。每个 C 都使用同配置 Mooncake 对照；不能把小并发 Mooncake 与大并发 AegisKV 比较。

提供两个条件：F0 和固定单故障 F1。为保留三条主系列，C1/C2 主图画 F1 下的三个系统，F0 用配对服务表报告；必要时再单独导出 F0，不把六条线挤进主图。每个 C 使用同一预定焦点 case 和注入 token 边界；背景并发是本扫描唯一主动改变的因素，严格匹配受害者的协议与上节相同。

C1 画 SLO goodput，C2 画响应时间 P95，同时表内报告 HBM 分配/抢占、逐路径利用率和 CPU 饱和度，以定位容量拐点。采用固定长度测量窗与足够的外部工作输入；固定窗口中只有一次故障，故障尚未触发的执行标记为协议失败。固定入场约束与真实到达等待都记录。SLO、重复单位和失败处理沿用前述约定。

## 8. 暂留的三个位置

- DP size / Model / TP：留空。以后分开研究固定总 GPU 数下 DP↔TP 的分配变化与增加总资源的扩展；注明一次 rank 故障是否使整个 TP group 不可用，保护与计算资源都计入预算。
- 其他 baseline：留空。候选为 DéjàVu 式异步 DRAM 复制、GhostServe、LUMEN / RaidServe 等；先核对实际可用实现、故障模型和并行方式。复现变体须显式命名，不能把 DRAM-only AegisKV 改名为 DéjàVu。预警抢占、设备 soft fault、突然 GPU 掉线、整节点故障分开对照。
- 算法 2 / 3 消融：留空。待算法 2 冻结，再定义相同资源下移除其决策或使用对照价值的变体；算法 3 单独比较关闭 Peer、相同硬上限的静态 Peer、Guarded AIMD，并同时量化正常代价与恢复收益。

## 9. 原始数据接口与交付

采集前写入 [结构化协议](evaluation-design/protocol.json) 的固定清单；当前尚无实际 case 列表、绝对 SLO、原生平台或正式 commit，状态不得设为 frozen。所需 CSV 表头见 [输入模板](evaluation-design/data/README.md)，不放示意数值。

正式绘图由原始表计算上述指标；尚未实现的新日志字段不得从已有聚合表猜测。当前绘图脚本只从冻结 source-v3 复算七张诊断候选，未读取新协议空表或给空表补零。扩展扫描的四张图明确标注 LAYOUT ONLY，没有曲线、误差线或代表实验结果的基准线。

图的颜色统一为 Mooncake 灰、DRAM-only 橙、AegisKV 蓝，并用形状/线型辅助识别；组成图颜色代表恢复来源，系统在轴上完整说明。逐 Workflow 密集曲线通栏 7 inch，其余按信息量使用 3.33 或 7 inch，独立 PDF + SVG + PNG + 数值 CSV，可由 LaTeX 组合。图内不堆实验配置，不绘制流程框，不平滑或截掉不利结果。

### 仅供设计检查的扩展空布局

| R1：故障频率与 goodput | R2：故障频率与尾部响应时间 |
|---|---|
| [![R1](../../../output/pdf/aegiskv-evaluation-20260909/layout-rate-goodput.png)](../../../output/pdf/aegiskv-evaluation-20260909/layout-rate-goodput.pdf) | [![R2](../../../output/pdf/aegiskv-evaluation-20260909/layout-rate-tail.png)](../../../output/pdf/aegiskv-evaluation-20260909/layout-rate-tail.pdf) |

| C1：并发与 goodput | C2：并发与尾部响应时间 |
|---|---|
| [![C1](../../../output/pdf/aegiskv-evaluation-20260909/layout-concurrency-goodput.png)](../../../output/pdf/aegiskv-evaluation-20260909/layout-concurrency-goodput.pdf) | [![C2](../../../output/pdf/aegiskv-evaluation-20260909/layout-concurrency-tail.png)](../../../output/pdf/aegiskv-evaluation-20260909/layout-concurrency-tail.pdf) |
