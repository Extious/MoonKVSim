"""Claims and captions bound to Agent subleases / independent Guarded AIMD."""

F0 = ("Uncalibrated discrete-event simulation with 160 paired, two-round workflows "
      "(2608 requests), DP8, 8 x 40 GiB HBM, 1 TB DRAM, a 25 GB/s shared path, and "
      "16 active workflows. ")
ORDER = ("All workflow views use the same order by Mooncake's no-failure WCT; "
         "connecting segments identify adjacent objects, not elapsed time. "
         "Markers every ten objects aid series identification; lines retain all 160 workflows. ")
NATIVE = ("Qwen3-8B BF16/SDPA component measurements on one exclusive two-L40S allocation. "
          "Five randomized measurement blocks per condition; markers and ranges show "
          "the median and observed minimum/maximum, not confidence intervals. ")


def captions():
    rows = []

    def add(name, title, zh, en, *, primary=True):
        rows.append(dict(name=name, title=title, caption_zh=zh, caption_en=en, primary=primary))

    add("motivation-branch-gap", "并行分支留下多少时间差", "124 个具有重叠分支的观测 Workflow，每个对象取最大分支持续时间差；对数秒轴。它说明分支存在不均衡，还不能直接作为可消费的因果 Slack。",
        "Distribution of the maximum overlapping-branch duration gap in each of 124 observed workflows. The horizontal axis is logarithmic. Duration imbalance motivates workflow-aware recovery but is not itself validated causal slack.")
    add("motivation-kv-capacity", "长上下文副本的容量代价", "按 Qwen3-8B BF16 的 147,456 B/token 计算，96 Ki tokens 的一份 / 两份 KV 为 13.5 / 27 GiB。参考线仅扣模型权重和 2 GiB runtime，尚未扣动态前台 KV，不能视为 Peer 配额。",
        "Analytical KV footprint for Qwen3-8B BF16 at 147456 bytes/token (Ki=1024). One and two copies of 96 Ki tokens require 13.5 and 27 GiB. The reference line subtracts model weights and 2 GiB runtime from 40 GiB, before dynamic foreground KV; it is not a lendable backup quota.")
    add("system-overview", "数据路径与三个算法的职责", "同一 Source 分别向 Peer HBM 和 Store DRAM 复制；实线为数据，虚线为控制。Algorithm 2 管理物理块上的 Agent 子租约，Algorithm 3 独立限制目标 GPU 允许借给备份的显存。",
        "AegisKV data and control paths. The source independently copies sealed KV chunks to Peer HBM and Store DRAM. Solid arrows carry data and dashed arrows carry control. Agent subleases attach recovery value to shared physical chunks; an independent Guarded AIMD controller limits backup borrowing on each target GPU.")
    add("design-joint-wct", "按联合 Workflow 收益分账", "同一 DAG 的两条分支共享一个物理块；按固定 Agent 顺序逐个加入恢复改善，WCT 为 12→12→10 ms，分账为 0+2 ms。单个分支的重算下降不等于整个 Workflow 等额缩短。数值为可核算示意。",
        "Illustrative joint-WCT accounting for two branches sharing a chunk. Adding recovery improvements in a fixed Agent order changes workflow completion from 12 to 12 to 10 ms, assigning marginal shares of 0 and 2 ms. The shares telescope to one joint gain; branch-local recovery savings cannot simply be added as workflow savings.")
    add("design-agent-subleases", "信用跨请求保留，按 Agent 新轮更新", "共享尾块 X 上 A/B 信用为 6/4，竞争尾块 Y 为 2；按物理容量收租后 X 为 4.8/3.2，Y 淘汰。仅 A 进入新轮时 X 变为 6/3.2；同轮命中不能补回已花信用。内部块 R 不参加尾块收租。",
        "Illustrative Agent subleases on shared physical chunks. A rent round changes X's A/B balances from 6/4 to 4.8/3.2 while exhausting competing tail Y. Only A's next request round refreshes its balance to 6; B remains at 3.2. Same-round hits do not refill spent credit, and internal prefix R is excluded from tail rent.")
    add("design-prefix-admission", "单块试算、释放与提交", "每个状态都只画一个共享 R；只从可释放尾块 Q 选牺牲者。空闲门为 G≥0，替换门为 G>D。版本核验后应用试算，free 完成后分配，复制 ACK 后才可恢复；失败不复活已释放的旧块。",
        "Single-chunk admission on one shared prefix tree. Eligible tails form Q. Free-space admission permits nonnegative gain, whereas replacement requires gain strictly above joint deletion loss. Trial credits commit only after version validation, allocation follows fenced release, and recovery eligibility follows copy acknowledgement. A failed later copy does not resurrect released victims.", primary=False)
    add("design-guarded-aimd", "独立的显存借用上限控制", "40 GiB 示意布局明确区分前台、保留量、备份和 FREE。C 是硬上限，Q 是允许借用的额度，均不是实际占用；增长、预警减半和容量裁剪单独展示。实现使用 50 ms 窗口、连续 4 个稳定窗口、每次增 1 GiB、β=0.5。",
        "Independent Guarded AIMD over a 40 GiB illustrative memory layout. C is the memory ceiling and Q is granted borrowing permission, distinct from physical copies. The controller grows after four valid stable 50 ms windows with demand and completed adjustment, halves Q on a warning, and clips permission to C. Invalid telemetry revokes permission. Additive growth is 1 GiB.")
    add("commit-tier-timeline", "独立提交决定故障后能恢复的前缀", "同一 C1 的 Peer ACK 已到、DRAM 尚 pending 时 Source 故障，两个 tier 因而留下不同前缀。恢复仍须装入新 primary 并重算缺失后缀；图中间距仅表示逻辑次序。",
        "Independent commits and recovery for the same chunks. C1 is committed on Peer HBM before source failure while its DRAM copy is pending and subsequently aborts. Recovery materializes the available prefix into a new primary and recomputes the missing suffix before decoding resumes. Spacing denotes logical order, not measured duration.")
    add("workload-prompt_tokens", "输入的 Prompt 长度分布", "冻结输入的 1,304 个原始请求；Ki=1,024 tokens。两轮扩展不作为新原始样本。总上下文最大 86,214 tokens，不能据此声称覆盖 128K。",
        "Prompt-length distribution of 1304 original requests in the frozen FanOutQA-derived workload (Ki=1024). Controlled revisit copies are excluded. Maximum total context is 86214 tokens, so this input does not establish coverage of 128K contexts.")
    add("workload-workflow_call_counts", "输入的 Workflow 规模", "160 个原始 Workflow 的调用数分布，最大为 27。样本单位是 Workflow；不是 160 次完整系统运行。",
        "Distribution of original call counts over 160 workflows, with at most 27 calls per workflow. Counts precede the controlled duplication of each complete DAG into two rounds; a sample is one workflow, not an independent system execution.")
    add("f0-revisit-wct", "同配置逐 Workflow 的 WCT", "每点是同一个 Workflow；从首次 release 至最后请求完成，不含活跃 slot 外的入场等待。三系统只按 Mooncake 的同一序列对齐，保留全部尖峰。",
        F0 + "WCT runs from first release to final completion, excluding admission waiting outside active workflow slots. " + ORDER)
    add("f0-revisit-wct-difference", "逐 Workflow 的完成时间变化", "各系统 WCT 减同一 Workflow 的 Mooncake WCT；零线为 Mooncake，正值更慢、负值更快。与上一图使用同一 ID 映射，不按差值重新排序。",
        F0 + "Paired WCT differences from Mooncake. Positive values are slower and negative values faster; Mooncake is the zero reference. " + ORDER)
    add("f0-revisit-wct-cdf", "单一入场顺序的 WCT 分布", "seed 0 的完整 160 对象经验分布；主文使用三种入场顺序的分布包络补充稳健性，本图保留为单配置核对。",
        F0 + "Empirical WCT distributions for all 160 workflows in admission order 0, including full tails. These are within-execution objects, not independent execution replicates.", primary=False)
    add("f0-revisit-dram-hit", "DRAM 准入是否保住正常复用", "正常服务实际复用的 DRAM token / 全部 prompt token，包含冷访问和精确重访；恢复 token 不计入。它是 token 命中率，不是请求命中比例。",
        F0 + "Actually reused DRAM prompt tokens divided by all prompt tokens per workflow, including cold and revisit rounds. Recovery tokens are excluded. " + ORDER)
    add("f0-revisit-cache-sources", "实际复用来自哪一层", "将全部 prompt token 互斥分解为 Local HBM、Store DRAM、Peer HBM 和重新计算，合计 100%。Peer 备份写入量不会被计为正常服务的命中收益。",
        F0 + "Mutually exclusive prompt-token sources: Local HBM, Store DRAM, Peer HBM and recomputation, summing to 100%. Backup writes are not reuse hits. Stacked colors encode sources; system identity is on the horizontal axis.")
    add("f0-revisit-scheduler-queue", "正常请求的 GPU 调度排队", "每个 Workflow 内请求的平均 GPU-ready→运行等待。GET、CPU 和等待分配 HBM 分开计量，不能把它们都写成 scheduler queue。",
        F0 + "Mean GPU-ready-to-execution queue time over requests within each workflow, excluding separately recorded GET, controller and HBM-admission waits. " + ORDER)
    add("f0-revisit-hbm-wait", "前台因 HBM 准入而等待多久", "每个 Workflow 内请求的平均前台 HBM 等待；Peer 是否增加排队，需要同时看显存余量、动态消融和原生干扰微基准，不能仅凭跨系统的一个均值归因。",
        F0 + "Mean foreground HBM-admission waiting time per request within each workflow. Differences include changed scheduling and cache behavior and are not an isolated causal Peer effect. " + ORDER)
    add("f0-revisit-hbm-pressure", "GPU 的低空闲显存时间占比", "按每张 GPU 的时长加权，统计 FREE 低于 1 GiB 的执行时间比例；保持真实 GPU 编号和同一阈值。包含可回收的普通缓存，低余量不等于 OOM、HBM 带宽饱和或服务违约。",
        F0 + "Time-weighted fraction of execution with less than 1 GiB FREE on each GPU, including reclaimable ordinary cache occupancy. GPU IDs and the threshold are shared across systems. Low headroom is not an out-of-memory event, hardware-bandwidth saturation or a service-level violation.")
    add("f0-revisit-ttft-cdf", "请求 TTFT 的完整分布", "所有 2,608 个请求从 release 到第一个输出 token 的经验分布；与只量 GPU prefill 的耗时不同，包含执行路径上的等待。",
        F0 + "Empirical time-to-first-token distribution of all 2608 requests per system, measured from request release to first output token, including waits along the execution path.")
    add("f0-revisit-tpot-tail", "请求平均 TPOT 的尾部", "每系统 2,432 个分母有效的请求先计算首 token 后的平均 TPOT，再绘制包含等号的经验生存比例；保留完整尾部。它不是逐 token ITL 分布，也不是跨运行置信区间。",
        F0 + "Inclusive empirical survival of request-mean time per output token after the first token. Each system contributes 2432 requests with a defined denominator. This is not a token-level inter-token-latency distribution.")
    add("f0-revisit-controller-service-difference", "逐 Workflow 的 CPU 服务报价变化", "对准入和前台派发的固定 CPU 服务报价按 Workflow 归因，再减 Mooncake；全局控制 CPU 单独计量。这条曲线不是每个 Workflow 的实测 CPU 利用率。",
        F0 + "Per-workflow difference from Mooncake in modeled controller service demand for admission and foreground dispatch. Global controller operations are not attributed to individual workflows. CPU quotes are fixed independent calibration means, not native serving utilization. " + ORDER, primary=False)
    add("f0-revisit-controller-breakdown", "进入模拟时序的控制 CPU 服务", "固定服务报价的总和，分为前台派发和准入；经过同一个控制器队列。提交、回收和 AIMD 的全部 CPU 工作量还没有完整转成因果延迟。",
        F0 + "Total modeled controller service demand for foreground dispatch and admission, using fixed means from separate Python calibration executions and one service queue. Commit, reclaim and AIMD CPU work is measured separately and is not fully inserted as causal delay.")
    add("reference-cpu-breakdown", "Python 参考实现的实际 CPU 工作量", "按线程 CPU 时间分解前台派发、准入与 DAG、提交、回收与 AIMD，扣除嵌套计量避免重复。它是本参考实现的组件工作量，未覆盖原生服务的全部 CPU。",
        F0 + "Exclusive measured thread CPU in the Python reference implementation, with nested measurements subtracted: foreground dispatch, admission and DAG value, commit, and reclaim plus AIMD. These are reference-component costs, not native serving utilization or all server CPU work.")
    add("f0-revisit-traffic-breakdown", "实际传输量的组成", "累计模拟内传输的字节，分为正常 GET、DRAM 写入和 Peer 复制，纵轴 TiB。更多副本写入与较少正常命中可能同时发生，不能仅比较总字节得出带宽无争用。",
        F0 + "Transferred bytes split into foreground GETs, DRAM writes and Peer copies (TiB). Each physical transfer is counted once. Traffic volume alone does not establish absence of contention; foreground GET slowdown is reported separately.")
    add("f0-revisit-transfer-service_slowdown", "保护流量是否拖慢前台 GET", "每个成功正常 GET 的实际传输服务时长 / 同字节量独占链路时长；横轴倍率。不同系统的命中对象和 GET 数量会变，CDF 是描述性分布。",
        F0 + "Empirical distribution of successful foreground GET service duration divided by the same transfer's isolated-link duration. Different cache decisions change GET counts and sizes; these distributions are descriptive rather than object-matched causal effects.")
    add("f0-revisit-background-copy", "逐 Workflow 的后台复制量", "DRAM 与 Peer 实际后台传输之和，按源 Workflow 归因；与固定 Workflow 顺序的 WCT 图配套诊断。",
        F0 + "Background DRAM plus Peer transfer bytes attributed to each source workflow. " + ORDER, primary=False)
    add("f0-revisit-peer-copy", "逐 Workflow 的 Peer 复制量", "只统计实际 Peer 传输，不用 AegisKV 总流量减 DRAM-only 来估算。Mooncake 与 DRAM-only 为重合零线。",
        F0 + "Actually transferred Peer-copy bytes per source workflow. Mooncake and DRAM-only AegisKV coincide at zero; Peer traffic is measured directly, not inferred by subtracting system totals. " + ORDER, primary=False)
    for q in (25, 50, 75):
        add(f"f1-q{q}-workflow-penalty", f"{q}% 进度选点的逐 Workflow 故障代价", f"三系统各用本系统 F1 减配对 F0；均为同一 2,608 请求输入。选点依据 Mooncake F0 的 {q}% 完成进度附近第一轮长请求，在其 prefill 60% 触发单 GPU 故障。包含已完成对象的零值与调度重排产生的负值。",
            F0 + f"Paired F1-minus-own-F0 WCT for a single 120 s GPU outage. The focal first-round long request is selected near {q}% completed-workflow progress in Mooncake F0; each system fails at 60% of that request's prefill. All workflows and signed changes are retained. " + ORDER, primary=q == 50)
    add("failure-progress-p95-penalty", "不同故障位置的尾部 Workflow 损失", "每个预定故障位置，对全部 160 个配对 Workflow 的 F1−F0 求 P95。三个位置是不同干预，不是同条件三次独立重复；实际参考进度另表给出。",
        F0 + "P95 signed paired-workflow WCT penalty at three prespecified failure-selection positions. Each point summarizes 160 workflows in one execution per system. Positions are different interventions, not independent repeats, and do not imply a per-workflow bound.")
    add("failure-focal-recovery-phases", "保护缩短的是哪个恢复阶段", "每根柱追踪同一个预定焦点请求：从故障到前缀装入，再到后缀计算与解码恢复；Peer/DRAM 恢复 token 和重算 token 另存 CSV。只缩短前缀装入不等于总恢复获益。",
        F0 + "Focal-request recovery at the three prespecified positions. Stacks split failure-to-prefix-materialization from suffix computation and decode resumption, including recovery queues. The same focal identity is compared across systems; restored and recomputed token counts accompany the CSV.")
    add("benefit-cost-fault-mixture", "何种故障概率下才能抵消正常开销", "解析混合 E[WCT]=(1−p)·F0+p·平均 F1，假定一次完整执行至多一个故障，三个预定位置等权。p 是分析参数，不能解释成观测故障率、MTBF 或多次故障结果。",
        "Analytical expected mean WCT formed as (1-p) times the simulated F0 mean plus p times the mean of the three simulated F1 conditions. At most one fault per execution and equal position weights are assumptions. The horizontal axis is not an observed failure frequency or a repeated-failure model.")
    for name, title, fault in [("order-normal-wct", "更换入场顺序后的正常 WCT", False), ("order-failure-penalty", "更换入场顺序后的故障代价", True)]:
        add(name, title, "三种预定入场顺序包含相同 160 个 Workflow；每个经验分位的线为中位数、阴影为三个顺序的最小/最大值，不是置信区间，也没有合并成 480 个独立样本。" + ("每个顺序各自从 Mooncake F0 选择中期故障，再减本系统对应 F0。" if fault else "无故障、资源和两轮输入均相同。"),
            F0 + "At each empirical rank, the line is the median and shading the min/max across three prespecified admission orders of the same workflows, not a confidence interval or 480 independent observations. " + ("Each order uses its own Mooncake-selected mid-execution focal fault and matched F0." if fault else "The curves report no-failure WCT."))
    for b in (1, 4):
        add(f"native-forward-b{b}", f"真实 forward 与 DMA 并发：batch {b}", f"batch={b}，额外触达分配 8 GiB；prompt 为 512/2,048/4,096 tokens。每个测量块内用相同 prompt 的无复制 forward 归一化；Peer 输入、输出和 DRAM 写入分开测。",
            NATIVE + f"Batch {b}, 8 GiB additional touched HBM allocation and three prompt lengths. Forward duration is paired with the no-copy condition in the same block. Concurrent Peer input, Peer output and DRAM PUT are distinct directions; values above one are slower.")
    add("native-memory-occupancy", "分配容量与复制争用分别测量", "batch=4、prompt=4,096，额外触达分配 0/8/16 GiB；比较四种 DMA 条件的真实 forward 时长。纵轴放大局部变化，零 OOM 只适用于这批条件。",
        NATIVE + "Batch 4, prompt length 4096 and additional touched HBM allocations of 0, 8 and 16 GiB. Forward duration is shown for no copy and three concurrent DMA directions. The vertical axis is zoomed; absence of OOM in these conditions is not a memory-safety guarantee.")
    add("native-concurrent-copy", "真实复制速率随前台计算变化", "batch=1、额外占用 8 GiB，按每个块的实际复制字节 / 复制完成时间聚合；256 MiB 缓冲反复复制。这里的并发有效速率不是链路标称容量。",
        NATIVE + "Concurrent completed-copy rate for batch 1 and 8 GiB additional allocation. Each block aggregates bytes over copy-completion time using 256 MiB buffers. Rates under foreground computation are not link-capacity specifications.", primary=False)
    add("native-release-ack", "撤销备份后的实际释放延迟", "1/4/8 GiB 分配各 20 次：等待异步写入 fence 与 allocator free+empty_cache+同步分开测。两部分都是实测完成时间，不能直接替代原生服务的回收延迟。",
        "Native release microbenchmark on the same L40S allocation, 20 trials per 1/4/8 GiB object. Markers and ranges report median and min/max for the pending-write fence and allocator free plus empty-cache and device synchronization separately. This component sequence is not an end-to-end serving reclamation measurement.")
    add("native-copy-cpu", "原生复制线程的 CPU 需求", "batch=1、额外占用 8 GiB，测量整个 forward 窗口的进程 CPU / 墙钟时间，以核数表示；包含本微基准的复制线程与 CUDA 同步等待。它不等价于原生 AegisKV 准入 CPU 或整台服务器利用率。",
        NATIVE + "Batch 1 and 8 GiB additional allocation. Process CPU divided by elapsed forward time gives average core demand, including this benchmark's copy thread and CUDA synchronization behavior. It is not native AegisKV admission CPU or whole-server utilization.", primary=False)
    add("ablation-normal-wct", "Algorithm 2 / 3 的正常服务消融", "分别去掉 DAG 联合价值、将空闲门改为严格 G>0、或将动态 Peer 改为静态容量上限。相同输入与 CPU 报价，每次只改一个因素；减少保护可能降低正常开销，也可能损失恢复覆盖。",
        F0 + "One-factor AegisKV ablations: sum of recovery savings instead of joint DAG WCT, strict positive-gain free admission, and a static Peer cap. CPU quotes remain fixed. Lower F0 overhead alone does not establish a superior fault-protection policy.")
    add("ablation-lazy-refresh", "惰性计算是否保持同样的准入决策", "DRAM-only 上比较 Lazy / Eager：两者都检查全部可释放尾块，只允许跳过版本未变的价值计算。比较每次接纳/拒绝与牺牲块序列必须完全相同；计数包含被拒绝的试算。",
        F0 + "Lazy versus eager value evaluation in DRAM-only AegisKV. All eligible tails are checked in both modes; only unchanged value evaluation is skipped. The complete admission-status and victim sequences are asserted identical. Counts include rejected trials, and fixed CPU quotes are unchanged.")
    add("aimd-quota-and-occupancy", "AIMD 授权与实际副本占用", "在 30% DMA 额外 forward 时长的敏感性条件下，按 50 ms 窗口汇总 8 张 GPU 的 C、Q 和实际副本。物理占用含 pending；模拟器在 fence 后同步 free，真实释放时长另图测量。",
        F0 + "AegisKV under an explicit 30% DMA forward-time sensitivity coefficient. Memory ceiling C, granted quota Q and charged physical copies are summed over eight targets every 50 ms. Pending copies remain charged. DES release is synchronous after fencing; native release latency is measured separately.")
    add("aimd-warning-windows", "预警反馈是否随控制变化", "同一 30% 争用假设下，比较 Guarded AIMD 和只保留显存上限的 Static Peer；1 s 桶内统计产生归一化 forward 预警的目标窗口比例。预警不是请求 SLO 违约率。",
        F0 + "Guarded AIMD versus a static Peer cap under the same 30% DMA coefficient. One-second bins aggregate eight targets' 50 ms warning observations. Warnings are normalized forward-delay controller signals, not request-SLO violations; each curve stops at its own execution completion.")
    add("ablation-aimd-interference", "强争用下动态控制的 WCT 影响", "相同 30% DMA 假设，比较 DRAM-only、Guarded AIMD 和 Static Peer；静态版本仍尊重显存硬上限。容量守恒与前台时延保护是两个不同问题。",
        F0 + "Mean WCT under the same 30% DMA sensitivity coefficient for DRAM-only AegisKV, Guarded AIMD and static Peer permission. Static Peer retains the memory ceiling but omits warning-driven feedback.", primary=False)
    settings = [
        ("bandwidth", "共享路径带宽敏感性", "5/25/50 GB/s", "mean WCT", True),
        ("dram-capacity", "DRAM 容量与正常命中", "250 GB / 1 TB", "token-weighted DRAM hit rate", True),
        ("concurrency", "活跃 Workflow 并发敏感性", "16/32 个活跃 Workflow", "mean WCT", False),
        ("cpu-quote", "CPU 服务报价的敏感性", "1×/2× 固定 CPU 报价", "mean WCT", False),
        ("dma", "硬件 DMA 争用系数的敏感性", "0/5/30% 额外 forward 时长", "mean WCT", False),
    ]
    for name, title, setting, metric, primary in settings:
        add(f"sensitivity-{name}", title, f"实际执行 {setting}，其余保持默认；每个点是该配置的整批汇总，三系统配对。连线只连接已测设置，不能外推为连续函数。CPU/DMA 系数是模型参数。",
            F0 + f"Sensitivity of {metric}; only the displayed parameter is varied and only marked settings were executed, once per system. Segments connect tested settings. CPU and DMA coefficients are explicit model sensitivity parameters.", primary=primary)
    for row in rows:
        name = row["name"]
        if name == "failure-focal-recovery-phases":
            row["caption_zh"] += " 每个故障位置的柱从左到右均为 Mooncake、DRAM-only AegisKV、AegisKV；颜色表示系统，纹理表示恢复阶段。"
            row["caption_en"] += " Within each position, bars follow legend order from left to right: Mooncake, DRAM-only AegisKV, AegisKV. Color denotes the system and hatching denotes the recovery phase."
        if "workflow-penalty" in name or name in {"f0-revisit-wct", "f0-revisit-wct-difference", "f0-revisit-dram-hit", "f0-revisit-scheduler-queue", "f0-revisit-hbm-wait", "f0-revisit-controller-service-difference", "f0-revisit-background-copy", "f0-revisit-peer-copy"}:
            row["caption_zh"] += " 每隔 10 个对象添加识别标记，连线保留全部 160 个 Workflow。"
        if name in {"sensitivity-cpu-quote", "sensitivity-dma"}:
            row["caption_zh"] += " 纵轴展示实际秒值的局部范围，以辨认小幅差异。"
            row["caption_en"] += " The local vertical range shows actual seconds to resolve small differences."
        if name == "aimd-warning-windows":
            row["caption_zh"] += " 纵轴 0–20% 覆盖全部观测值。"
            row["caption_en"] += " The 0–20% vertical range includes all observations."
        if name in {"aimd-quota-and-occupancy", "aimd-warning-windows"}:
            row["caption_zh"] += " 两张控制时序图共用横轴范围，各曲线保留自身观测终点。"
            row["caption_en"] += " Both control views share horizontal limits; each curve retains its own observed endpoint."
        if name == "design-guarded-aimd":
            row["caption_zh"] += " 右列表示下一步前台需求增加 4 GiB，裁剪后旧副本仍占 4 GiB，物理 free ACK 到达才降至 2 GiB。"
            row["caption_en"] += " The right-hand case anticipates 4 GiB of additional foreground demand: existing copies remain at 4 GiB after permission is clipped and fall to 2 GiB only after the physical free ACK."
        if row["name"].startswith("native-"):
            if row["name"] == "native-release-ack":
                row["caption_zh"] += " 标记和误差线为 20 次测量的中位数与最小/最大值。"
            else:
                row["caption_zh"] += " 每条件含同一次 GPU 分配中的 5 个随机交错测量块；标记和误差线为中位数与最小/最大值，不是置信区间。"
        if row["name"].startswith("f1-q"):
            row["caption_zh"] += " 三个故障位置使用同一纵轴范围。"
            row["caption_en"] += " The three fault-position exports share the same vertical limits."
    from agent_lease_draft_captions import CAPTIONS, PAPER_CAPTIONS_EN
    for name in ["motivation-recovery-exposure", "evaluation-resource-cost",
                 "evaluation-native-interference", "evaluation-configuration-effects"]:
        title, zh = CAPTIONS[name]
        add(name, title, zh, PAPER_CAPTIONS_EN[name])
    for row in rows:
        row["primary"] = row["name"] in CAPTIONS
        if row["primary"]:
            row["caption_en"] = PAPER_CAPTIONS_EN[row["name"]]
    return rows
