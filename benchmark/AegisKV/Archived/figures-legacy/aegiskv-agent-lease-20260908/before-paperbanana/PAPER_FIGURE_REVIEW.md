# 当前算法的逐图审查与证据范围

[论文叙述](Paper_Figures.md) · [历史审查](PAPER_FIGURE_REVIEW_PrefixAdmission_20260908.md)

本版重新执行新 Algorithm 2/3，旧算法数值不复用。统计图沿用三系统颜色、线型和固定 Workflow 映射；示意图使用具体共享块、数值账本、显存比例与同一对象的提交状态。所有输出按 7 / 3.33 inch 绘制，独立 PDF 可直接被 LaTeX 组合。实际字体、来源哈希、账本与最终导出的核对结果见 [本轮核对记录](../../../output/agent-lease-20260908/DELIVERY_AUDIT.json)。

| 图 | 证据类型 | 本次核对的核心问题 | 去向 |
|---|---|---|---|
| [M1 并行分支留下多少时间差](Paper_Figures.md#paper-motivation-branch-gap) | 观测动机 | 124 个具有重叠分支的观测 Workflow，每个对象取最大分支持续时间差；对数秒轴。它说明分支存在不均衡，还不能直接作为可消费的因果 Slack。 | 正文候选 |
| [M2 长上下文副本的容量代价](Paper_Figures.md#paper-motivation-kv-capacity) | 解析计算 | 按 Qwen3-8B BF16 的 147,456 B/token 计算，96 Ki tokens 的一份 / 两份 KV 为 13.5 / 27 GiB。参考线仅扣模型权重和 2 GiB runtime，尚未扣动态前台 KV，不能视为 Peer 配额。 | 正文候选 |
| [S1 数据路径与三个算法的职责](Paper_Figures.md#paper-system-overview) | 设计示意 | 同一 Source 分别向 Peer HBM 和 Store DRAM 复制；实线为数据，虚线为控制。Algorithm 2 管理物理块上的 Agent 子租约，Algorithm 3 独立限制目标 GPU 允许借给备份的显存。 | 正文候选 |
| [S2 按联合 Workflow 收益分账](Paper_Figures.md#paper-design-joint-wct) | 设计示意 | 同一 DAG 的两条分支共享一个物理块；按固定 Agent 顺序逐个加入恢复改善，WCT 为 12→12→10 ms，分账为 0+2 ms。单个分支的重算下降不等于整个 Workflow 等额缩短。数值为可核算示意。 | 正文候选 |
| [S3 信用跨请求保留，按 Agent 新轮更新](Paper_Figures.md#paper-design-agent-subleases) | 设计示意 | 共享尾块 X 上 A/B 信用为 6/4，竞争尾块 Y 为 2；按物理容量收租后 X 为 4.8/3.2，Y 淘汰。仅 A 进入新轮时 X 变为 6/3.2；同轮命中不能补回已花信用。内部块 R 不参加尾块收租。 | 正文候选 |
| [A1 单块试算、释放与提交](Old_Figures.md#agent-lease-supplements) | 设计示意 | 每个状态都只画一个共享 R；只从可释放尾块 Q 选牺牲者。空闲门为 G≥0，替换门为 G>D。版本核验后应用试算，free 完成后分配，复制 ACK 后才可恢复；失败不复活已释放的旧块。 | 补充 |
| [S4 独立的显存借用上限控制](Paper_Figures.md#paper-design-guarded-aimd) | 设计示意 | 40 GiB 示意布局明确区分前台、保留量、备份和 FREE。C 是硬上限，Q 是允许借用的额度，均不是实际占用；增长、预警减半和容量裁剪单独展示。实现使用 50 ms 窗口、连续 4 个稳定窗口、每次增 1 GiB、β=0.5。 | 正文候选 |
| [S5 独立提交决定故障后能恢复的前缀](Paper_Figures.md#paper-commit-tier-timeline) | 设计示意 | 同一 C1 的 Peer ACK 已到、DRAM 尚 pending 时 Source 故障，两个 tier 因而留下不同前缀。恢复仍须装入新 primary 并重算缺失后缀；图中间距仅表示逻辑次序。 | 正文候选 |
| [E1 输入的 Prompt 长度分布](Paper_Figures.md#paper-workload-prompt_tokens) | 输入统计 | 冻结输入的 1,304 个原始请求；Ki=1,024 tokens。两轮扩展不作为新原始样本。总上下文最大 86,214 tokens，不能据此声称覆盖 128K。 | 正文候选 |
| [E2 输入的 Workflow 规模](Paper_Figures.md#paper-workload-workflow_call_counts) | 输入统计 | 160 个原始 Workflow 的调用数分布，最大为 27。样本单位是 Workflow；不是 160 次完整系统运行。 | 正文候选 |
| [E3 同配置逐 Workflow 的 WCT](Paper_Figures.md#paper-f0-revisit-wct) | 未标定机制模拟 | 每点是同一个 Workflow；从首次 release 至最后请求完成，不含活跃 slot 外的入场等待。三系统只按 Mooncake 的同一序列对齐，保留全部尖峰。 | 正文候选 |
| [E4 逐 Workflow 的完成时间变化](Paper_Figures.md#paper-f0-revisit-wct-difference) | 未标定机制模拟 | 各系统 WCT 减同一 Workflow 的 Mooncake WCT；零线为 Mooncake，正值更慢、负值更快。与上一图使用同一 ID 映射，不按差值重新排序。 | 正文候选 |
| [A2 单一入场顺序的 WCT 分布](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | seed 0 的完整 160 对象经验分布；主文使用三种入场顺序的分布包络补充稳健性，本图保留为单配置核对。 | 补充 |
| [E5 DRAM 准入是否保住正常复用](Paper_Figures.md#paper-f0-revisit-dram-hit) | 未标定机制模拟 | 正常服务实际复用的 DRAM token / 全部 prompt token，包含冷访问和精确重访；恢复 token 不计入。它是 token 命中率，不是请求命中比例。 | 正文候选 |
| [E6 实际复用来自哪一层](Paper_Figures.md#paper-f0-revisit-cache-sources) | 未标定机制模拟 | 将全部 prompt token 互斥分解为 Local HBM、Store DRAM、Peer HBM 和重新计算，合计 100%。Peer 备份写入量不会被计为正常服务的命中收益。 | 正文候选 |
| [E7 正常请求的 GPU 调度排队](Paper_Figures.md#paper-f0-revisit-scheduler-queue) | 未标定机制模拟 | 每个 Workflow 内请求的平均 GPU-ready→运行等待。GET、CPU 和等待分配 HBM 分开计量，不能把它们都写成 scheduler queue。 | 正文候选 |
| [E8 前台因 HBM 准入而等待多久](Paper_Figures.md#paper-f0-revisit-hbm-wait) | 未标定机制模拟 | 每个 Workflow 内请求的平均前台 HBM 等待；Peer 是否增加排队，需要同时看显存余量、动态消融和原生干扰微基准，不能仅凭跨系统的一个均值归因。 | 正文候选 |
| [E9 GPU 的低空闲显存时间占比](Paper_Figures.md#paper-f0-revisit-hbm-pressure) | 未标定机制模拟 | 按每张 GPU 的时长加权，统计 FREE 低于 1 GiB 的执行时间比例；保持真实 GPU 编号和同一阈值。包含可回收的普通缓存，低余量不等于 OOM、HBM 带宽饱和或服务违约。 | 正文候选 |
| [E10 请求 TTFT 的完整分布](Paper_Figures.md#paper-f0-revisit-ttft-cdf) | 未标定机制模拟 | 所有 2,608 个请求从 release 到第一个输出 token 的经验分布；与只量 GPU prefill 的耗时不同，包含执行路径上的等待。 | 正文候选 |
| [E11 请求平均 TPOT 的尾部](Paper_Figures.md#paper-f0-revisit-tpot-tail) | 未标定机制模拟 | 每系统 2,432 个分母有效的请求先计算首 token 后的平均 TPOT，再绘制包含等号的经验生存比例；保留完整尾部。它不是逐 token ITL 分布，也不是跨运行置信区间。 | 正文候选 |
| [A3 逐 Workflow 的 CPU 服务报价变化](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 对准入和前台派发的固定 CPU 服务报价按 Workflow 归因，再减 Mooncake；全局控制 CPU 单独计量。这条曲线不是每个 Workflow 的实测 CPU 利用率。 | 补充 |
| [E13 进入模拟时序的控制 CPU 服务](Paper_Figures.md#paper-f0-revisit-controller-breakdown) | 未标定机制模拟 | 固定服务报价的总和，分为前台派发和准入；经过同一个控制器队列。提交、回收和 AIMD 的全部 CPU 工作量还没有完整转成因果延迟。 | 正文候选 |
| [E12 Python 参考实现的实际 CPU 工作量](Paper_Figures.md#paper-reference-cpu-breakdown) | Python 参考 CPU 实测 | 按线程 CPU 时间分解前台派发、准入与 DAG、提交、回收与 AIMD，扣除嵌套计量避免重复。它是本参考实现的组件工作量，未覆盖原生服务的全部 CPU。 | 正文候选 |
| [E14 实际传输量的组成](Paper_Figures.md#paper-f0-revisit-traffic-breakdown) | 未标定机制模拟 | 累计模拟内传输的字节，分为正常 GET、DRAM 写入和 Peer 复制，纵轴 TiB。更多副本写入与较少正常命中可能同时发生，不能仅比较总字节得出带宽无争用。 | 正文候选 |
| [E15 保护流量是否拖慢前台 GET](Paper_Figures.md#paper-f0-revisit-transfer-service_slowdown) | 未标定机制模拟 | 每个成功正常 GET 的实际传输服务时长 / 同字节量独占链路时长；横轴倍率。不同系统的命中对象和 GET 数量会变，CDF 是描述性分布。 | 正文候选 |
| [A4 逐 Workflow 的后台复制量](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | DRAM 与 Peer 实际后台传输之和，按源 Workflow 归因；与固定 Workflow 顺序的 WCT 图配套诊断。 | 补充 |
| [A5 逐 Workflow 的 Peer 复制量](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 只统计实际 Peer 传输，不用 AegisKV 总流量减 DRAM-only 来估算。Mooncake 与 DRAM-only 为重合零线。 | 补充 |
| [A6 25% 进度选点的逐 Workflow 故障代价](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 三系统各用本系统 F1 减配对 F0；均为同一 2,608 请求输入。选点依据 Mooncake F0 的 25% 完成进度附近第一轮长请求，在其 prefill 60% 触发单 GPU 故障。包含已完成对象的零值与调度重排产生的负值。 三个故障位置使用同一纵轴范围。 | 补充 |
| [E16 50% 进度选点的逐 Workflow 故障代价](Paper_Figures.md#paper-f1-q50-workflow-penalty) | 未标定机制模拟 | 三系统各用本系统 F1 减配对 F0；均为同一 2,608 请求输入。选点依据 Mooncake F0 的 50% 完成进度附近第一轮长请求，在其 prefill 60% 触发单 GPU 故障。包含已完成对象的零值与调度重排产生的负值。 三个故障位置使用同一纵轴范围。 | 正文候选 |
| [A7 75% 进度选点的逐 Workflow 故障代价](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 三系统各用本系统 F1 减配对 F0；均为同一 2,608 请求输入。选点依据 Mooncake F0 的 75% 完成进度附近第一轮长请求，在其 prefill 60% 触发单 GPU 故障。包含已完成对象的零值与调度重排产生的负值。 三个故障位置使用同一纵轴范围。 | 补充 |
| [E18 不同故障位置的尾部 Workflow 损失](Paper_Figures.md#paper-failure-progress-p95-penalty) | 未标定机制模拟 | 每个预定故障位置，对全部 160 个配对 Workflow 的 F1−F0 求 P95。三个位置是不同干预，不是同条件三次独立重复；实际参考进度另表给出。 | 正文候选 |
| [E17 保护缩短的是哪个恢复阶段](Paper_Figures.md#paper-failure-focal-recovery-phases) | 未标定机制模拟 | 每根柱追踪同一个预定焦点请求：从故障到前缀装入，再到后缀计算与解码恢复；Peer/DRAM 恢复 token 和重算 token 另存 CSV。只缩短前缀装入不等于总恢复获益。 | 正文候选 |
| [E31 何种故障概率下才能抵消正常开销](Paper_Figures.md#paper-benefit-cost-fault-mixture) | 模拟结果的解析混合 | 解析混合 E[WCT]=(1−p)·F0+p·平均 F1，假定一次完整执行至多一个故障，三个预定位置等权。p 是分析参数，不能解释成观测故障率、MTBF 或多次故障结果。 | 正文候选 |
| [E19 更换入场顺序后的正常 WCT](Paper_Figures.md#paper-order-normal-wct) | 未标定机制模拟 | 三种预定入场顺序包含相同 160 个 Workflow；每个经验分位的线为中位数、阴影为三个顺序的最小/最大值，不是置信区间，也没有合并成 480 个独立样本。无故障、资源和两轮输入均相同。 | 正文候选 |
| [E20 更换入场顺序后的故障代价](Paper_Figures.md#paper-order-failure-penalty) | 未标定机制模拟 | 三种预定入场顺序包含相同 160 个 Workflow；每个经验分位的线为中位数、阴影为三个顺序的最小/最大值，不是置信区间，也没有合并成 480 个独立样本。每个顺序各自从 Mooncake F0 选择中期故障，再减本系统对应 F0。 | 正文候选 |
| [E23 真实 forward 与 DMA 并发：batch 1](Paper_Figures.md#paper-native-forward-b1) | 真实 GPU 组件微基准 | batch=1，额外触达分配 8 GiB；prompt 为 512/2,048/4,096 tokens。每个测量块内用相同 prompt 的无复制 forward 归一化；Peer 输入、输出和 DRAM 写入分开测。 每条件含同一次 GPU 分配中的 5 个随机交错测量块；标记和误差线为中位数与最小/最大值，不是置信区间。 | 正文候选 |
| [E24 真实 forward 与 DMA 并发：batch 4](Paper_Figures.md#paper-native-forward-b4) | 真实 GPU 组件微基准 | batch=4，额外触达分配 8 GiB；prompt 为 512/2,048/4,096 tokens。每个测量块内用相同 prompt 的无复制 forward 归一化；Peer 输入、输出和 DRAM 写入分开测。 每条件含同一次 GPU 分配中的 5 个随机交错测量块；标记和误差线为中位数与最小/最大值，不是置信区间。 | 正文候选 |
| [E25 分配容量与复制争用分别测量](Paper_Figures.md#paper-native-memory-occupancy) | 真实 GPU 组件微基准 | batch=4、prompt=4,096，额外触达分配 0/8/16 GiB；比较四种 DMA 条件的真实 forward 时长。纵轴放大局部变化，零 OOM 只适用于这批条件。 每条件含同一次 GPU 分配中的 5 个随机交错测量块；标记和误差线为中位数与最小/最大值，不是置信区间。 | 正文候选 |
| [A8 真实复制速率随前台计算变化](Old_Figures.md#agent-lease-supplements) | 真实 GPU 组件微基准 | batch=1、额外占用 8 GiB，按每个块的实际复制字节 / 复制完成时间聚合；256 MiB 缓冲反复复制。这里的并发有效速率不是链路标称容量。 每条件含同一次 GPU 分配中的 5 个随机交错测量块；标记和误差线为中位数与最小/最大值，不是置信区间。 | 补充 |
| [E26 撤销备份后的实际释放延迟](Paper_Figures.md#paper-native-release-ack) | 真实 GPU 组件微基准 | 1/4/8 GiB 分配各 20 次：等待异步写入 fence 与 allocator free+empty_cache+同步分开测。两部分都是实测完成时间，不能直接替代原生服务的回收延迟。 标记和误差线为 20 次测量的中位数与最小/最大值。 | 正文候选 |
| [A9 原生复制线程的 CPU 需求](Old_Figures.md#agent-lease-supplements) | 真实 GPU 组件微基准 | batch=1、额外占用 8 GiB，测量整个 forward 窗口的进程 CPU / 墙钟时间，以核数表示；包含本微基准的复制线程与 CUDA 同步等待。它不等价于原生 AegisKV 准入 CPU 或整台服务器利用率。 每条件含同一次 GPU 分配中的 5 个随机交错测量块；标记和误差线为中位数与最小/最大值，不是置信区间。 | 补充 |
| [E21 Algorithm 2 / 3 的正常服务消融](Paper_Figures.md#paper-ablation-normal-wct) | 未标定机制模拟 | 分别去掉 DAG 联合价值、将空闲门改为严格 G>0、或将动态 Peer 改为静态容量上限。相同输入与 CPU 报价，每次只改一个因素；减少保护可能降低正常开销，也可能损失恢复覆盖。 | 正文候选 |
| [E22 惰性计算是否保持同样的准入决策](Paper_Figures.md#paper-ablation-lazy-refresh) | 未标定机制模拟 | DRAM-only 上比较 Lazy / Eager：两者都检查全部可释放尾块，只允许跳过版本未变的价值计算。比较每次接纳/拒绝与牺牲块序列必须完全相同；计数包含被拒绝的试算。 | 正文候选 |
| [E27 AIMD 授权与实际副本占用](Paper_Figures.md#paper-aimd-quota-and-occupancy) | 未标定机制模拟 | 在 30% DMA 额外 forward 时长的敏感性条件下，按 50 ms 窗口汇总 8 张 GPU 的 C、Q 和实际副本。物理占用含 pending；模拟器在 fence 后同步 free，真实释放时长另图测量。 | 正文候选 |
| [E28 预警反馈是否随控制变化](Paper_Figures.md#paper-aimd-warning-windows) | 未标定机制模拟 | 同一 30% 争用假设下，比较 Guarded AIMD 和只保留显存上限的 Static Peer；1 s 桶内统计产生归一化 forward 预警的目标窗口比例。预警不是请求 SLO 违约率。 | 正文候选 |
| [A10 强争用下动态控制的 WCT 影响](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 相同 30% DMA 假设，比较 DRAM-only、Guarded AIMD 和 Static Peer；静态版本仍尊重显存硬上限。容量守恒与前台时延保护是两个不同问题。 | 补充 |
| [E29 共享路径带宽敏感性](Paper_Figures.md#paper-sensitivity-bandwidth) | 未标定机制模拟 | 实际执行 5/25/50 GB/s，其余保持默认；每个点是该配置的整批汇总，三系统配对。连线只连接已测设置，不能外推为连续函数。CPU/DMA 系数是模型参数。 | 正文候选 |
| [E30 DRAM 容量与正常命中](Paper_Figures.md#paper-sensitivity-dram-capacity) | 未标定机制模拟 | 实际执行 250 GB / 1 TB，其余保持默认；每个点是该配置的整批汇总，三系统配对。连线只连接已测设置，不能外推为连续函数。CPU/DMA 系数是模型参数。 | 正文候选 |
| [A11 活跃 Workflow 并发敏感性](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 实际执行 16/32 个活跃 Workflow，其余保持默认；每个点是该配置的整批汇总，三系统配对。连线只连接已测设置，不能外推为连续函数。CPU/DMA 系数是模型参数。 | 补充 |
| [A12 CPU 服务报价的敏感性](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 实际执行 1×/2× 固定 CPU 报价，其余保持默认；每个点是该配置的整批汇总，三系统配对。连线只连接已测设置，不能外推为连续函数。CPU/DMA 系数是模型参数。 | 补充 |
| [A13 硬件 DMA 争用系数的敏感性](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 实际执行 0/5/30% 额外 forward 时长，其余保持默认；每个点是该配置的整批汇总，三系统配对。连线只连接已测设置，不能外推为连续函数。CPU/DMA 系数是模型参数。 | 补充 |

## 验证与剩余范围

52 项针对性回归覆盖 Agent 分支/轮号、同轮信用、Q 尾块刷新、拒绝回滚、复制提交、AIMD 与连续推理调度。实验源码先冻结，再执行矩阵；运行正确性不等于实际硬件性能得到验证。

原生组件新增 360 个 forward 样本与按对象大小各 20 次释放测量。尚缺原生三系统端到端服务、在线预测器校准、多工作负载及多故障泛化。相关限制已进入主文图注，不能将形式正确或审查 PASS 写成系统收益已获证明。

设计语言沿用 [Best Paper 实际图页审查](../docs/paper/BEST_PAPER_FIGURE_REVIEW.md) 的具体对象、状态对比和相邻证据组织；未复制参考论文的图像或数据。
