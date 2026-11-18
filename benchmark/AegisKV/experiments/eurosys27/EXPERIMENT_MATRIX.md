# AegisKV Evaluation：研究问题与分阶段实验矩阵

版本：2026-09-23。本文与 `PROTOCOL.md`、`campaign-plan.json` 共同定义**计划实验**，不是运行完成报告。依据是当前 `paper/system_design.tex` 的 fixed L/K/Z、互斥三层 owner、无租金 Peer、lower-tier lazy credit 与 guarded AIMD。旧版 no-Peer、完整下层复制、全局整方案搜索、Peer 租金的规格不再是主策略。

当前未验证一个实现上述完整语义的 serving runner。历史 GlobalDES/静态脚本、toy rental、analytical pipeline、真实 trace 描述以及路径微基准，均不得直接改名为当前控制器实测。硬件、精确模型 revision、可执行 workload cohort 和校准值尚待冻结；计划中的 `null` 是未落实项。本文不启动物理实验。

## 1. 写作主线与文献依据

Evaluation 按“公平比较 → 端到端效果 → 因果机制 → 正常开销 → 边界/正确性”展开。文献核对与具体章节/图号见 `EVALUATION_LITERATURE_20260923.md`：LUMEN 提供 interrupted/uninterrupted 与故障恢复分解的范式；HCache 展示 bandwidth/history 与 compute/I/O balance；Mooncake 强调 TTFT/TBT SLO goodput 及 locality 与实际命中的分离；TOPAS/Parrot 提供 workflow completion、依赖 workload 与多租户比较。借鉴的是实验问题和公平控制，不复制其硬件、收益或未运行过的系统标签。

当前可用证据图与未来主结果图分开登记。正文不必为每项扫描放图；补充材料保留所有 cells、原始数据和负例。以下 8 个 RQ 是实验组织，不是 8 张图的固定配额。

| RQ | 核心问题 | 最小决定性结果 | 扩展扫描 | 建议结果图与判定 |
|---|---|---|---|---|
| RQ1 | 相同物理资源下，故障后 WCT 是否改善？ | 3 families × 2 models；H-LRU、Reuse、AegisKV、Recompute；60% load；同 ID 80% common-worker fault；每策略自己的 F0 | 30/85% load、其他故障进度、支持的 TP/长上下文 | family 分面配对差与 95% CI，absolute F0/F1 WCT、完成率伴表；只胜 Recompute 不足以证明策略贡献 |
| RQ2 | Peer 与恢复调度为何改变 WCT，是否损害旁观者？ | 固定 checkpoint/native demand 的 Peer×pipeline 四格；共享/隔离资源与 Router 四格；直接、共享未失败、隔离 cohort | burst 1/2/4/8、targets 1/2/4；读/NIC/H2D 瓶颈；同 ID phase | recovery critical path + cohort penalty/queue；暴露等待减少而整体尾部变差仍是负例 |
| RQ3 | 有限容量、带宽和负载下，优势在哪里消失？ | 先完成 RQ1 的受压容量点；边界 cells 逐个扫，不全笛卡尔 | Peer 0/5/10/20%；DRAM 0/.1/.25/.5/1；storage .5/1/2；load .3/.6/.85；backend/rate | absolute WCT penalty 与实际 GiB/achieved GiB/s 曲线，completion companion；all-fit 应收敛，零容量不得隐含免费后备 |
| RQ4 | Slack、normal reuse、共享份额与 fixed Peer slots 各有何贡献？ | 无 Slack/无共享/两者都无；无 reuse/无 fault；fixed-slot FCFS/recency/Slack 的相同配额比较 | recovery-benefit 排序、frozen placement、exclusive vs duplicate backing、adaptive L/K、small oracle | 同 campaign 消融差值与四格 interaction；不把高 Credit 当 Peer 资格，不宣称 fixed L/K 最优 |
| RQ5 | 下层 Credit/lazy 是否在同工作预算下值得？ | AegisKV/direct × lazy/eager 四格；no-renew/no-aging；CPU 与 WCT 同时报告 | ordinary GDS/Landlord、unlimited eager、no rotating scan、candidate breadth、paid-rent diagnostic | WCT–CPU 散点/Pareto 和 migration/scan-age；396 scalar checks 不是新实现的 CPU 证据 |
| RQ6 | 时间/访问预测与固定 L/K/Z 能否迁移？ | workflow-disjoint train/calibration/test；真实 residual-segment error；normalized vs raw sparse history；固定值测试前冻结 | ±10/25/50/100% error、shift、missing edges、cold starts、L/K/Z 和 M/N sensitivity | signed error/false-slack 与 native future-demand coverage；把错误传播到 WCT，历史相关性不代替准确率 |
| RQ7 | 健康服务和真实故障频率下净收益如何？ | RQ1 全部 F0，加低/高负载 F0；一次原始 DAG、完整分母；同 arrival/SLO | 连续 outage trace、original/even/group-shuffled/accelerated timing、故障稀有度与成本摊销 | WCT/TTFT/ITL/SLO-goodput 曲线；calendar-block paired difference 与 break-even；零故障窗口保留 |
| RQ8 | 所有权迁移是否安全，控制开销是否可承受？ | 正确性先行；16 类交错；Peer/DRAM shrink + full-storage + leases；CPU、队列和真实 free bytes | DP2/4/8、DAG10/100/1000、groups1e2/1e3/1e4、q16/64/256、多故障域 | occupancy/target timeline + p50/p95/p99 controller latency；安全失败阻止对应性能结论 |

## 2. 比较对象与共同预算

| ID | 可运行定义（待实现/核对） | 在论证中的角色 |
|---|---|---|
| H-LRU | 同一 engine、checkpoint/manifest/lease、有限三层容量与 tuned pipeline；从 active requests 按 recency 分配相同 Peer slot，LRU 管理下层；相同 Adapter 压力规则与 load/locality Router，deferred demand 取自己的资格队列 | 主要强 baseline。Peer/工作显存、safe migration、router 都不能免费省略 |
| Reuse | 相同三层执行；仅 normal next-use saved work/byte，无 fault/Slack term；Peer 从 active requests 按 reuse 排序，配额与安全相同 | 区分普通缓存收益和 recovery 贡献；须在 disjoint validation 调参 |
| AegisKV | 当前设计：零 guarded Slack Peer 候选、固定 L/K/Z、normalized native access、per-Agent lower-tier credit/lazy、AIMD | 被评估系统；尚未验证完整 runner |
| Recompute | 同 engine 与 ordinary local prefix cache；无新增 fault-safe KV checkpoint；持久 input/accepted-token log | 重建代价控制。其 unused protection resources 可供正常服务；不是 equal-recovery-coverage 策略基线 |
| All-DRAM | 让 checkpoint fit DRAM；Peer disabled；相同恢复调度 | 容量放宽参考，不能算等资源胜负；仍有 detection/replay/queue，不是绝对零延迟下界 |
| Small oracle | 2–8 groups 的可行穷举；真实剩余时间/需求；相同 bytes/dependencies/migration constraints | 小实例决策 regret；离线结果，不充作 deployable baseline |

外部系统按兼容性选择**至少一个最相关且可复现的 artifact**作为扩展对照，或明确说明不可运行原因；不要求全部实现。优先核对 LUMEN 的 load-aware recovery、DéjàVu replication、GhostServe parity 中与实际部署兼容者；RaidServe 只在其 TP/异构故障场景合理时加入。TOPAS/KVFlow 比较 workflow/cache policy 时接相同 fault-safe backing。不能把自行实现的一条策略曲线命名为完整系统；写清 `...-style (reimplementation)`。所有冗余/parity、编码、staging、metadata、迁移和工作空间都计费。

公共中心 cell：DP2/TP1 **规划**，host/failure isolation 待核验；自然 supported 32K workload bucket；Peer cap=可管理 HBM pool 的 10%；DRAM=冻结 unique checkpoint working-set 的 25%；storage=100%；load=H-LRU 健康可持续吞吐的 60%；具体 GiB、SLO、L/K/Z、block size 与 rate 由独立 pilot/calibration 冻结。0/5/10/20% 等为实验点，不是产品默认参数。分母 working-set 由同一冻结 workload census 得出，不能按各策略命中率重新定义。

## 3. 最小 suite、扩展 suite 与计算预算

`campaign-plan.json` 显式列出 model/workload/policy/scenario/conditions/repeats，每 cell 都是 `planned`，无 fabricated run IDs。`run_slots` 是计划的独立进程运行次数，不是已经取得的重复数，也不是 GPU-hours。一个 paired campaign 包含比较所需 policies 和它们各自的 F0/F1；不能把这些 run slots 都称独立 campaigns。

- **P0 readiness/pilot**：核验实现语义、模型原生路径、workload 可执行性、fault-domain 与协议正确性，校准 serving SLO/传输；小型一 family、一 model、4 policies、F0/F1、10 campaigns 为 **80 slots**，是主矩阵的子集，不另加 80。失败或 unsupported cell 公开记录。
- **P1 minimum decisive suite**：主比较 3 families × 2 models × 4 policies × 2 conditions × 10 campaigns = **480 slots**。另列 mechanism、Peer、Router、healthy、pressure cells，不把它们与主比较偷偷乘成全笛卡尔。RQ1 的 480 本身不证明所有机制或跨拓扑泛化；完整最小计划为 **68 cells / 15 comparison blocks / 150 paired campaigns / 1,200 run slots**：主结果 480、机制 320、Peer 四格 80、Router 四格 80、低/高负载 F0 160、两种动态压力 80。
- **P2 extended suite**：在 W3/M-S 中心点做独立单因素 resource/phase 扫描；必要时在 W1/W2 复现转折点。显式扩展共 **40 cells / 16 blocks / 800 run slots**；完整外部系统、连续 trace、扩展 TP/DP/model/context 为尚未落实的条件扩展，不在 800 内。先 pilot 测每 run 耗时，再冻结 GPU-hours。
- **非 serving 作业**：16×100 seeded interleavings、workflow-disjoint prediction、native trace、small-instance oracle 和 controller scale。它们单独计数，不能充实 serving campaign 的 n。

最小机制 cells 用统一 constructed workload family 以固定 causal changes；统计含 matched workflow/Agent IDs。同一场景同一 policy 的 F0 可以在预声明的 pairing block 内复用，JSON 保守地为每个 matched block 独立计划 F0；分析不得把复用的物理 run 计算为新独立重复。

## 4. 端到端与因果控制（RQ1–RQ3）

主故障：预声明 anchor workflow/Agent/segment/request 的 **80% frozen total-token logical progress**，杀掉该 source replica 的全部共置 requests。其他 policies 路由到不同 source 时仍按 anchor 触发；用固定原始 arrival cohort 做 intent-to-treat，另报实际 interrupted 子组。无法达到锚点的配置保留 timeout/unreached，不能另选方便的 request。单请求取消仅是诊断，不冒充共同 worker failure。

两类运行不可混用：**full-system** 允许实际路由、committed frontier、queues、迁移与 hit 差异，全部计费；**attribution** 固定 pre-fault state、commit frontier、frozen native demand、source co-location 和 scheduler/workspace，只改变预声明因素。Attribution 中 exclusive Peer on/off 在三层间搬同一 unique KV，保持总体覆盖；因为位置是处理因素，各 tier occupancy 可变，但不得超相同物理上限。Duplicate-backing 对照是另一个等总物理预算实验，不能声称相同 unique coverage 自然成立。

恢复事件链记录 failure→detection/fencing→target admission→storage/NIC/H2D→required replay→first unacknowledged token→branch→join→WCT。只累加真实关键路径的不重叠区间；read、copy、compute busy time 各自另报。避免把 avoided historical prefill 算作可用于 overlap 的 computation。Native sparse 不改 selector/budget；selection miss 实际读取 owner，mandatory state 不按稀疏热度省略。

同时报告直接故障、共享 reader/NIC/target 未失败、隔离未失败三个 cohort。只有存在共享资源拓扑和对应队列证据才解释跨 workflow 传播。保持负差、完整尾部、backlog recovery time、discard/timeout/completion。All-fit、Peer=0 与 no-slack 都是重要边界，不要求它们有正收益。

## 5. 完整机制与交互（RQ4–RQ6）

| 变体 | 唯一变化 | 固定项/观测 |
|---|---|---|
| no-slack / zero-slack fallback | 所有 urgency 使用 zero guarded Slack | normal reuse 保留；相同预算与参数，报告 Peer membership 与 WCT |
| no-reuse / no-fault | 分别去 normal-reuse term / failure term | lookup 和安全协议保留；F0/F1 双报 |
| no-shared-shares | 多 Agent 兴趣改为单一 owner-Agent share | 物理 bytes/refs 仍去重计费，不能故意重复占用显存制造收益 |
| frozen placement | 起始 placement 固定，跳过可选在线换位 | 必须容量 relief 与安全迁移仍运行；记录限制 |
| direct revaluation | 下层用相同 g/byte 与 inspected candidates 当前值；无 cumulative rent/renewal | 与当前 priority model 相同，不恢复旧 complete-plan global search；记录 plan feasibility 与 CPU |
| ordinary GDS/Landlord | 静态单对象 cost/size + pressure aging | 共用 safety/candidate budget；不导入经典竞争保证 |
| no-renew / no-aging | 去 actual-use refresh / pressure aging | 相同 grants/candidate exposure；分别揭示 reuse 与 stale retention |
| eager-capped / eager-reference | eager refresh 在同 CPU/候选预算下 / 不限 refresh 预算 | 超预算明确截断，不假装所有 block 已更新；unlimited 仅是成本参考 |
| no-rotation | 仅刷新 low-key heap candidates | 测 victim disagreement/rank regret、scan age；不得宣称 heap top 即真最小 |
| raw / recency | normalized selected/visible 换 raw selected count / recency | 同未来 Queries、block ages、cold starts、K/bytes/native path |
| serial | 关闭 restoration pipeline | native demand、coverage、staging bytes、rates 相同 |
| locality-only Router | 去 load-aware target scoring | 同 compatible survivors/faults/affinity rules，Peer rebind 不白得本地副本 |
| Peer FCFS/recency/benefit | 改 request slot 资格/顺序 | 最小参照从全部 active requests 选择，不能称纯排序消融；扩展固定同一候选名单隔离顺序；同 L/K/Z、cap |
| fixed Peer cap / adaptive L/K | 关 AIMD / 改每 request quota | 相同物理总 cap 与工作预算；后者是较贵参考，不叫当前 AegisKV |
| duplicate backing | 保留 Peer 对应下层副本 | 同总物理资源，所有冗余计费；比较故障覆盖与迁移代价 |
| bounded-pair / oracle | 更宽 candidate/victim 或穷举 | 同 grants、物理资源；大实例 unsupported；DAG joint oracle 仅诊断 approximate priority |

必须完整执行的四格（四个角使用相同 campaign/workflow pairing；Y 为同一指标）：

1. **Slack × shared-Agent shares**：00/01/10/11；看共享正常价值是否解释所谓 Slack 收益。
2. **normalized demand × pipeline**：raw vs normalized、serial vs bounded pipeline；区分更准需求与隐藏传输。
3. **credit × lazy**：direct vs renewable-credit、capped eager vs lazy；同工作预算；unlimited eager 独立参考。
4. **load-aware Router × shared-link contention**：locality-only/load-aware 与 isolated/shared bottleneck；healthy mates 匹配资源。
5. **Peer × pipeline**：Peer disabled/enabled 与 serial/pipeline；固定 coverage/native demand 的归因块。它是新增必要四格，不替代前四组。

`interaction = (Y11 - Y10) - (Y01 - Y00)` 在每 campaign 内先算，再给 CI；两个单独 speedup 不能相加替代 interaction。安全协议不作为可关闭的性能消融。

预测训练/校准/测试按完整 workflow 隔离，labels 是 residual **segment** 而非 whole-Agent 总时间；request arrival/fork/join/tool completion 的 features 只取当时可见数据。报告 remaining-time MAE、signed tail、false-positive Slack、critical-path ranking 与 fallback rate；用真实 raw predictions 绘 CDF。GBDT 与 median/history/zero-slack 比较，历史弱特征和负结果继续展示。固定 L/K/Z 在 calibration 上选后冻结，再测试其他 workflows、M/N/load；Z 的 64/256/1024 点需按实际 block 对齐，不能令产品运行时自适应 Z。

## 6. 健康成本、真实 trace 和负证据（RQ7）

F0 每原始 DAG 一次（rounds=1），同 IDs/order，完整 prompt 含首个请求；分别记录 request-hit/token-hit、local HBM/Peer/DRAM/storage。潜在 prefix coverage 不是 runtime hit。healthy 图包含绝对 WCT、TTFT、ITL、SLO-goodput、GPU busy、I/O 和 controller CPU；已有 `healthy-io` 的 ms 是 I/O response，不改名 TTFT。非显著不等于零开销；等效性界限必须预声明。

连续故障扩展保留 source-system 独立日历、down/up、故障簇、重复故障与容量失去/返还；固定 workload→fault-domain mapping 和 arrival stream。没有 down/up 的 trace 不猜 crash/recovery 时间。比较 original timing、同 count/span evenly spaced、保留组大小的时间置乱、10/100/1000 clock compression；后者明确 stress test。calendar blocks/system weighting 与 event weighting 都报，按完整窗口/故障簇 bootstrap。

保留旧证据且限制解释范围：

- LANL 当前镜像 23,739 行 vs 官方说明 23,741，差异未解释；严格 compute 清洗后 21,738 outage intervals、22 systems、3,542 observed nodes，不能用 observed faulty nodes 当 fleet exposure。原 1,648 non-compute、122 零长度、231 重叠/相接合并的 accounting 留在 trace package。
- Reflex/ByteDance revision `89f843a78b1a278e430215cf23800c9fac6e43c0`：98 jobs、344,175 alerts、144 faulty node/job entries，其中 108 无该节点 alert。job-relative 且缺 down/up，只作标签/覆盖描述。
- 旧 trace-driven dedicated FIFO pool 模型未实现 current controller，也不含正常流量、有限 spare/repair/再次故障。原 mean 10.4533→9.4673 s 的同时，p95 37.0375→40.0292 s、p99 204.1208→232.1125 s 变差。同分钟展开只是分辨率敏感性（mean 8.0997/7.0224、p99 163.8936/191.8852 s），不是还原真实毫秒事件。
- 旧 isolated rental 的 total cost 462.96→506.39、两者均 396 scalar comparisons，保留修正/诊断变体；不将它解释为新 lazy controller 的 runtime overhead。
- 已有 whole-Agent predictor MAE 438.6/406.7/407.1 s 及 basic-minus-median CI [-80.9,4.9] s，不验证 residual-segment Slack。所有 analytical/static/observed/physical 标签分开。

摊销使用实测 healthy cost 与条件故障 benefit，说明共同 horizon/单位。若 benefit 随 rare failure probability 消失，报告 break-even 与不适用区间；不拿“从真实 trace 输入”替代端到端实测。

## 7. 正确性、动态压力和扩展（RQ8）

正确性必须覆盖以下 16 类（每类至少 100 个 seeded 随机交错，另对小状态机穷举；case 而非 campaign n）：reservation fail、partial copy、checksum/TP shard/selector missing、commit boundary、redirect boundary、live lease/drain、stale epoch/duplicate callback、accepted-token acknowledgement、full DRAM cascade、full storage/last-copy fallback、Peer shrink/tie、tool-handoff/final short snapshot、sole-owner loss/rebind、duplicate actual use/shared shares、paid-rent roundtrip、fault after committed capacity handoff。

每类按有关变体检查：无 PENDING reads、完整 published manifests、dest confirm→redirect→reader drain→source free、双方临时 bytes 计费、无重复 acknowledged output；tier pressure 已付状态停计/恢复、actual-use 只更新一份、旧 prefix 增长不续租、preview reject 不推进 clocks、已提交 handoff 后失败不回滚历史。Tool side effects 需应用层 idempotency log；不把模型 token replay 等同外部操作 exactly-once。

动态压力：Peer quota cap→半 cap→cap；DRAM 中心预算→2/3→原预算；上下文增长→tool handoff→重复 call→storage backlog→source fault。加反向变化、overlapping leases、full lower pools。记录 target、reserved、committed、retiring、temporary、actually-free，不能以 target 下降即释放。固定、AIMD 和 Recompute/H-LRU 的比较按场景需要；foreground stall、migration bytes、bounded queues 与 WCT 同报。

扩展参数 DP2/4/8、故障域1/2/4，先核对 surviving advertised owners/fallback，unsupported simultaneous losses 不能拆成独立故障。控制器独立测 DAG nodes/edges、live groups、Agent shares、q 与 profiler calls 的 CPU/metadata/scan age，并在等 CPU budget 下回到 WCT；synthetic row count 不代表系统规模。

## 8. 判定、出图与交付

正面主张至少需要：当前语义实现/正确性通过、同预算 H-LRU/Reuse、公平实际 coverage/工作显存、paired WCT/完成率、可接受 F0 代价、共同故障与 collateral 结果。只展示优化后的 analytical 曲线不满足这些条件。

结果由 `DATA_CONTRACT.md` 的逐点表/manifest/raw hashes 驱动。未来主结果的图型合同见 `campaign-plan.json.figure_contracts`；它们是预注册的输出规格，**不是**已注册/已生成结果文件。更改 metric 必须新增对应 visual spec；原有 analytical 数据不填进 planned measured figure。

最终图按真实单栏宽约 3.33465 in 重绘，字体约 10.3 pt、灰度可辨，PDF/SVG/PNG 与可编辑代码同源；检查最终论文实际置入尺寸。图注必须写 evidence、unit/cohort、n、故障触发、预算和 CI 定义。正负、缺失、unsupported、timeouts 均保留。所有完整原始数据/旧图/模型保留在实验包，正文选图不删除实验设计。
