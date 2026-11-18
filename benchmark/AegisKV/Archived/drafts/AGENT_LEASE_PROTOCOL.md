# Agent 子租约与 Guarded AIMD：实验协议（2026-09-08）

本协议对应用户指定的两个算法线程：`01a06fb3-0069-74e1-af0f-ef9bcd39310a`、`01a079a1-f8f8-7813-b500-1d0b0e911710`。Algorithm 2 以 2026-09-08 11:00 UTC 完成的第二、三页决策图为准；旧 CPU reference 中空闲空间也要求严格正收益的分支已经过时。实际源文件哈希见 `output/agent-lease-20260908/ALGORITHM_AUTHORITY.json`。

## 算法绑定

- Algorithm 2：每次处理一个物理 chunk；同一物理前缀在一个 Pool 中只计一次容量。按固定 Agent ID 顺序对联合 DAG WCT 的边际下降分账。恢复终点为已生成 KV；补备份已有块时保留已产生后缀的重算，未知未来输出不进入恢复成本。
- 信用按 Agent 生命周期及请求轮号去重。新请求只改变 Agent 记录；新轮首次参与尾块竞争时更新该 Agent 的信用。同轮刷新取剩余额度与当前价值的较小值，不能补回另一 Agent 已消耗的信用。请求完成不伪造新的 Agent。同名 Agent 的并行执行分支按输入 DAG 的确定性因果链分配独立记录；每条链内请求必须有祖先关系，分支归属不受运行次序或系统策略影响。
- 可释放尾块 Q 全部检查版本后才收租；内部块、被读取块及 pending 复制的必要前缀不参与收租。共享块按物理字节收一次租金，再按扣租前信用占比分摊。
- 空闲空间允许 G≥0；有淘汰时严格要求 G>D。准入试算不改变正式账本。实际释放后才能分配目的地，完整复制确认后才可恢复；后续复制失败不会复活已经释放的旧块。DES 中释放为同步 fencing，不冒充实机 free ACK 延迟。
- Algorithm 3：独立 Guarded AIMD。C=min(策略上限, 现有 FREE+备份占用−前台新增需求−1 GiB 保留量)。普通推理可复用缓存仍属于前台占用。50 ms 窗口、K=4、加性增量 1 GiB、β=0.5；增长必须有需求、有效监测且上一轮调整完成。空闲前台仍有有效监控心跳。缺失/陈旧监控撤销授权的行为有独立测试。进行中 step 超过无竞争参考时长也产生预警。
- 所有系统使用相同的已封存 chunk 复制粒度；复制 ACK 继续排空已生成前缀，不能只等待下一次 GPU step。保护路径与正常 GET 共享既有传输资源与 HBM 账本。

## 三系统与输入

Mooncake 为现有共享前缀、LRU DRAM Store 的模拟适配；DRAM-only AegisKV 使用新 Algorithm 2，关闭 Peer；AegisKV 在同样的 DRAM 策略上启用 Peer 和新 Algorithm 3。三条曲线均不是原生 Mooncake/AegisKV 服务的端到端测量。

冻结 FanOutQA 派生的 160 个 Workflow、1,304 个原始请求。每个 Workflow 将完整 DAG 执行两轮，得到 2,608 个请求；第二轮沿用 Agent ID，并显式标记为受控精确重访。三系统共享 token、DAG、资源、入场顺序和故障身份。默认 Qwen3-8B BF16，DP8/TP1/PP1，8×40 GiB，chunk=4,096 tokens（共享模板可能是更短的完整边界），DRAM=1 TB，共享链路=25 GB/s，同时活跃 Workflow=16。

主排序由 seed 0、无故障 Mooncake 的 Workflow WCT 决定，所有逐 Workflow 图沿用同一个 ID 映射。一个点代表一个 Workflow；重复入场种子改变 Workflow 入场顺序，不增加独立 Workflow 对象。区分配置、完整运行次数和对象数，不对 160 个相互争用资源的对象伪造独立重复置信区间。

## 配对故障与敏感性

无故障 F0 和故障 F1 使用**同一份两轮重访输入**。F1 从对应 Mooncake F0 中选取最接近 25%、50%、75% Workflow 完成进度的第一轮长输入请求（prompt≥16 Ki tokens；避免全缓存重访跳过新计算触发点），在该请求 prefill 60% 处对三个系统分别触发一个逻辑 GPU 故障。事件身份、故障持续 120 s 与进度规则配对；绝对时刻、物理路由和同 GPU 上的其他受影响请求可随执行变化，均保留记录。故障焦点的选择先于失败运行，不根据 AegisKV 收益选点。

默认条件增加 seed 1/2 的 F0 和中期 F1，检验入场顺序的影响；它们不代表多台独立集群。保留所有正、零、负收益及失败状态。配置敏感性包括共享带宽 5/25/50 GB/s、DRAM 250 GB/1 TB、并发 16/32；机制消融检查不考虑 DAG、严格正收益空闲门、eager 刷新、静态 Peer 上限，以及 CPU 报价翻倍。硬件争用敏感性使用预设的 0/5% 额外 forward 时长系数；该系数不由期望论文结论选择。

所有算法性能矩阵从通过回归后的不可变源码快照运行。冻结文件包含两张 Algorithm 2 决策图、Algorithm 3 图、实际 Python 实现、runner、模型与 workload 配置。运行前检查快照内每个文件哈希；保留输入、CPU 报价、参考故障与原始结果的哈希。

## 时序、CPU 与物理测量的边界

GPU 服务仍使用现有 observed-trace prefill:decode=1:8 模型，未标定为 A100 的真实 kernel 时长；不将其改名为训练完成的 GBDT。CPU 收集 Python 参考实现的线程 CPU 时间，包含准入、共享收益计算、复制提交、回收和 AIMD；嵌套计量不重复相加。每个 Workflow 的 CPU 归因与全局控制操作分开统计。

端到端 DES 对准入和前台派发采用独立 16-Workflow 校准运行的固定平均 CPU 服务报价，经过单控制器服务队列。复制提交和其他控制 CPU 的工作量单独报告，尚未完整转换为因果延迟。报价翻倍是敏感性检查，不能当作原生 CPU 上界。计量细节与样本哈希见 `CPU_QUOTES.json`。

补充的物理微基准在 Slurm 独占两张 L40S 上运行真实 Qwen3-8B BF16/SDPA，随机交错 batch、prompt 长度、备份占用量和无 DMA/DRAM PUT/Peer 输入/Peer 输出条件，各条件 5 次块内测量，并记录真实传输完成和 allocator 释放耗时。它回答占用与 DMA 是否干扰真实 forward，不提供原生三系统的 WCT、故障恢复或跨机器置信区间。L40S 微基准与 A100 40 GiB 模拟结果分别绘制，不能混合为同一硬件的性能测量。

## 图像与证据

输出独立 PDF/SVG/PNG、逐图 CSV、配置与来源清单；Markdown 可将共同解释一个问题的独立图并排。既有 PrefixAdmission 图保留在 Old_Figures 中，不能重标为 Agent 子租约实验。新结果按 Motivation、System Design、Evaluation 组织，最终导出按实际单栏或通栏尺寸检查。负结果不因不利于论文而删除。
