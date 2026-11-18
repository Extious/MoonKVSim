# Evaluation：问题诊断、扩展协议与投稿证据

[论文初稿](Paper_Draft.md) · [图稿审查](PAPER_FIGURE_REVIEW.md) · [事件诊断](../../../output/aegiskv-revision-20260909/EVALUATION_DIAGNOSIS.md) · [前版完整方案](EVALUATION_DESIGN_BeforeDiagnosis_20260909.md)

本次修订把图像问题与实验问题分别处理：替换第三条动机、重画 Overview；对正常开销和故障结果按原始事件追因；补充固定算法的并发与外部时钟故障扫描。算法 2/3 的实现不在本轮修改范围。所有定量点均按证据类型标注，不能把图形重画当作新算法性能验证。

## 1. 本轮诊断改变了哪些判断

| 用户指出的问题 | 已核对的事实 | 图与指标的修正 |
|---|---|---|
| WCT 出现数百个百分点增长 | 最坏 Workflow 从25.553增至155.130 s；存在104.929 s中途抢占等待 | 全部160个Workflow按同ID配对，以绝对秒画差值，保留百分比CSV；单独画真实请求进度 |
| AegisKV 命中率下降 | 第二轮重访token加权DRAM命中为94.257/81.568/82.245%；准入并未显式优化未来重访 | 只以重访prompt作图中分母，同时保留两轮合计；初次读取与实际避免prefill分开 |
| 平均时间无法解释服务表现 | 原queue只记录首次入场，漏掉中途抢占；HBM_WAIT也不是全生命周期 | 删除混合指标归一图，以事件轨迹解释长尾；CPU与字节列绝对量表 |
| 故障后没有稳定优势 | 三个焦点的Peer恢复量均为0，故障前大部分GPU备份容量/占用为0 | 同一Workflow画F0→F1，邻接真实恢复来源；不再将这些例子解释为Peer收益 |
| 缺少两个扩展维度 | 旧实现只支持逻辑token故障，不能直接配置外部故障率 | 并发补C8/C64；故障协议单独派生外部时钟事件，先回归再冻结扫描 |

完整事件、代码行与来源见诊断报告。抢占附近 Peer 占用为零，因此“Peer 挤占导致该离群点”没有得到证明。正常开销以同一 Workflow 的 WCT 秒数差值为主，保留全部正负尾部。原始 WCT P95 仅留在补充点表；正常场景的均值保留在正文描述性表格中，两者都不能代替逐对象比较。这组结果不能通过去掉离群点或换分母变成无开销结果。

## 2. 实际参考的论文


本轮重新核对四篇论文的正式出版 PDF，并实际读取方法、评估与机制图页；Mooncake 和 Ensō 的 Best Paper 身份由官方会议页确认，DéjàVu 和 DistServe 不附加获奖标签。这里借鉴如何检验机制和排除替代解释，不移植其他论文的数字或收益。以下页码均为 PDF 文件从 1 开始计数，含 USENIX 封面。

| 参考与身份 | 具体章节 / 图 | 对本实验的启发 | 不直接沿用的部分 |
|---|---|---|---|
| [Mooncake，FAST 2025 Best Paper](https://www.usenix.org/conference/fast25/presentation/qin)；[原文](https://www.usenix.org/system/files/fast25-qin.pdf) | §2.2、§3.1、§5.3–5.4；图 3、9–14；实际查看 PDF 第 5、12、13 页 | 先比较传输与重算的条件，再以命中率、实际 prefill 时间、带宽退化和阶段分解闭合证据链 | 本文应测量抢占后实际避免的计算；不能把原生 Mooncake 的传输性能或 SLO 收益移植给 LRU 策略模拟 |
| [Ensō，OSDI 2023 Best Paper](https://www.usenix.org/conference/osdi23/presentation/sadok)；[原文](https://www.usenix.org/system/files/osdi23-sadok.pdf) | §3、§7.1、§7.2.2–7.2.5；图 3、9–12、表 1；实际查看 PDF 第 5、11、12 页 | 用受控变体破坏局部性，再以 cache/PCIe 计数核对原因；保留引入额外复制的反例和高负载延迟代价 | NIC 计数不是 AegisKV 的测量；应该借鉴控制变量实验，不能把 CPU 时间、流量与等待混成总成本 |
| [DéjàVu，ICML 2024 正式版](https://proceedings.mlr.press/v235/strati24a.html)；[原文](https://raw.githubusercontent.com/mlresearch/v235/main/assets/strati24a/strati24a.pdf) | §4.2.3、§5.1、§5.2.3、附录 E/F；图 7、10/11、24/25；实际查看 PDF 第 6、8、9、22 页 | 将复制优化的无故障开销、同一 microbatch 的故障进度和后续完成事件分别验证；恢复点由已复制进度决定 | 正式版故障图为 10/11；旧预印本为 14/15。其 PP 恢复与整条 pipeline 重启基线不同于本文 DP Worker 故障，不能直接借用加速比 |
| [DistServe，OSDI 2024](https://www.usenix.org/conference/osdi24/presentation/zhong-yinmin)；[原文](https://www.usenix.org/system/files/osdi24-zhong-yinmin.pdf) | §2.3、§3.3–4、§6.3–6.5；图 2、10–12、表 2；实际查看 PDF 第 5、7、13 页 | 固定批次后只加入一种竞争工作观察减速；用阶段等待解释端到端表现，并对照真实系统校验模拟器 | 本文需要测量保护 DMA 的物理干扰。其部署前搜索耗时不能用来论证 AegisKV 在线逐事件准入开销可接受 |

本次正式版、SHA、实际阅读页及图号见 [新版参考审查](../../../output/aegiskv-revision-20260909/draft-refinement/REFERENCE_AUDIT.json)，针对当前稿件的建议见 [科学论证缺口](../../../output/aegiskv-revision-20260909/draft-refinement/SCIENTIFIC_ARGUMENT_REVIEW.md)。本地 DéjàVu 旧文件是 2024-03-04 的 arXiv v1（24 页）；本次另存 PMLR 正式版（27 页），故障图由旧版 14/15 对应为正式版 10/11。旧 PDF 与 [前版参考记录](../../../output/evaluation-redesign-20260909/reference-review.json) 均保留不改；前版中的 GhostServe 作者稿记录不并入此次四篇正式版复核。获奖身份用于选择参考，不构成统一的会议绘图规则。

## 3. 公共配置与统计单位

- 系统：Mooncake、DRAM-only AegisKV、AegisKV，共用模拟引擎、资源、路由规则与恢复路径；Mooncake为策略模拟，非完整原生部署。
- 模型/资源：Qwen3-8B BF16、DP8/TP1/PP1、8×40GiB、1TB Store、25GB/s、4096-token chunk。
- 输入：固定160个FanOutQA-derived Workflow，完整DAG两轮精确重访，2608个请求。全部ID、token输入和顺序绑定SHA。
- 算法：冻结source-v3；完整源码manifest SHA `17c7fd37e74356d2531b15ed1c3659d7f03c874ab00b2fe0794930a8383f5de1`。当前live Algorithm2的进一步修改不纳入这些点。
- CPU：固定CPU_QUOTES，只将入场/准入报价写入模拟单控制器队列；Python实测工作和DES服务报价分别报告，不等于原生CPU利用率。
- 统计：每配置每系统一次完整模拟，Workflow是运行内相互争用的观测，不是独立运行重复。不画虚构的重复CI，也不完成非劣检验。
- WCT：本Workflow首request release到最后request完成；并发门限之前的等待不在其中。完成速率另报，使低并发下短WCT不被误解为高容量。
- 配对：同一配置下比较相同 Workflow ID；正常场景取各系统减同配置 Mooncake 的 WCT，固定追加故障取同系统 K2 减 K1 的 WCT。后者另保留 release 与 completion 的绝对时刻及差值，以区分 Workflow 执行期间的变化与闭环入场时刻移动。

无故障为F0，一次逻辑焦点故障为F1；固定外部扫描的K是每个输入轨迹的事件数，两者使用不同注入契约，不混作重复。

## 4. 正常场景的图像规格

| 独立图 | 原始对象与变换 | 能回答的问题 | 不能据此声称 |
|---|---|---|---|
| eval-workflow-delay | 160个相同Workflow，WCT_s−WCT_M；固定Moon F0顺序，三条线 | 正常延迟增加了多少秒、哪些对象出现长尾 | 单次执行证明非劣；裁尾后证明无开销 |
| eval-initial-reuse | 每WF第二轮DRAM读取token/第二轮prompt token，三条线；总体按token加权 | 准入是否保留正常重访能力 | 初次读取成功就一定避免这些GPU计算 |
| eval-preemption-progress | 同一个长请求的scheduler步与抢占事件；时间对齐各自WF首release | 中途停算与从零重算如何形成某个离群点 | 该单例估计全部请求损失，或证明Peer直接挤占 |

CPU与流量在正文表中按计量过程分别列绝对值；不把请求平均等待、CPU秒和TiB画为可以相加的总开销。进一步采集必须包括每次入队/抢占/重新入场区间、累计实际prefill token、读取后失效token、逐GPU active/reusable/restore/Peer占用与峰值、逐物理路径利用率和copy on/off干扰。

正式的服务非劣目标、SLO和重复方案仍保存在 [未执行的完整协议](evaluation-design/protocol.json)；其中2%只是前版暂拟阈值，没有用户确认，也没有由本轮探索结果进行检验。10块/12case等未来样本计划不计入本次运行数。

## 5. 单次故障的可解释比较

主文将原4张故障图整理为两张：九行（3case×3system）的F0→F1绝对WCT配对，以及相同顺序的恢复token来源。原归一化增量、恢复阶段和全部原始数据仍留在历史目录。

历史C1/C2/C3分别使用相同焦点Workflow和gpu6/gpu2/gpu0，但总token进度约60%的触发未固定全部受害者。实际活跃请求数Moon/DRAM/Aeg为2/4/2、1/1/3、1/1/1；排队为5/7/3、2/3/2、1/0/0。`OBSERVED_ONLY`和match=true不能解释为跨系统集合相等。

下一版严格主实验需要预选焦点输入、源故障域、相同decode边界与120s停机；隔离直接丢失的primary集合，但允许三策略自然形成不同已提交副本。不得等AegisKV ACK后才注入，也不得删除无Peer空间的失败保护案例。至少覆盖以下两个边界：

1. 没有可借HBM余量：检查安全退让和正常代价，不预期Peer收益。
2. 存在可借余量：同时测量连续已提交前缀、实际恢复来源、后缀重算、queue/resume和DAG终点；验证恢复节省是否传递到WCT。

这些条件应来自事前容量/负载计划，而不是从已完成结果里选胜出的Workflow。此严格单故障协议尚未执行，本轮不将自然混部诊断升级为它的证据。

## 6. Workflow并发扩展

固定资源、输入、seed0和F0，C∈{8,16,32,64}。16/32复用相同source-v3的6个既有运行；新增8/64×3system=6个完整运行均已完成。C8三系统pilot通过完整性/配对审计后执行C64；全部12个参数点均完成160个Workflow、2608个请求。

正文使用两张独立图，按“整体处理能力—最高并发下的逐对象代价”顺序分行介绍，不将两图压成同行子图：

- 单栏吞吐曲线（3.33 inch）：横轴C=8/16/32/64，纵轴完整批次完成速率160/T_batch，单位Workflow/s，三系统三条线。T_batch从模拟零时刻计至整个批次排空，包含填充与排空，不叫SLO goodput。
- 宽幅逐Workflow差值图（7 inch）：固定最高并发C=64，每个系统减去同ID、同C64的Mooncake WCT，单位秒；Mooncake为零线。横轴固定采用正常开销图的C16 Mooncake F0排序，C16只决定顺序，不参与纵轴减法。这是最高并发点的配对分析，不是并发轴曲线。全部160个Workflow均保留，AegisKV有65个更快、95个更慢，不能用整体吞吐改善概括为每个Workflow都更快。

每cell发布预定/完成Workflow和请求数、makespan、吞吐、抢占数、配置和来源SHA；原始WCT均值/P95保留在补充点表，不作为正文图或主结论。C64图的CSV保留绝对WCT、同ID基线和差值，另提供四个并发点的全部配对数据。曲线只接已完成的参数点，不平滑、不插值缺测，不用Workflow bootstrap伪造运行间CI。

[预冻结计划](../../../output/aegiskv-revision-20260909/scaling/FROZEN_PLAN.json) · [补充点表](../../../output/aegiskv-revision-20260909/scaling/points.json) · [C64逐对象数据](../../../output/pdf/aegiskv-revision-20260909/eval-concurrency-workflow.csv) · [全部并发配对表](../../../output/pdf/aegiskv-revision-20260909/eval-concurrency-workflow-all-concurrency.csv) · [运行审计](../../../output/aegiskv-revision-20260909/scaling/RUN_AUDIT.json)

## 7. 外部故障频率扩展

旧触发器的时刻由焦点token进度决定，只能研究特定请求的逻辑干预。新适配器从source-v3派生，只修改故障输入与审计分支；继续调用原有GPU fence、状态丢失、恢复和修复路径。Algorithm2/3文件逐字节保持不变。

固定观察窗口H=480模拟秒，C16，K∈{0,1,2,4}。事件表按前K项嵌套取用：

| 顺序 | 绝对模拟时刻 | 物理目标 | 不可用时长 |
|---|---|---|---|
| 1 | 60s | gpu-0 | 120s |
| 2 | 180s | gpu-2 | 120s |
| 3 | 300s | gpu-4 | 120s |
| 4 | 420s | gpu-6 | 120s |

输入频率为K/H，即0/7.5/15/30次/集群小时；这是明确的压力范围，不代表生产故障分布。相同外部轨迹允许自然受害对象不同。即使目标空闲也照常使该GPU不可用，不按副本或受害请求状态推迟事件，不伪造logical/token证据。

窗口内停机暴露为0/120/240/420 GPU·s；420s的最后故障在窗口内只覆盖60s，并于540s修复。480s后不再注入新故障，已发生故障仍按计划修复。故障频率正文图只报告固定0..480s窗口内完成Workflow数/480s，三系统共用窗口和分母。窗口外完成的Workflow不计入窗口吞吐分子，但继续模拟至全部完成，并在补充点表保留完整批次时长、原始WCT统计和完成率；不将全体异质Workflow的原始P95画成故障频率主图，也不把有限事件轨迹解释为稳态故障分布。

K0复用既有F0；派生无故障路径已先与原版完成三系统执行指纹回归。新增K>0的9个完整模拟均已完成，和6个新增并发模拟相加为本轮已完成15次完整扩展模拟。小工作负载回归单独计，不作性能重复；下述固定追加事件图复用K1/K2的6个运行，不增加实验计数。

小回归覆盖三系统F0等价，以及忙/闲GPU、多次事件、精确注入时刻与修复。该回归证明适配边界的这些行为，不证明所有故障状态或原生性能。每个正式cell再次核对固定time/GPU/down、实际注入次数、全部请求完成及输出身份，任何失败保留记录且不伪补点。

[协议](../../../output/aegiskv-revision-20260909/scaling-rate/PROTOCOL.json) · [派生补丁](../../../output/aegiskv-revision-20260909/scaling-rate/EXTERNAL_SOURCE_PATCH.diff) · [耐久回归证据](../../../output/aegiskv-revision-20260909/scaling-rate/REGRESSION_DURABLE.json) · [补充点表](../../../output/aegiskv-revision-20260909/scaling-rate/points.json) · [事件与完成审计](../../../output/aegiskv-revision-20260909/scaling-rate/EVENT_AUDIT.json)

## 8. 固定追加事件的同Workflow比较

独立宽图`eval-fixed-event-wct`从频率扫描中取K1/K2配对：每个系统均保留60s时gpu-0停机120s的共同历史；K2只额外加入180s时gpu-2停机120s。纵轴为同系统、同Workflow的`WCT(K2)−WCT(K1)`，不是减F0，也不是减Mooncake。这一差值描述在共同首故障历史下，追加第二次故障及其后续调度变化的净影响；保留负值、零值和正值，不将追加故障必然解释为延迟增加。60s首事件在三系统都没有直接活跃/排队请求受害者，但仍使GPU容量不可用120s并丢失可复用缓存，因此不是无操作对照。

图中横轴使用180s事件的活跃/排队受影响Workflow在三系统之间的7个ID并集，各系统均画同样7个对象，共21行；标记区分该系统中活跃、仅排队或未直接受影响。这个并集是看过事件日志后形成的描述性对象集合，不是事前固定的因果子组，也不代表全部160个Workflow，更不证明跨系统直接丢失的primary集合相同。

已按整数纳秒核对图中全部21行：K1/K2的首release时刻相等，因此这些对象的`Δcompletion = ΔWCT`。但闭环并发可能改变后续Workflow的入场时刻，不能把此等式推广到全部输入。完整160×3=480行配对表不按结果或受害状态筛选，保留K1/K2各自的release、completion、WCT以及`Δrelease`、`Δcompletion`、`ΔWCT`，并逐行精确检查`Δcompletion = ΔWCT + Δrelease`。这里completion指最后请求的绝对完成时刻；WCT仍不包含首release之前的等待。

已完成三系统各32类保存日志的严格`[0,180s)`语义前缀审计，结果均为PASS。覆盖已记录的scheduler步、路由/抢占、输出位置及实际发出时间、准入/替换与控制观察、GPU/DRAM状态采样、固定DES CPU队列、请求release/completion及传输提交/执行事件；跨边界的终态字段屏蔽，速率区间在180s截断。比较排除运行分配的传输等标识符和真实Python `cpu_ns`，保留固定模拟CPU服务时间。恰好180s发生的首故障修复和追加故障均在前缀之外。这个结果只说明已保存日志在上述语义投影下相同，不是完整模拟器heap状态一致，也不核对不同日志流在同一时间戳内的完整先后顺序。

这张图复用已完成的6个K1/K2运行，前缀审计和绘图均未增加性能运行。严格事前固定直接丢失集合的协议仍未执行；当前追加事件证据不能代替第5节的严格单故障实验。

[事件图与数据清单](../../../output/pdf/aegiskv-revision-20260909/fixed-event-wct-manifest.json) · [全部160个Workflow配对表](../../../output/aegiskv-revision-20260909/scaling-rate/data/fixed-event-all-workflows.csv) · [结构化配对与单位](../../../output/aegiskv-revision-20260909/scaling-rate/data/fixed-event-all-workflows.json) · [语义前缀审计](../../../output/aegiskv-revision-20260909/scaling-rate/FIXED_EVENT_PREFIX_AUDIT.json) · [审计范围与复现说明](../../../output/aegiskv-revision-20260909/scaling-rate/FIXED_EVENT_PREFIX_README.md)

## 9. 待绘图规格与后续证据

本轮图稿可用于讨论当前原型的真实问题与参数响应，不能预设收益。近零正常开销和稳定故障改善仍需要正常复用/抢占计量修复、能实际形成保护的事前场景、严格单故障比较、原生三系统端到端实现和独立重复。DP/TP/Model、其他相关 baseline、算法 2/3 消融及缺少的正常计量，现已在 Paper_Draft 中展开为 P1–P8 八组待绘规格、十张独立候选。每张给出图型、坐标、条件预期和可能反转的情形；所有候选均未执行，不会在算法调整中启动未冻结的完整矩阵。

绘图及样张入口见 [PAPER_FIGURE_REVIEW.md](PAPER_FIGURE_REVIEW.md)。此前四张空扫描布局保留在 [前版实验设计](EVALUATION_DESIGN_BeforeDiagnosis_20260909.md)，当前图只填实际完成的数据。

[主稿的结构化待绘图规格](scripts/paper/templates/planned-figures.json) · [完整计量与比较细则](../../../output/aegiskv-revision-20260909/draft-refinement/planned-figure-specs.md) · [三部分初稿改进记录](PAPER_DRAFT_REVIEW.md)

P3 以焦点请求恢复到共同 consumed-token cursor 的状态就绪时间比较，包含缺失段重建；不同长度的已备份前缀自身就绪时间另作分解，不能混作共同终点。本文尚未执行这些严格故障与原生采集协议。
