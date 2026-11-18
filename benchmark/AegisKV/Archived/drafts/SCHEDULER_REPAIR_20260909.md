# Figure 5 负载纠正与共享调度修复

本文记录共享模拟器修复及其验证，不替代 `Paper_Draft.md` 中的论文叙述。Figure 5 和 Figure 6 使用原始 160 个 Workflow、1,304 个请求，每个 DAG 只执行一次；三系统按相同 Workflow ID 配对。人工第二轮重放只能用于明确标注的缓存机制或代码回归，不能用于这两张图的无故障开销论证。

## 与并行实验的关系

用户指定的两个会话分别处理单轮 Figure 5–7 和按 Agent 80% 进度注入故障的实验。它们使用原始冻结 `output/agent-lease-20260908/source-v3`，源码清单 SHA-256 为 `17c7fd37e74356d2531b15ed1c3659d7f03c874ab00b2fe0794930a8383f5de1`。

本次修复使用独立目录 `output/aegiskv-scheduler-fix-20260909`。其中名为 `source-v3` 的目录是**修复候选第三版**，不是上述原始 `source-v3`；其清单 SHA-256 为 `4023192bbf633179df0504d179de1ad22b635bdbfe885f92ee5e96da4e0494f9`。原始算法 2/3、工作负载、随机种子与 CPU 报价保持不变，修改三系统共享的调度器及前台 connector 交接。不得把修复版 F0 与原始版 F1 配成一对，也不得用本目录的两轮回归替换并行会话的单轮图。

## 修复范围

1. 本地 HBM prefix 命中不再被当作异步 Store GET 完成而进入外部 KV 优先队列。普通抢占请求回到普通 FCFS 队首；真正的异步 GET 等待者保留独立语义。
2. Store GET 在引擎遍历 waiting 队列并检查容量后启动。路由结果只用于选择目标，不再允许刚释放的请求提前占用 GET 目标显存、绕过尚未准入的请求。GET 期间同时持有逻辑页容量和物理目标容量。
3. 普通显存抢占后重新查询当前可用前缀；保留已输出 token，避免重复对外输出。它与故障恢复的 fence、版本和显式恢复优先级分开。
4. 三系统统一启用绑定引擎默认的 `scheduler_reserve_full_isl`：先检查完整已物化输入序列能否装入 KV 空间，再按本步 token 数实际分配。它是容量准入检查，不是一次性分配完整 prompt。

来源为 `reference/source-lock.json` 指定的 1Cat-vLLM `644d8a7cd05ed4ecd1cd188e3c05b4bbd074f504`：`vllm/config/scheduler.py:140`、`vllm/v1/core/sched/scheduler.py:822`、`:954`、`:1163` 与 `vllm/v1/core/kv_cache_manager.py:346`。该绑定引擎包含 Mooncake connector；不能将其静态语义核对称为 Mooncake 原生服务性能验证或完整上游等价。

## 已完成的原始单轮证据

以下结果来自并行会话已发布的原始版本单轮 F0，**不是本次修复后的收益**。数据见 [`output/aegiskv-single-pass-20260909/summary.json`](../../../output/aegiskv-single-pass-20260909/summary.json)。

| 系统 | 平均 WCT（s） | 相对 Mooncake | 抢占次数 | DRAM 命中 token |
|---|---:|---:|---:|---:|
| Mooncake | 39.083474 | 0 | 0 | 0 |
| DRAM-only AegisKV | 39.206431 | +0.3146% | 0 | 0 |
| AegisKV | 39.058733 | −0.0633% | 0 | 0 |

均值仅用于核对这次完整模拟，不能替代逐 Workflow 曲线，也不是独立重复实验的统计结论。单轮没有出现旧两轮实验中的抢占，因此旧的 104.929 s 抢占等待不能用来解释这里的离群点。三系统 DRAM 命中均为零，也无法据此证明 DRAM 准入在有真实共享前缀的负载上不影响复用。

仍存在批次干扰：Workflow `1fb9003757829127` 的最后一个请求在 Mooncake 和 AegisKV 中均为 250 个 prompt token、47 个 output token，命中 64 个本地 token，实际 prefill 186 个 token，且没有抢占。但请求时延分别为 2.013 s 和 30.018 s；GPU step 覆盖时间分别为 0.269 s 和 18.712 s，排队及其余等待分别为 1.743 s 和 11.304 s。同期其他请求的 prefill 工作量分别为 1,291 和 192,182 tokens。可核对 [`final-request-batch-evidence.json`](../../../output/aegiskv-single-pass-20260909/final-request-batch-evidence.json)。这证明实际批次构成及等待存在差异，尚未独立证明其上游变化全部由 CPU、Peer 占用或传输引起。

## 本次验证

最新相关测试为 126 项通过，包括普通队列顺序、抢占后恢复已有前缀、输出一致性、GET 逻辑容量、完整输入准入、三系统真实 GET 生命周期及单轮故障恢复回归。此前扩展回归 218 项通过，另一个新增测试因 fixture 参数拼写失败，修正后已包含于这 126 项通过结果中；不能把此前日志写成一次全部通过。

修复候选第三版的三系统单轮 F0 已全部完成，并逐请求核对输出守恒、原始 DAG 身份及关键路径时间求和：

| 系统 | 平均 WCT（s） | 相对本版 Mooncake | 最大逐 Workflow WCT 增量（s） |
|---|---:|---:|---:|
| Mooncake | 39.289524 | 0 | 0 |
| DRAM-only AegisKV | 39.291100 | +0.0040% | +0.319114 |
| AegisKV | 39.070825 | −0.5566% | +33.864663 |

三系统均没有抢占；每个系统本地命中 81,472 tokens、DRAM 命中 1,472 tokens、实际执行 prefill 26,677,427 tokens，合计等于原始输入 26,760,371 tokens。按执行时刻查询后，少量 DRAM 前缀已可用，因此它与旧版“路由时首次查询”计数不同。三系统各输出 17,936 tokens，没有重复、缺失或旧路由输出。

这组比较同时改变了三系统共享的引擎接入语义；Mooncake 的绝对 WCT 也发生变化。因此，DRAM-only 相对差距缩小不能表述为它的绝对时延下降，亦没有逐个分离四项修复的性能贡献。

AegisKV 的最大变慢对象为 `aa2bb6b28944a416`：WCT 从 28.027672 s 增至 61.892335 s；关键路径 GPU step 时间从 7.105184 s 增至 29.882455 s，排队及其他等待从 20.922488 s 增至 32.009881 s。两者关键路径 ID、输入命中和 prefill 工作量相同，没有 GET 或抢占，不能再将此差异解释为命中下降或抢占重算。

控制 CPU 时间置零的两系统单轮反事实已完成：Mooncake 与 AegisKV 的全部 160 个 Workflow 的 WCT 逐 ID、逐纳秒相同，最大绝对差值为 0，均值均为 39.282796 s。备份与传输仍然启用；累计 PUT 传输量分别为 3,861,063,401,472 和 4,284,114,339,392 bytes。原先 +33.864663 s 的焦点差值也变为 0。数据见 [`CPU_COUNTERFACTUAL_COMPARISON.json`](../../../output/aegiskv-scheduler-fix-20260909/CPU_COUNTERFACTUAL_COMPARISON.json)。

该干预只把 `cpu_scale` 从 1 改为 0，同时去掉前台 dispatch 和保护准入的模拟 CPU 服务时长，其余机制与输入保持相同；副本形成时刻、批次构成等下游状态自然随之变化。结合关键路径分解，可定位到“模拟 CPU 服务延迟 → 请求进入批次的时刻变化 → 混合 prefill/decode 与排队放大”。它说明 CPU 报价是本例差异的触发因素，不单独分离 CPU 与显存/传输的交互贡献，更不是 CPU 免费的物理性能结果。这两次执行只作为诊断，不能放入 Figure 5 的正常开销曲线。

逐对象数据保存于 [`SINGLE_PASS_WORKFLOWS.csv`](../../../output/aegiskv-scheduler-fix-20260909/SINGLE_PASS_WORKFLOWS.csv)，包含 WCT、释放时刻和完成时刻差值，并核对 `Δcompletion = Δrelease + ΔWCT`。固定并发的闭环释放会改变后续请求到达时刻：本次 AegisKV 有 18 个 Workflow 的 WCT 更短但绝对完成时刻更晚。这类情况不能用较短 WCT 宣称整体更早完成。

修复候选第二版的 DRAM-only 两轮压力回归发现一次明确停滞：没有 running 请求，GET 已完成但尚未被计算采用，目标预留占用约 22.48 GiB。该失败保留；候选第三版补入完整输入准入检查后的 `partial-get-regression-v3` 已完成全部 2,608 个请求，没有抢占或停滞，输出 35,872 tokens，守恒检查通过。它不提供论文开销证据。

最终候选的完整验证包括三系统各一次原始单轮 F0、两次单轮 CPU=0 反事实、一次 DRAM-only 两轮代码回归，共六次完整模拟。单轮条件为 160 Workflow、1,304 请求、并发 16、seed 0、无故障，没有独立种子重复；CPU=0 的旧重放对照已取消。所有输出属于未校准 GlobalDES：批次时长仍来自观察轨迹的 token 工作量分摊；Python 参考 CPU 测量与模拟控制器服务报价不能相加或解释为原生 CPU 利用率。当前 `dma_slowdown=0` 还明确省略了未校准的 DMA 对 GPU 计算的减速，不能作为不存在该开销的证据。混合 prefill/decode 的时长、实际传输争抢与完整路由策略仍需要独立校准，不能为使曲线接近零而调整。

审计见 [`DELIVERY_AUDIT.json`](../../../output/aegiskv-scheduler-fix-20260909/DELIVERY_AUDIT.json)。源码补丁、压缩源码/测试包、逐 Workflow CSV 与紧凑数据保存在仓库目录中。受 home 配额限制，完整原始轨迹和冻结副本暂存在 `/tmp/aegiskv-scheduler-fix-20260909`，仓库内提供软链接；长期保留实验前应归档这些原始文件，不能仅依赖临时目录。
