# 新 workflow 的论文与实验设计

版本：2026-10-05。证据状态：**正式评估设计未完成；两个输入的新应用执行、小规模固定 token GPU 对照和原生选择观测已采集**。最新运行、图型映射及证据限制见 [实测图记录](../../exports/workflow-motivation-measured-20261005/README.md)。本设计不使用旧实验选择任务、模型参数或故障案例。原论文版本保存在 `exports/workflow-paper-revision-20261005/before/`。本目录负责新实验协议，不改变已经实现的算法。

## 任务来源与 trace 的选择

| 应用 | 公开输入 | 可以借鉴的执行参考 | 本项目需要新采集 |
| --- | --- | --- | --- |
| 有证据支持的比较研究报告 | [DeepResearchBench](https://github.com/Ayanami0730/deep_research_bench)：100 个专家设计任务、22 个领域，主题分布参考真实用户查询；[DRB II](https://github.com/imlrz/DeepResearch-Bench-II)：132 个专家报告衍生任务与 9,430 项评分标准 | [NVIDIA Open Deep Research 执行与回放说明](https://nvidia.github.io/TensorRT-LLM/latest/blogs/tech_blog/blog27_Evaluating_Agentic_Serving_with_Trace_Replay_and_Job_Level_Metrics.html)：实际模型运行，包含并行研究示例；本地未取得该研究示例的原始完整 trace | 7 Agent 应用的完整输入、输出、依赖、token、工具/队列时间、KV 和恢复事件 |
| 仓库 issue 的变更方案评审 | [SWE-bench Verified](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified)：500 个经人工核验的真实 GitHub issue/修复任务，仅使用 issue、仓库、base_commit | [MAST](https://github.com/multi-agent-systems-failure-taxonomy/MAST/tree/main/traces) 的软件协作日志；[SWE-smith trajectories](https://huggingface.co/datasets/SWE-bench/SWE-smith-trajectories) 的单 Agent 工具调用轨迹只能作为补充参照 | 8 Agent 分析/评审 DAG 的连续多轮运行；不冒称完成原始 SWE-bench 修复测试 |

公开 benchmark 的报告、答案与评分标准不是多 Agent 服务 trace。以上公开 trace 尚未被验证完整满足本应用的固定任务 DAG、连续多轮、完整历史、短工具四项约束。具体 7/8 节点图是本项目实现，不能称为生产日志中直接提取的拓扑，也不能凭两个图声称覆盖全部 Agent 应用。

研究报告不限于软件市场：产品比较、技术路线比较、方法适用性分析均可实例化同一依赖结构；每个主题必须明确对象、需求/评价标准、外部限制三个材料域。纯事实问答、没有比较/综合目标的任务不硬套该模板。本轮实测以 DRB-66 的 Obsidian 比较为起步实例；早期文档中的任务 93 并非本轮采集输入。全体任务先做与恢复策略无关的适配性标注，公开所有纳入/排除理由及各领域覆盖率。DRB II 提供可选扩展和独立质量评价，不默认为已经下载、适配或全部可用。

当前已有材料见 [输入来源与哈希](../workload-decision-20261004/SOURCE_MANIFEST.json) 和 [公开 trace 审计](../trace-reference-audit-20261004/README.md)：本地有 DRB 100 条输入、一个 SWE-bench 输入样本及若干外部 trace 样本；两个 DAG 的初始完整执行 trace 现位于 `experiments/workflow-motivation-20261005/runs/capture-163125/`。正常阶段为 36 次调用、15 个 Agent、两个输入；这不代表全数据集集成或应用质量通过。

## 应用与逐轮请求

每个节点是一个 Agent 的完整任务。所有直接前驱任务完成后，该节点获得其全部产物并启动；只等待自己的前驱，不设整层屏障。中间产物携带必要事实与证据 ID，避免下游偷偷读取未声明的前驱。Agent 启动后不向别的 Agent 请求中途反馈，自己连续提交多轮请求；服务排队仍可能打断 GPU 实际执行。

每个 Agent 有不同的 system 角色提示，输入均包含原问题、分配材料、前驱产物与产物格式。轮次遵循 **按实际材料组阅读/形成产物 → 证据核查 → 有具体问题时修订**。至少形成与核查两次独立 model invocation；更多轮次由真实材料与未解决项决定，不按目标 KV 长度追加无意义调用。每轮追加此前全部 user/assistant 消息；不重写前缀、不静默摘要。是否产生可复用 KV 用实际序列化 token 的公共前缀核验。

研究报告的角色与请求如下；市场报告与技术比较分别映射同一角色，具体领域名称在任务注册前固定。

| Agent / 前驱 | 首轮请求大意 | 后续独立调用及交付 |
| --- | --- | --- |
| A 对象/方法研究 / 无 | 从对象资料提取能力、实现条件、证据和可比项；市场实例比较产品功能，技术实例比较方法机制 | 按剩余对象材料组补全表；核对来源和不确定性，交付对象证据表 |
| B 需求/标准 / 无 | 从应用资料明确用户问题、适用场景、评价标准，区分需求与推断 | 补充遗漏场景；核对标准是否来自输入，交付需求—标准表 |
| C 背景/限制 / 无 | 从外部资料提取成本、生态、部署、时间/地域限制；不捏造缺失市场统计 | 核对资料口径与冲突，交付限制与背景证据表 |
| D 匹配与比较 / A,B | 建立对象—需求/标准比较矩阵，每项引用两侧证据 | 检查可比性与过度推断，交付比较结果 |
| E 背景下的评价 / A,C | 分析外部限制怎样改变对象选择/竞争定位 | 检查每个结论的依据，交付条件化评价 |
| F 缺口与启示 / B,D | 找出需求未满足项及其实际意义 | 区分证据支持的缺口与猜测，交付限制与启示 |
| G 报告综合 / E,F | 根据带引用的两项综合产物回答原问题、形成报告 | 核对问题覆盖、矛盾、引用，必要修订后提交最终报告 |

仓库评审的角色与逐轮请求见 [既有具体设计](../workload-decision-20261004/README.md#4-第二场景真实仓库-issue-的变更评审)。依赖为 A/B/C 起始；D←A,B；E←B,C；F←D；G←C,D；H←E,F,G。A 形成行为契约，B 说明实现与调用关系，C 核对已有测试，D 分析根因，E 分析兼容风险，F 提出改动方案，G 提出测试方案，H 综合评审。每个角色都有形成产物、代码/证据核查两个独立调用；多文件资料按原有文件/符号边界分组。生成阶段不提供 gold patch、test_patch、答案测试列表、rubric 或参考报告。

主实验测量 **资料已准备好的分析与生成阶段**：资料准备独立计时并冻结内容。主版本无工具；另设真实本地只读文件查询版本及原样在线检索参照，所有工具时长计入各自 WCT。若提出“短工具”claim，报告次数、median/p95/max、工具等待占比和工具位于实际关键路径的比例，不能删掉长调用后称原始执行。上下文超限、轮次上限、质量失败都保留，统计覆盖率；自然任务不 padding、截断或复制 DAG。

## 要回答的论文问题与完整实验矩阵

| 编号 | 要检验的问题 | 自变量与对照 | 主指标与图 |
| --- | --- | --- | --- |
| E0 应用有效性 | 应用是否有用并实际符合论文负载范围？ | 两应用、领域/仓库、自然资料规模；原样外部参考单列 | 质量、完成率、每 Agent 轮数、公共 token 前缀、请求衔接、实际并行；F1 工作负载画像 |
| E1 状态与重建 | 历史增长是否产生有意义的恢复成本/容量压力？ | 同一真实输入的自然长度分组；短/长任务全保留 | 完整 KV/元数据字节、重建/完整 DRAM/增量 HBM 恢复、健康复制开销；F2 成本曲线 |
| E2 workflow 优先级 | Slack 是否改变保护价值，算法是否用对它？ | cost-only、zero-slack、predicted-slack、oracle-slack，预算一致 | 故障时 Slack 与重建延迟联合分布；选择差异、配对 WCT；F3 暴露与选择 |
| E3 主要端到端收益 | 同预算是否改善失效条件下完成时间，代价如何？ | 主 baselines × 两应用 × 低/中/高负载 × F0/F1 | paired WCT/penalty、尾部、完成率、健康成本；F4 主结果 |
| E4 共同故障影响 | 单 worker 失效影响多个 Agent/job 后是否仍有效？ | 一个活跃 Agent、同 workflow 多 Agent、跨 workflow 多 Agent；实际 victim 集合记录 | 直接受害/共享资源间接受害/其余全部 job 的 WCT，故障影响窗口；F5 恢复扩散 |
| E5 Peer-HBM 增量 | DRAM 完整覆盖之后，HBM 真能减少等待吗？ | DRAM-only vs HBM，Agent 集合/DRAM manifest 不变；同字节 recency/random/past-count/oracle | 暴露 H2D 等待、完整重建尾、重试延迟、去重需求字节命中、HBM 成本；F6 区域与流水线 |
| E6 组件消融 | 三个机制分别贡献什么，有无交互？ | workflow selection × Top-K HBM × adaptive quota 的 2×2×2 设计 | paired WCT、HBM/DRAM bytes、健康 TTFT/TPOT、控制开销；F7 消融 |
| E7 动态容量 | Adapter 是否保护前台并利用闲置容量？ | steady、低→高→低、突发；fixed-small/fixed-large/adaptive | serving need、safe ceiling、quota、实际副本、驱逐/重拷贝、TTFT/TPOT/OOM；F8 时间序列 |
| E8 预测与保护误差 | 可部署的因果预测是否足够好？ | 历史均值/角色 prior、当前回归器、oracle；训练分组独立 | 剩余时长 MAE/p50/p90 相对误差、Slack 偏差、漏保护率、WCT regret、O(|V|+|E|) 开销；F9 误差与代价 |
| E9 敏感性/扩展性 | 优势在哪些资源/算法边界消失？ | λ、Z、K、L、DRAM/HBM 容量、实际带宽、并发、worker 数 | WCT 与健康开销、复制 lag、选择成本、零/负增益区域；F10 扫描 |
| E10 恢复正确性 | 部分/陈旧/传输中状态是否安全？ | prefill/decode、中途 TP shard 丢失、未提交复制、peer 不可达、重复失效、收缩期间 failure | token/产物一致性、可达 manifest、幂等工具、回退、所有失败计数；T2 正确性 |
| E11 成本权衡 | 正常开销能否被恢复收益抵消？ | 同人口/同到达 trace 的 F0/F1；单独受控故障频率扫描 | 同一 objective 的 H 与 D、故障条件增益、假设性 break-even；F11 权衡 |

主文建议 7 个互补测量图（F1–F7；F8/F9 如篇幅允许进入主文），附录放敏感性、正确性、完整分组表与负面案例。论文图编号交由 LaTeX；这里的 F1–F11 是实验图规格 ID，不是当前论文编号。图的精确数据契约见 `FIGURE_SPECS.json`，设计稿见 `exports/workflow-paper-revision-20261005/experiment-figure-atlas.pdf`。设计稿没有假数据、趋势或误差条。

## Baselines：公平预算与实现身份

全部策略共享模型/tokenizer、正常前缀缓存、编排、队列/批处理、retry 路由约束、token 耐久日志和故障检测。只改恢复保护策略；普通 prefix cache 的已有 DRAM 若可在本故障域恢复，必须计入 baseline 的实际恢复资产。

| 对照 | 定义与作用 |
| --- | --- |
| Restart | 无额外容错副本；使用仍可达的普通缓存；不足部分从耐久输入重建 |
| Fixed checkpoint | 不用 workflow Slack，固定 Z，在相同 DRAM 预算下按先到顺序保护，作为朴素覆盖对照 |
| Cost-only | 按完整重建 T 降序保护，使用相同 Z、DRAM/HBM 字节预算，隔离 Slack 贡献 |
| Aegis-DRAM | 当前 E=[T−s]+ 选择与完整 DRAM checkpoint；无 HBM 副本 |
| Aegis-fixed | 同选择、Top-K×L，固定 HBM quota，隔离 Adapter |
| AegisKV | 同选择、区域策略与 guarded AIMD；现有完整算法 |
| Full-DRAM feasible reference | 有容量时保护所有 Agent；容量不足时明确溢出/拒绝，不能给它隐性无限 DRAM。另列无限容量 ideal 参考，不算公平预算 baseline |
| External fault-tolerance system | 优先复现公开 DéjàVu/LUMEN/GhostServe 的可适配实现。复用论文思路自行实现只能标为 inspired proxy，不能借系统名字声称复现 |
| Oracle references | 真未来剩余时间/需求仅在离线 oracle 分析中使用；必须与实际故障受害集合与预算匹配，不用于在线策略 |

Parrot/KVFlow/TOPAS 优化正常 serving，是互补机制。采用其公开实现做外部健壮性检查时，所有恢复策略在同一个正常 backend 上比较；恢复启用与否的配对差才支持 AegisKV claim。未适配的正常缓存算法不直接命名为 fault-tolerance baseline。Top-K 对照使用完全相同物理字节、层范围、sink/local-window 配额与元数据，seed 固定；观察 native 模型完整所需恢复，不把选中历史 blocks 的 hit ratio 等同于恢复时间。

## 测量平台与物理证据

主平台目标为至少两个同型号、同 TP 配置的兼容 model replicas，源和备份位于独立保护域；TP=2 时至少 4 GPU，跨 host 失效实验需要真正独立 host。硬件以实际可用平台冻结，当前本机 `nvidia-smi` 无可用驱动，不记录虚构已部署平台。可选多 worker 扩展单列；不可将其他机器或静态带宽估算拼成主实验。

主 native-sparse 候选为现有适配范围内的 NOSA-8B、NSA-8B、MiniCPM4.1-8B；实际权重版本、kernel、forward、TP 支持和生成质量必须先过 pilot。至少一个支持真实生成和完整恢复的 native 模型用于端到端，第二模型做泛化。若 adapter/训练权重不支持当前应用，不用随机 token 或 CPU 参考 top-k替代；报告不适配并补实现。可增加 dense 模型对 Agent 选择泛化，dense 结果不证明 sparse Top-K 收益。不同模型每个都按自己的 tokenizer 执行相同真实文本任务；不要求跨模型 token ID 相同。

平台清单冻结 GPU/CPU/DRAM、PCIe/NVLink/NIC/NUMA、DP/TP/GQA、精度、每 rank KV layout、block size、native metadata、软件 commit、权重/tokenizer SHA、kernel、batch/scheduler、warmup、日志开销、故障检测 interval、durable tokens、DRAM/HBM 实际预算。KV 统计所有 TP shard 与 attention metadata；同一物理副本只记一次，pending/committed/evicting 都占实际容量。复制 bytes、HBM occupancy、队列时刻与 CUDA timeline 各自来源必须明确。

恢复微测量用同一被冻结 prefix/接受尾/选取集合，在同一 retry worker 上比较 restart、完整 DRAM、DRAM+HBM、bulk/layer-order。输出 fault→detect→target/admission→manifest-ready→H2D/compute→resume→Agent/task/job complete 时间戳。传输与计算重叠用 union timeline 计算，不能把阶段均值相加代替 wall time；实际 H2D 同时测 contention。完整物理恢复必须加载全部 required state，只有 Top-K 的理想 toy pipeline 单列 analytical。

当前设计 checkpoint Z=256、block=64；按 Z 触发不保证故障时 tail≤Z。记录生成 frontier N、committed frontier M、pending copy 和 lag=N−M，传输积压时实际重建 lag 全部计时。尚未提交 TP shard 不得作为完整 checkpoint，恢复到最后完整已提交 frontier。

## 配对故障和到达协议

先用无故障新执行冻结真实应用内容、依赖与 token。两条证据轨分开：

1. **实际生成与质量轨**：真实模型在线运行，记录产物与得分；无故障/故障检查正确性与质量。内容分叉、停止条件变化都记录，不能强称完全同输出。
2. **确定内容的 serving 轨**：固定输入/真实 output token，保留每个 Agent 的顺序、前驱完成约束与自然非服务延迟，由当前策略实际完成时刻触发后继；故障重建和模型/kernel 仍物理执行。不得把 F0 的绝对 invocation start 强塞进 F1，从而禁止 workflow 的延迟传播。

job 外部 arrivals 相同，不等前一个 job 完成才释放下一个。主负载用无故障能力 C 的 30%/60%/85% arrival rate（C 在校准集测定并冻结），Poisson 与突发序列都保存；单 job/固定并发作为诊断。并发 1/4/8/16/32 只在硬件可承载范围内扫，不默认为每点可行。

每条 F1 对自身策略 F0 做差 P_p=WCT_p,F1−WCT_p,F0；主 comparison 同时报 WCT_A,F1−WCT_B,F1 与 P_A−P_B，健康开销另列。逻辑故障绑定 (job,Agent,invocation,phase,accepted-token/chunk)，不以“80%总完成”替换未定义具体调用；主位置 early/middle/late 在校准 trace 对应 25%/50%/75%已接受 token 的具体 landmark，prefill/decode分别设计。自然故障在固定 worker 的 wall time 注入，实际 co-victims 可能因策略不同而不同，单列部署证据；受控机制实验可固定 route/受害状态，说明强制条件，不伪称自然相同 victim。两者都记录 pending/queued/resident KV，而不仅当时 executing batch。

主域为 fail-stop worker/TP group；故障时使其 KV 真正不可访问并停掉整个 group。process failure、host failure、GPU reset分别陈述，不用清单纯 tensor当作硬件宕机证据。健康 worker 保持 serving，不人为把整个集群暂停，除非标明独立 coordinated-pause 诊断。peer unavailable/repeated failures属于超出单 surviving-target 主假设的鲁棒性实验，记录回退和未完成，不宣称全部可恢复。

## 统计、质量与样本量

- 每应用约 20 个校准任务起步；不以此宣称统计充分。按任务来源分组拆分训练/校准/测试，research 按原题/来源文章聚类，repository 按 issue、仓库做 grouped/leave-one-repository-out。任何同题 invocation、多个故障位置、种子及重复运行不充当新的独立任务。
- 适配性筛选在看恢复收益前完成；任务列表和排除理由全公布。以 pilot 的 paired effect 变异和预注册精度决定测试样本量；默认目标是 mean paired WCT 改变量 95%CI 的半宽不超过相应基准 mean WCT 的 5%，并检验 10% 的工程相关效应。达不到则报告实际精度，不靠重复单例扩充 n。
- 固定 arrival seeds，至少 3 个独立 arrival/执行块检验运行波动，hardware microbench 每单元 5 次预热后至少 10 次 timing repeats，并保留顺序/温度/负载。timing repeats不提升任务泛化样本量；cluster bootstrap 的上层是 task/source 与 arrival block。
- 主统计用 paired difference、mean/median/p95 WCT、cluster bootstrap 95%CI；p99 只有独立 cohort/足够 job 支持并做稳定性分析时才作为主结论，小样本只列描述性尾部。predeclared timeout作为失败，不从分母删去；报 completion率、censored延迟、最长尾及总 backlog。
- 每种策略的 F0 同时测 job WCT、TTFT、TPOT、throughput/goodput、CPU/显存/复制开销。SLO 从应用要求或独立校准冻结，不以最佳结果倒推。无直接受害 job 不等于不受间接影响，需要 shared retry/bandwidth/queue 拓扑和时间戳。
- 研究报告用来源核查、问题覆盖、证据支撑和独立 rubric；DRB/DRB II judge/version、人工盲审抽样都冻结。离线材料版本的任务限定覆盖所给材料，不能沿用原始在线 benchmark leaderboard score。仓库评审按根因、代码引用、改动合理性、可执行测试方案与人工复核评分；不报官方 SWE-bench solved%。
- HBM 增量和预测性能可以为零/负；保留短任务、带宽充分、访问分散、共同故障、预测失准等完整分组。不能先筛有益失败再画 CDF。

## 参数与成本边界

Z 默认256，扫64/256/1024；β/ε使用当前算法值并冻结后再独立扫。λ比较0、校准 T 分布的低/中/高分位对应秒值，不能根据测试收益定。K比较0与若干合法block budget，L比较1、离线模型选择与全层；组合同时报告实际HBM bytes，固定 K×L扫描与同字节allocation扫描分开。DRAM用峰值全保护KV容量的0.25/0.5/1.0预算，HBM用safe剩余空间的0/5%/10%/20%；实际分配不越safe ceiling。带宽要实际测或受控限速、并报告限速工具与干扰，不拿 nominal peak填到“实测”。

F11 在同一个 task人口、同一个 WCT/总WCT objective 上定义健康成本 H=W_A,0−W_B,0，故障条件节约 D=W_B,1−W_A,1。假设二元混合下净改变量 (1−p)H−pD；H,D>0时 break-even p=H/(H+D)。这是指定故障分布的假设分析，不是部署故障率或全年可靠性保证。直接受害与全 cohort分别计算，不能用单例D抵消全群体H。

## 执行顺序与完成门槛

G0：输入/许可证/版本、真实资料包、角色DAG、逐轮提示与排除规则可复核。G1：两个起步实例实际运行，完整历史与所有required前驱字段齐全、无隐式屏障；采集真实token/质量/工具/衔接。G2：新无故障pilot、真实并行、前缀增长、资源画像，按精度冻结测试集/模型/负载/参数/故障。G3：commit/frontier/TP正确性、故障注入、预算和日志通过。G4：E1/E3/E5物理主结果与F0，所有图可由原始数据重建。G5：消融/预测/动态/共同故障/负面/敏感性完整，外部系统身份准确。G6：独立审查统计、claim—图—输入哈希、论文编译与最终尺寸阅读。

当前仅提供设计、机制图和图表规格；G1–G6 未执行。不把“协议/静态审查通过”升级为性能通过。正式结果发布条件由 `CAMPAIGN.json` 的门槛控制。需要硬件时执行物理测量，不能用旧 PG19/单前缀图作为这两应用的实测替代。

## 相关工作借鉴与边界

| 原始论文 | 借鉴的实验方法 | 本设计补充 |
| --- | --- | --- |
| [Parrot, OSDI 2024](https://www.usenix.org/conference/osdi24/presentation/lin-chaofan), §8 | 多类应用、MetaGPT 分工与依赖、应用时延和请求负载扫描 | 任务节点/内部调用分离；故障恢复与质量同时测 |
| [KVFlow](https://arxiv.org/abs/2507.07400), §4 | 单 workflow/高并发、GPU与host缓存、传输重叠对照 | 真实文本连续历史；不借其随机token微基准证明native需求；加入失败域 |
| [TOPAS](https://arxiv.org/abs/2608.25523), §V | 共用固定arrival trace、JCT/tail、真实MetaGPT任务与syntheticDAG分列、scheduler开销 | 只把正常调度视为互补backend，测恢复条件WCT和健康成本 |
| [DéjàVu, ICML 2024](https://proceedings.mlr.press/v235/strati24a.html), §5 | streaming微基准、正常执行开销、失败恢复；同一实现逐优化对照 | 有限字节预算、整Agent历史、所有TPshard提交与checkpoint lag |
| [LUMEN](https://arxiv.org/abs/2606.17787), §6 | interrupted/uninterrupted、TTFT/TPOT故障窗口、No-Failure、负载与重复 | 增加明确任务DAG与配对WCT；承认其负载感知协调，不泛称它只恢复不选择 |
| GhostServe, MLSys 2026, §6，仓库已有原文PDF | 模型/长度范围、healthy/faulted成本、checkpoint/recovery权衡 | 自然任务为主，合成压力单列；明确原文buffer清空/暂停与本实验fail-stop不同 |

上述方法来自原始论文，不意味着已经移植系统或拥有对应公开服务trace。更多 figure协议及数据字段见本目录 JSON 文件。
