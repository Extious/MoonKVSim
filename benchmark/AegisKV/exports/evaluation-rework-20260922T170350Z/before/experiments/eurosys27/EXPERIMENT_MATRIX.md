## 当前互斥三层主策略（2026-09-21）

KV Master 按 Slack/访问概率→共享信用/Lazy refresh→固定配额 Peer→在线三层执行叙述。三层并集覆盖 checkpoint，同一对象稳定态仅有一个 owner。下层用独立租金，Peer 不计租；L/K/Z 在模型校准后冻结，Adapter 只调 Peer 总额。实际新 use 续租；attention 统计、Slack 变化、checkpoint 增长与迁移保留已付金额。在线不再做全局 WCT 整方案搜索。

新增配对设计：

- 原始次数 vs 按因果可见机会归一化概率：固定未来 Query、块年龄、冷启动和字节预算。
- Lazy vs eager：相同工作预算加不限预算 eager 参考，记录候选排序误差、淘汰差异、扫描年龄、CPU、WCT。
- 固定 Peer slot：同 L/K/Z、同物理预算比较 FCFS、recency、Slack、恢复收益排序；自适应 L/K 与小规模 oracle 仅作为参考。按 workflow 隔离校准/测试，扫描 M/N、负载和模型。
- 下层信用：同估值/机会/工作预算的直接重估、普通 GDS/Landlord、无续租、无压力 aging、无多 Agent 份额。原 462.96/506.39 及修正负例保留。
- 固定额度 vs AIMD、互斥 vs 重复后备；实际执行中记录 temporary bytes 与 Peer→DRAM→storage 级联。

必须覆盖：同 Agent 工具往返、同角色 prefix、Slack 大→小、旧前缀不因增长续租；完成 slot 优先回收、活跃按 Slack 降序、普通同值不抢占/强制 shrink 同值按 request-use recency；physical lease 阻塞；满下层等待；迁移交接前/后失败；唯一 owner 丢失；最后副本 fallback；各 pool 账目停计及往返保留；最终短 snapshot。旧版静态检查与旧分析模型不验证新控制器，当前不启动物理实测。

# 完整 Evaluation 实验执行与图像设计

2026-09-21：按用户要求，当前阶段**不限制 12 页**，实验设计保持全面，正文只保留必要图像。Evaluation 现有 **8 张单栏核心图、17 个完整实验小节**；本矩阵的所有运行、指标、对照和参数扫描均保留。其余图在实验包中作为补充/备用，不因未放入正文而取消对应实验。选择依据见 `FIGURE_SELECTION.md`。正文是完整研究草稿，下面是可执行实验规格，不是宣称已经完成物理实验。

## 三层设计增补（2026-09-21）

当前设计为 **Peer HBM＋DRAM＋Shared storage 互斥驻留**。以下既有 DRAM/storage 分析是旧完整 checkpoint、Peer-disabled 策略，部分 DRAM layer model 是独立机制分析；均不验证当前混合在线控制器。

新增配对 cells 固定跨层完整覆盖、原生 demand、fault IDs 和调度：Peer=0、等字节 recency/frequency、固定配额 Slack 准入、自适应 L/K 参考。扫描 Peer 占 managed HBM pool 的 0/5/10/20%（实验参数，非默认），同时扫描 D/S 容量。策略共用物理 HBM 和 open-loop 流量，计入正常服务挤占、提升后释放下层对象、实际降级流量与临时双份，不给 Peer 免费显存。做 Peer 位置×overlap 四格，独立扫描 M、真实 N、Z、热集、额度窗口和 rebind。

新增字段：takeover_dp、binding_version、configured L/K/Z、slot_member/evictable、hot_set_version、request_use_age、physical_read_lease、peer_budget_target、reserved/committed/retiring/free_bytes、object_owner、owner_epoch、跨层 manifest、临时 copy bytes、D/S grant/paid/clock/use_epoch。输出同-ID WCT、暴露等待、移动及未用预取字节、healthy throughput 和摊销净收益。旧 5,400/160 runs 示例未含新 cells，冻结预算时重新核算。

正确性要求目的端完成→目录切换→读者排空→释放源；迁移未完成不能计为空闲。下层满时必须级联腾挪或延后；最后副本删除发布所有受影响 manifest 的有效旧 checkpoint／replay fallback。工具切换将 slot 标为可淘汰，实际 lease 仍保护读取。保护的 source failure 不能丢失全部覆盖中的 owner；额外 sole-owner loss 测试 fallback，而非假定仍有完整 DRAM。无法提交扩展时 M 不变、记录 N 增长。本轮不启动实测。

## 1. 需要证明的主线

1. **一次故障是否减少 WCT？** 先和同样可靠覆盖、同样预算的 DRAM/storage LRU 比，再和 Recompute 比，防止把 checkpoint 本身的好处当成工作流策略的新贡献。
2. **为什么减少？** 保留对象 → 各层/块读入与 replay → request ready → 各分支完成 → join → WCT。另列总字节、总 GPU work 和整个恢复池占用，不把这些量混在一起。
3. **会不会把代价转给别人？** 观察直接受故障影响的 workflow、共享资源但没被 kill 的 workflow、独立资源对照；确认共享 reader/NIC/GPU 后才解释排队传播。
4. **真实故障模式下是否仍有效？** 保留实际日历及故障簇，单独处理缺失字段、节点映射、修复与连续容量损失。平均收益与 p95/p99 都要看。
5. **复杂设计各自有没有贡献？** 价值、共同故障、直接重估/迁移滞回、稀疏需求/overlap、路由均有独立对照；下层租金／续租是待验证主机制，Peer 固定配额按 Slack 贪心，强交互用四格实验。
6. **代价与边界是什么？** 正常服务、故障稀有度、SSD/网络拥塞、预测误差、有限 storage、保护覆盖、协议正确性和控制开销。

## 2. 实验单位与冻结文件

每次正式运行保存 `runs.jsonl`、`workflows.csv`、`requests.csv`、`events.jsonl`、`predictions.csv`、`correctness.csv`，字段沿用 `DATA_CONTRACT.md` 与 `PROTOCOL.md`，新增：

| 文件 | 必须增加/保留的字段 | 用途 |
|---|---|---|
| runs | experiment_id, campaign_id, pair_id, mapping_id, workload_hash, fault_trace_hash, source_revision, code_revision, arrival_seed, fault_seed, topology_id, backend_id | 唯一关联物理运行，区分 trace/model/measurement |
| workflows | workflow_id, release, finish, deadline, status, direct_fault, shared_reader, shared_link, shared_target, original_cohort | 分组与 intent-to-treat 统计；未完成也必须有行 |
| events | event_id, parent_ids, resource_id, request/Agent/workflow_id, epoch, release/start/end, bytes, source/tier, GPU_stream, layer, shard | 还原真实依赖与关键路径，不能把重叠时长相加 |
| checkpoints | trigger_tokens, acknowledged_tokens, committed_tokens, trigger/start/commit time, manifest, failed_write, storage_domain | 测量实际 N、copy lag 与可靠覆盖 |
| controller | snapshot versions, incoming/victim IDs, candidate/victim evaluations, DAG passes, accepted, priority, materialized_version, scan_age, rejection_reason, lease eligibility, reserved/released bytes, CPU_ns | 验证新分层租金主策略；记录 per-Agent grant/paid-rent、trial/committed clock、renewal、revalue；direct 为同预算对照 |
| trace mapping | original_system/node, destination_failure_domain, event group, raw_row_ids, original/transformed time, down/up, mapping_seed | 可复算缩放/聚簇/容量映射 |

**一级单位**是独立启动的 paired campaign；每个 campaign 含多 workflow，每个 workflow 含多 request/层/块。三层数量都报告。默认 10 campaigns；30 个独立 workflow/family 是工作负载对象数，不能写成 300 个不同工作流。各策略各有自己的 healthy mate。分析顺序：同 ID 配对 F1−F0 → 同 campaign 策略差 → campaign 聚合/置信区间。

## 3. 固定的公共矩阵

| 维度 | 正式设计 | 必须保持的公平性 |
|---|---|---|
| 拓扑 | DP 2/4/8；TP 1/2；1/2/4 个故障域 | DP/TP 不混为一个维度；真实目标容量与 failure domain 分开记录 |
| 模型 | dense Qwen3-8B；Qwen2.5-7B-1M；额外 MiniCPM4 native sparse | 固定 checkpoint、kernel、精度与原生选择语义 |
| workflow | coding、FanOutQA、受控 fork/join/sequential | 原始 DAG 一次，完整 prompt 分母，保留首轮与负例 |
| 长度 | 32K、128K、512K、1.01M（仅支持的组合） | OOM/不支持明确记录，不填理论值冒充实测 |
| 负载 | 基线健康可持续吞吐的 30/60/85% | 所有策略使用同一绝对 open-loop arrival trace；报告丢失副本后的负载 |
| DRAM | unique working set 的 0/10/25/50/100% | 同预算；共享物理对象仅按实际 replica 计费 |
| storage | working set 的 0.5/1/2 倍 | 小容量必须触发真实 last-copy eviction，不假定无限 backing |
| 后端 | local NVMe、remote NVMe、shared filesystem | 不互换名称；shared server cache 不可控就明确标注 |
| 故障阶段 | matched 20/50/80/95% progress；prefill、decode、tool wait、commit 边界 | 同 workflow/Agent/request 及逻辑进度，不能统一 wall-clock 时刻后宣称进度一致 |
| checkpoint | Z 64/256/1024；多写入带宽/队列上限 | 相同触发规则；完整系统比较保留实际 achieved frontier 差异 |

主矩阵不用盲目全笛卡尔积。先冻结 primary cells；其他扫描每次只变指定因素。示例主矩阵为 3 workload families × 2 models × 3 loads × 3 DRAM ratios × 5 policies × 2 conditions × 10 campaigns = **5,400 runs**；每个 run 可含多个 workflow，运行时间须用 pilot 实测估计。单个机制验证 pilot 可先使用 1 family × 1 model × 2 budgets × 1 load × 4 policies × 2 conditions × 10 campaigns = **160 runs**，它不能替代整个主矩阵。

## 4. 单次故障：完整分解实验

### F1：WCT 与受益人群

- 注入：主 cell 为同一 Agent 的冻结总 token progress 80%；kill 整个 source replica，纳入全部共置 request。
- Attribution run 冻结 pre-fault placement/routing、输入历史、committed coverage 和 transfer scheduler，只改变保留决策。Full-system run 放开策略实际前沿、路由与 placement，成本全计入，不能混成同一张“纯策略”图。
- 路由使被影响 workflow 身份变化时，以固定原始 arrival cohort 做 intent-to-treat 统计，再展示实际 interrupted 子组；不能每个策略只挑自己完成得快的样本。
- 主结果：绝对 WCT、D=F1−F0、paired LRU−Aegis、completion/deadline goodput、各 family p50/p95。
- 数据必须同时保留分布与同-ID差值：正文展示 `eval-workflow-outcomes` 并报告配对统计；`eval-paired-benefit` 作为补充图，配对计算仍为必做项。
- 可推翻条件：只有对 Recompute 有收益，对 tuned LRU/reuse-only 无收益；或健康回归抵消故障收益。

### F2：分支与关键路径归因

- 对同一冻结故障记录所有 affected branch 的 residual DAG 和故障时 Slack，不能用总 branch 时长差冒充 Slack。
- 输出 raw request-ready、branch-finish、join-finish、whole-WCT。图 `eval-branch-exposure` 显示恢复与裕量的关系。
- 关键路径日志按父事件连接，列 floor、admission queue、SSD read、NIC、H2D、required replay 与 join waiting。物理关键路径只累加路径上不重叠区间。
- 图 `eval-recovery-attribution` 当前使用固定 placement 的有序 counterfactual：floor→read→NIC→H2D→replay。增量相加等于最终 WCT penalty；交互归属依赖顺序。实测替换必须明确是同一种 counterfactual 还是重新定义后的 critical-path intervals。
- 图 `eval-storage-traffic` 独立报告字节；另外汇总 GPU work、pool busy time、unused/duplicate bytes。不能把优先级优化宣传成总工作减少。

### F3：拥塞传播与恢复尾部

- 1/2/4/8 simultaneous affected workflows × 1/2/4 targets × 固定三档负载；另设 reader/NIC 独立对照。
- cohort：直接失败、共享资源未失败、隔离资源未失败。记录 queue occupancy 随时间及恢复到预声明 latency band 的时间。
- `eval-burst-interference`：burst size → direct cohort mean penalty；配套实测表应增加 collateral cohort series。
- `eval-background-backlog`：时间 → 实际 backlog bytes，使用 reader/NIC queue 明确资源名。已有 fluid 曲线不是 TTFT。
- 运行到恢复完成或统一 τ，所有被丢弃/超时 workflow 纳入 completion 分母。
- 可推翻条件：只改善第一个 request，延迟转嫁导致 cohort 总成本或 p99 变差。

### F4：故障位置与 commit lag

- `eval-logical-fault-phase`：同 ID 的 20/50/80/95% 进度；prefill/迁移中失败另列不能插值冒充 decode。
- `eval-checkpoint-lag`：实际 commit lag → replay/WCT；记录 N 是否大于 Z。
- 同 Z 的理论图应逐 phase 配对后平均；实际图使用 achieved frontier，不能用 Z/2 代替日志。
- 分析短 Z 的潜在负效应：write backlog、copy contention、failed commits、normal service regression。

## 5. 真实 trace：从审计到持续故障重放

### T0：当前取得的数据和边界

**LANL**：官方语义来自 <https://usrc.lanl.gov/data/failure-data.php> / <https://www.usenix.org/cfdr-data>。原始 FTP 不可达，当前使用版本钉住的公开 CSV redistribution，记录在 `trace-source/lanl/SOURCE.json`；镜像 23,739 行，官方 23,741 行，**差异尚未解释，不能声明原始档案字节一致**。只使用原始格式文件，没有使用仓库中的 ML 加工标签。

清洗：purpose 严格为 compute；非 compute 1,648；零长度 122；同节点重叠/相接合并 231；保留 21,738 outage intervals，22 systems，3,542 observed nodes。零负时长、零不可解析 compute 行。所有原始行号进入合并记录；合并是物理不可用区间解释，不是挑选低成本事件。没有以 observed faulty nodes 代替 fleet exposure。

**Reflex/ByteDance**：官方 revision `89f843a78b1a278e430215cf23800c9fac6e43c0`，98 jobs、344,175 alerts、144 faulty node/job entries，其中 108 个 faulty labels 没有该节点 alert。各 job 独立平移时间，缺少 down/up；因此只画 `eval-modern-trace-labels`，**不**拼接日历或从 first alert 猜 crash time。所有相对时间检查限定 job 内。

### T1：当前可复算的条件恢复模型

- 一个 cleaned node start → 一个假设的四分支 workload，需要恢复；并不声称原 LANL 节点上实际运行 agent。
- 每 original system 使用独立 FIFO spare pool（2 targets）；保留 minute-resolution start 原间隔；并列按 node ID。
- 单次 pool service S=max(request-ready)，D=join penalty；q_i=max(0,q_{i-1}+S−Δa)，总 penalty=q_i+D。
- 同一批物理 placement 在 trace 前冻结；不能故障时用未来信息重新选择“已经在 DRAM”的数据。
- 原 rate 下 LRU mean 10.4533s，workflow value 9.4673s；p95 37.0375→40.0292s，p99 204.1208→232.1125s，负尾部保留。
- 当前模型假定 dedicated surviving pool 可用，不模拟 healthy arrivals、有限 spare、修复及 retry 再次失败。因此只称 **trace-driven recovery-load model**，不是 availability、SLO 或完整在线系统实测。

### T2：完整物理/仿真 trace campaign

1. 验证原始 archive、license、schema、时间单位/时区/分辨率、cause 与 maintenance；先冻结清洗，后看性能。保留原始全原因、去 maintenance、hardware-only 作为不同层级，并报告各层筛除数量。
2. 使用 source-system 独立日历；选择所有满足数据完整性的窗口，不挑最高收益的一天。若固定窗口长，保留稀疏/零故障窗口来估计正常开销。
3. 在策略比较前固定 workload→node/failure-domain mapping，公开 mapping seeds。比较 1/2/4 active workflows/domain 与不同 spare fraction，不能因为资源少就串行化故障簇。
4. primary replay 保留 down/up、原始事件间隔、故障簇；节点失效后减少真实计算容量、恢复后才返还。考虑 warmup/load/manifest availability；readmit 的模型权重装载单独计时。
5. 故障发生在 recovery 尚未完成时，保留第二次故障及其 target 故障域，不重置 trial 或跳过事件。storage-host failure 只有声明的副本/持久化域才能覆盖。
6. 仍按固定 arrival stream 发请求，报告所有输入 workflow 的 WCT/完成/超时/累计 goodput，三类 cohort 与资源 backlog。跨策略比相同 calendar blocks/mapping；不对每个策略单独归一化负载。
7. 控制：original timing；同系统 count/span 相同的 evenly spaced；保持事件组大小的时间置乱；clock compression 10/100/1000；观察到的 outage durations 与独立人工 repair 扫描分开。后几项均非原 trace rate。
8. 统计：event-weighted 与 system/calendar-block-weighted 两种聚合；不把同一故障簇里的所有节点当独立样本。bootstrap 保留整簇/整窗口，公布 window counts 与映射变化，不产生虚构物理重复。

### T3：图像布局

- `eval-trace-outages`：duration CDF，描述 trace，不画系统性能。
- `eval-trace-bursts`：同一分钟同系统 start 的 node-count CDF；承认分钟量化与相关性不可辨。
- `eval-trace-penalty`：模型或实测 penalty CDF，避免把 source 是真实 trace 当作 latency 实测。
- `eval-trace-queue`：intrinsic penalty / queue wait 两类条形。
- `eval-trace-system-benefit`：逐 system 的 paired benefit，保留负值。
- `eval-trace-burst-control`：original/even-spacing/within-minute spread 同源对照。将同分钟节点按ID均匀放入59秒只是分辨率敏感性，不是恢复真实毫秒时间。此时LRU/价值模型mean=8.0997/7.0224s，p99=163.8936/191.8852s，负尾部仍在。
- `eval-trace-time-stress`：原速与加速分开标注，x=1 是唯一本来事件间距。

## 6. 完整消融矩阵

| ID | 相对 full AegisKV 只改变的机制 | 固定项 | 关键指标/对应图 | 当前证据 |
|---|---|---|---|---|
| A0 | 无 DAG/Slack | state、rates、budget、normal lookup | WCT、ready/critical-branch；ablation-fault | static model |
| A1 | factorized priority → 较昂贵的 joint-DAG 参考 | source failure group、DAG、资源 | plan value误差、joint penalty；common-fault | 构造反例；完整campaign待跑 |
| A2 | 去掉 normal-reuse value | 正常lookup与backing安全不变 | F0 WCT/next-use，ablation-reuse | static model |
| A3 | 去掉 failure value | reuse与copy预算不变 | 正常/故障frontier；reuse-only对照 | static model中的reuse-only |
| A4 | 冻结placement，不随DAG/进度更新 | 相同起点与允许搬迁预算 | phase / pressure / changed plans | 物理campaign待跑 |
| A5 | direct revaluation 去掉主策略的租金筛选 | 相同value、候选机会和安全检查 | candidate/victim checks、DAG passes、CPU、WCT、churn | isolated additive model；396为scalar替换比较次数 |
| A6 | 在新租金主策略上去掉实际使用触发的 renewal | aging/safevictims不变 | reusemiss、expired/leased keys、migration | 旧简化模型仅提供局部证据；新主策略待集成验证 |
| A7 | lazy → eager refresh | 相同估值，分别固定预算与不限预算参考 | victim rank、CPU、WCT、scan age | 待执行；旧 hysteresis 反例仍保留 |
| A8 | opportunity-normalized rank → raw counts / recency | native attention、coverage、物理bytes、mandatory blocks | all-layer coverage、unused/miss bytes、WCT | 构造需求模型；native实测待跑 |
| A9 | bounded pipeline → serial | 需求、两层staging、DRAM、rates | exposedwait、total replay、WCT | eight-layer model |
| A10 | load-aware router → locality-only | surviving compatible targets、same failures | direct/collateral/tail、targetqueue | FIFO压力揭示需求；完整路由待跑 |
| A11 | 单块近似 → bounded-pair 参考 | 同估值输入、预算、候选上限 | oracle regret、CPU、whole-plan benefit | common-fault + small oracle；完整campaign待跑 |

交互实验必须保留四格：Slack×共享份额、A8×A9、A5×A7、A10×shared-link contention。定义 interaction=(Y11−Y10)−(Y01−Y00)，所有项同campaign/同ID配对；这个量不能从两个独立speedup相加得到。物理图沿用相应同单位 panel，添加 series 即可；没有结果的 ablation cell 留空，不填 0 或理论数伪装完整实测。

安全协议不是“可关掉以提高速度”的有效性能消融。epoch fencing、lease、COMMITTED 完整性、last-copy fallback 分别通过故障交错验证。

## 7. 其他必须完成的实验

| 实验 | 变化因素 | 观测/失败判据 | 图 |
|---|---|---|---|
| S1 稀疏与overlap | equal-byte early/late × serial/pipeline；真实history rank；prefetch准确度 | 等coverage，不改native选择；compute和exposedwait分开 | layer-factorial / layer-exposure / sparse-misses |
| O1 在线重估 | 平滑漂移、突变、上下文增长、重复visit、压力；direct/旧 rent/新 rent/门槛 | 少migration但更高miss不是成功；记录离线完整DAG对照、在线工作预算与CPU；主策略记录 grant/paid/trial/commit/renew，并区分 value refresh | rental-churn / rental-revaluation / rental-cost，保留历史简化结果 |
| C1 DRAM/storage容量 | 同budget、storage finite、metadata与retiring计费 | actual coverage、last-copy fallback、workingset | capacity-frontier |
| C2 I/O资源 | read/write/NIC/H2D rate、并发、cache状态 | bottleneck转移、commitlag、queue、byte | storage-bottleneck |
| P1 预测鲁棒性 | causal heldout、±10/25/50/100%、缺边、staleprofile | decision regret、falseSlack、fallbackcost；保留负例 | prediction-robustness |
| H1 正常服务 | F0原DAG一次、固定arrival、同保护预算 | absolute WCT/TTFT/ITL/goodput/CPU/GPU；request/tokenhit分开 | healthy-io仅I/O；服务指标单独命名 |
| H2 摊销边界 | faultprobability、horizon、measuredhealthycost | net objective = conditionalfaultbenefit − amortizedcost | rate-break-even |
| Q1 正确性 | 16类copy/commit/redirect/lease/epoch交错；fulltiers | PENDING不可读；accepted output不重复；完整分片/选择器 | correctness.csv + safe-demotion |
| Q2 压力迁移 | DRAM24→16→24GiB，写堵塞，lease重叠，targetloss | target不等于free；物理bytes直到safe release才扣除 | safe-demotion |
| G1 扩展性 | DP、DAGnodes/edges、groups、candidatebudget、profilecount | decisionp99、lock、planage、queuebound、actualWCT | controller-scaling（当前只有操作投影） |

## 8. 图像与替换数据的固定契约

所有当前图保留 PDF/SVG/PNG、逐点 CSV、manifest 和代码。画布宽 3.33465in，字体至少约10.3bp，线型/marker/纹理辅助灰度辨认，单独画图例，不采用 tight-bbox 改变最终物理字号。值域根据数据扩展，保留负值/尾部。CDF 只对相同定义和分母使用。

图像注册表为 `figure-specs.json`；含 kind、xlabel/ylabel、unit、evidence。数据 `experiments/data/eurosys27/expanded/eval-*.csv` 包含 figure/panel/series/x/y/category/lower/upper/unit/evidence/scenario_id/source_id/independent_runs。只替换同指标的数据时无需改绘图代码或LaTeX；若改了指标语义（例如 I/O response→TTFT），必须新建正确标注的图，不能悄悄改标题。

`FIGURE_CATALOG.md` 按正文/补充分组，逐图列出问题、证据、图注、CSV。`plot_expanded.py` 默认绘制全部 registered cells，`--publish` 只发布 `main-figures.json` 指定的 8 张正文图。`eval-value-ablation` 并列展示原 `eval-ablation-fault` / `eval-ablation-reuse` 的相同聚合值，两个单指标视图继续留在补充包；没有新样本或跨指标相加。`prepare_measured_figures.py` 从聚合 CSV 和原始日志 manifest 准备独立 measured 输入，支持只替换已有实测的几个图。物理结果解释、图注和摘要须随证据更新；“填数据即可”指固定图像配置，不意味着理论解释自动变成实测结论。

## 9. 执行顺序和交付判断

正确性/后端校准 → F1同ID主结果 → F2/F3解构与collateral → H1健康开销 → A0/A1/A5/A8/A9/A10关键消融 → 连续T2 trace重放 → 容量/压力/预测/扩展性。

当前负结果已经形成两个明确研究问题：**静态workflow优先级会增加queue尾部；rent当前例子没有减少revaluation且总成本更高。** 后续必须用正确的共享资源价值和在线cost/benefit实验解决，或缩小/简化设计。不能通过换成有利曲线来“证明”系统，也不能因论文写完整就推断高接收率。
