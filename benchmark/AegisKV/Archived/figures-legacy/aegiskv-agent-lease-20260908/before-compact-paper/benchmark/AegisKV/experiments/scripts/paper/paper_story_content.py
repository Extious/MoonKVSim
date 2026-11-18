"""Per-figure claims and standalone English captions for the narrative edition."""

HEALTHY = (
    "Mechanism simulation of the controlled two-round workload: 160 paired workflows, "
    "2608 requests, C=16, 1 TB DRAM and a 25 GB/s shared path. One execution per system. "
)
PAIRED = (
    "The same ordering by Mooncake's no-failure revisit WCT is used in every workflow view; "
    "each position denotes one workflow, and lines do not denote a time series. "
)
FAULT = (
    "Mechanism simulation on the original 160-workflow, 1304-request workload; C=16, "
    "1 TB DRAM, 25 GB/s. Each system is compared with its own matched no-failure execution. "
)


def records():
    result = []

    def add(section, ident, name, title, zh, en, *, old=None, evidence="modeled_exploration"):
        result.append(
            dict(
                section=section,
                id=ident,
                name=name,
                title=title,
                caption_zh=zh,
                caption_en=en,
                old_id=old,
                evidence=evidence,
            )
        )

    add(
        "Motivation",
        "M1",
        "motivation-branch-gap",
        "并行分支的时间差",
        "124 个存在观测重叠分支的真实工作流，每个样本取工作流内最大分支持续时间差；横轴为对数秒。持续时间差尚未验证为因果 CPM Slack。",
        "Empirical distribution of the maximum parallel-branch duration gap in each of 124 observed workflows with overlapping branches. The horizontal axis is logarithmic. These observed duration differences are not validated causal CPM slack.",
        old="P01",
        evidence="trace_observation",
    )
    add(
        "Motivation",
        "M2",
        "motivation-exposed-recovery",
        "相同恢复代价对应不同 Workflow 损失",
        "固定 DAG 中仅一个分支受延迟、其余执行时间和资源条件不变时，暴露给 Workflow 的延迟为 max(恢复延迟 − Slack, 0)。0/5/10 s 是示意参数。",
        "Analytical illustration of exposed recovery delay, max(recovery delay - slack, 0), for slack values of 0, 5 and 10 seconds. Only one branch is delayed in a fixed DAG; other durations and resource conditions remain fixed. This is not an observed failure experiment.",
        evidence="analytical",
    )
    add(
        "Motivation",
        "M3",
        "motivation-kv-capacity",
        "额外 KV 副本的容量代价",
        "Qwen3-8B BF16 按 147,456 B/token 计算；96 Ki tokens 的一份/两份 KV 为 13.5/27 GiB。灰线从 40 GiB 扣权重及 2 GiB runtime，未扣动态前台 KV。",
        "Analytical KV footprint for Qwen3-8B BF16 at 147456 bytes per token (Ki=1024). At 96 Ki tokens, one and two copies occupy 13.5 and 27 GiB. The dotted line subtracts model weights and 2 GiB runtime from 40 GiB HBM, before dynamic foreground KV; it is not a lendable Peer quota.",
        old="P02",
        evidence="analytical",
    )

    add(
        "System Design",
        "S1",
        "system-overview",
        "整体数据流与控制职责",
        "revision-3 设计。实线传 KV、虚线传控制；Source 分别写 Peer HBM 与 Store DRAM。恢复时已提交副本需装入新 primary。本轮执行范围由 Evaluation 配置表限定。",
        "AegisKV revision-3 design. Solid arrows carry KV data and dashed arrows carry control. The source writes independently to Peer HBM and Store DRAM; committed backup data must be materialized into a new primary for recovery. The complete design is broader than the implementation subset evaluated here.",
        old="P03",
        evidence="design",
    )
    add(
        "System Design",
        "S2",
        "design-slack-tickets",
        "Algorithm 1：从因果依赖得到 Slack ticket",
        "残余 DAG 与剩余时间估计进入前向/后向 CPM；ES/LS 为最早/最晚开始时间，m 为保守余量。ticket 绑定 consumer、DAG 版本和有效期；信息不足的相关消费者回退为零 Slack。",
        "Algorithm 1 turns a residual DAG and remaining-time estimates into versioned slack tickets. ES and LS denote earliest and latest start times; m is a conservative margin. Unknown structure, missing estimates or stale versions invalidate affected tickets to zero. Predictor accuracy is not established by this design illustration.",
        evidence="design",
    )
    add(
        "System Design",
        "S3",
        "design-shared-prefix",
        "Algorithm 2：共享前缀与删除闭包",
        "C0/C1 由两个 consumer 共享，物理字节只计算一次。删除 C1 必须一并删除其已提交后代 C2-A/C2-B；虚线表示 consumer 引用，实线表示前缀父子关系。",
        "Shared-prefix accounting in Algorithm 2. Consumers A and B share physical chunks C0 and C1. Evicting C1 requires its committed descendants C2-A and C2-B to be evicted as a closure. Solid arrows are prefix-parent relationships, dashed arrows are consumer references, and shared physical bytes are counted once.",
        evidence="design",
    )
    add(
        "System Design",
        "S4",
        "design-foreground-budget",
        "Algorithm 3：前台约束先于保护",
        "分配、复制、配额增长前同时检查 HBM 包络、传输许可和有效 QoS 证书。配额增长还需稳定余量、实际需求及已完成回收；失效即撤销，释放 ACK 前不能复用额度。",
        "Algorithm 3 checks memory and transfer envelopes before allocation, copying or quota growth. A fresh QoS certificate is additionally required. Growth needs stable headroom, demand and completed reclamation; invalid conditions revoke permission, and capacity remains charged until a free ACK. This illustrates the full design, not a certificate obtained by the simulation.",
        evidence="design",
    )
    add(
        "System Design",
        "S5",
        "commit-tier-timeline",
        "复制完成与独立提交",
        "同一 chunk 的 Peer copy ACK 先到，源故障时 DRAM 尚 pending，随后 abort。两个 tier 的提交状态独立；横轴只有逻辑先后，间距不是测得时长。",
        "Independent tier commits for one chunk. The Peer copy is acknowledged before source failure, while the pending DRAM copy aborts. Horizontal spacing denotes logical event order, not measured duration. A committed Peer copy does not imply a committed DRAM copy.",
        old="P04",
        evidence="design",
    )
    add(
        "System Design",
        "S6",
        "commit-recoverable-prefix",
        "故障时只有连续已提交前缀有效",
        "承接图 S5，Peer 可恢复 chunks 0–1，DRAM 只有 chunk 0；aborted/absent 不计恢复 token。所有 chunk 均为示意对象。",
        "Recoverable prefix after the illustrated failure. Peer HBM has committed chunks 0-1, whereas Store DRAM has only chunk 0. Aborted or absent chunks provide no recovery tokens. Each tier computes its own continuous committed prefix; these are illustrative chunks.",
        old="P05",
        evidence="design",
    )
    add(
        "System Design",
        "S7",
        "commit-materialize-recompute",
        "前缀装入与恢复解码是不同阶段",
        "备份 chunks 0–1 先复制进新的 primary buffers，再重算 suffix 2、恢复解码。箭头不表示字节量或时长，装入完成不等于恢复完成。",
        "A committed backup prefix must first be copied into new primary buffers. The unprotected suffix is then recomputed before decoding resumes. Arrows are conceptual and do not encode time or bytes; prefix materialization and decode resumption are distinct milestones.",
        old="P06",
        evidence="design",
    )

    add(
        "Evaluation",
        "E1",
        "workload-prompt_tokens",
        "原始输入的 Prompt 分布",
        "冻结 FanOutQA 派生输入的 1,304 个请求；Ki=1,024 tokens。仅含原始访问，总上下文最大 86,214 tokens，未宣称覆盖 128K。",
        "Prompt-length distribution of the 1304 original requests in the frozen FanOutQA-derived workload (Ki=1024). Synthetic revisit requests are excluded. The maximum total context is 86214 tokens, so this workload does not establish coverage of 128K contexts.",
        old="P07",
        evidence="workload_description",
    )
    add(
        "Evaluation",
        "E2",
        "workload-workflow_call_counts",
        "Workflow 规模分布",
        "同一输入中 160 个 Workflow 的原始调用数分布，最大为 27；样本单位是 Workflow，两轮重访不混入这张输入统计图。",
        "Distribution of original call counts across 160 frozen workflows, with a maximum of 27 calls. A sample is a workflow. These counts precede the controlled duplication of the complete DAG into two rounds.",
        old="P08",
        evidence="workload_description",
    )
    add(
        "Evaluation",
        "E3",
        "f0-revisit-wct",
        "逐 Workflow 的 WCT",
        "无故障两轮重访，160 个 Workflow 严格配对；按 Mooncake WCT 统一排序。均值依次为 53.39/64.05/69.74 s；WCT 不含活跃 slot 外的入场等待。",
        HEALTHY
        + "WCT runs from first release to final request completion, excluding admission waiting outside active workflow slots. "
        + PAIRED,
        old="P09",
    )
    add(
        "Evaluation",
        "E4",
        "f0-revisit-wct-difference",
        "逐 Workflow 的 WCT 增减",
        "图 E3 的逐对象差值：各系统 WCT 减 Mooncake WCT；正值更慢，负值更快。AegisKV 有 129/160 个 Workflow 更慢；不按正负筛选样本。",
        HEALTHY
        + "WCT difference from Mooncake for each paired workflow; positive values are slower. Mooncake is the zero reference. "
        + PAIRED,
        old="P10",
    )
    add(
        "Evaluation",
        "E5",
        "f0-revisit-wct-cdf",
        "WCT 的整体分布",
        "图 E3 中全部 160 个 Workflow 的经验分布；保留完整尾部。这里的分布描述同一次执行中的异质工作流，不提供跨独立重复置信区间。",
        HEALTHY
        + "Empirical WCT distributions contain all 160 workflows per system, including the full tail. Workflows describe within-execution heterogeneity, not independent execution replicates; no population confidence interval is inferred.",
    )
    add(
        "Evaluation",
        "E6",
        "f0-revisit-dram-hit",
        "准入改变后的 DRAM 复用率",
        "正常服务实际复用的 DRAM token / 全部 prompt token，包含冷访问与第二轮访问。总体 token 加权比例为 48.08%/26.54%/18.89%，不是请求命中比例。",
        HEALTHY
        + "For each workflow, DRAM token hit rate is actually reused DRAM prompt tokens divided by all prompt tokens, including both cold and revisit rounds. Recovery tokens are excluded. "
        + PAIRED,
        old="P11",
    )
    add(
        "Evaluation",
        "E7",
        "f0-revisit-cache-sources",
        "正常服务的缓存来源分解",
        "对全部 prompt token 做互斥分解：Local HBM、Store DRAM、Peer HBM 和重新计算，合计 100%。本配置正常请求的 Peer 命中为零；Peer 备份字节不算正常复用收益。",
        HEALTHY
        + "Exclusive decomposition of all prompt tokens into Local HBM reuse, Store DRAM reuse, Peer HBM reuse and computed tokens. Fractions sum to 100%; normal Peer reuse is zero in these runs. Backup bytes are not counted as foreground cache hits.",
    )
    add(
        "Evaluation",
        "E8",
        "f0-revisit-scheduler-queue",
        "前台 GPU 调度排队",
        "点为 Workflow 内请求首次实际入 GPU 队列到首次计算的平均等待；CPU、GET 和 HBM 申请等待另计。请求级 P95 依次为 9.48/13.15/16.72 s，不能把点误读为 P95。",
        HEALTHY
        + "Workflow means of request delay from actual GPU scheduler admission to first compute. CPU, GET and destination-HBM reservation delays are separate. "
        + PAIRED,
        old="P12",
    )
    add(
        "Evaluation",
        "E9",
        "f0-revisit-hbm-wait",
        "GET 目标 HBM 的申请等待",
        "逐 Workflow 的请求平均 HBM 申请等待。跨请求累计为 414.33/63.42/4.15 s；方向与 GPU 排队不同，GET 样本量也随命中率变化，不能独立归因为 Peer。",
        HEALTHY
        + "Workflow means of foreground DRAM GET destination-HBM reservation waiting, including zero-wait requests. GET populations differ with cache hits; cumulative wait is not an additive WCT penalty. "
        + PAIRED,
        old="P13",
    )
    add(
        "Evaluation",
        "E10",
        "f0-revisit-hbm-pressure",
        "全部 GPU 的显存占用压力",
        "按事件区间积分，统计每个 GPU 未分配 HBM 低于 1 GiB 的时间比例。包括可回收缓存占用，分母为各系统自身 workload makespan；不是硬件 HBM 带宽利用率。",
        HEALTHY
        + "For each of all eight GPUs, event-interval integration measures the fraction of workload time with less than 1 GiB unallocated HBM. Reclaimable caches remain allocated. Denominators are each system's workload makespan; this is not hardware HBM bandwidth utilization.",
        old="P14",
    )
    add(
        "Evaluation",
        "E11",
        "f0-revisit-ttft-cdf",
        "首 token 延迟分布",
        "全部 2,608 个请求的 TTFT，横轴用对数秒以同时显示主体与完整尾部。P99 为 21.68/22.20/27.87 s；没有据此宣称满足原生 QoS 阈值。",
        HEALTHY
        + "Empirical time-to-first-token distributions for all 2608 requests per system. The time axis is logarithmic and retains the complete range. These modeled values are not a native-serving QoS certificate.",
    )
    add(
        "Evaluation",
        "E12",
        "f0-revisit-tpot-tail",
        "请求平均 TPOT 的长尾",
        "每系统 2,432 个 TPOT 有定义的请求；双对数生存曲线给出不小于横轴值的请求比例。每个请求先求平均 TPOT，不能当成逐 token 间隔分布。",
        HEALTHY
        + "Inclusive empirical survival of request-mean time per output token (TPOT), for 2432 requests with defined TPOT per system. Both axes are logarithmic. Each observation is a request mean rather than an individual inter-token gap; extreme values are retained.",
    )
    add(
        "Evaluation",
        "E13",
        "f0-revisit-controller-service-difference",
        "逐 Workflow 的控制面代价",
        "查询与准入的模型服务需求减 Mooncake 对应值；按相同 Workflow 配对。CPU 报价固定，前台查询 50 µs 为假设，不是原生 CPU 利用率。",
        HEALTHY
        + "Paired controller service demand (foreground lookup plus admission), relative to Mooncake. Service quotations are fixed; the 50 microsecond foreground lookup cost is assumed. This is modeled CPU service, not native CPU utilization. "
        + PAIRED,
        old="P15",
    )
    add(
        "Evaluation",
        "E14",
        "f0-revisit-controller-breakdown",
        "控制面服务需求的组成",
        "按事件将前台查询与准入服务时间求和，总量为 2.58/5.44/6.05 s。该和不含排队，也不等于请求延迟或 CPU 使用百分比。",
        HEALTHY
        + "Additive controller service demand separated into foreground lookup and admission. Totals are 2.58, 5.44 and 6.05 seconds for Mooncake, DRAM-only AegisKV and AegisKV. Waiting time is excluded; this sum is neither request latency nor CPU utilization.",
    )
    add(
        "Evaluation",
        "E15",
        "f0-revisit-background-copy",
        "逐 Workflow 的后台传输量",
        "DRAM 写入与 Peer 复制的实际传输字节，含中止前已传部分及收尾阶段；按源请求归属 Workflow 累计。它表示累计流量，不能当作驻留副本容量。",
        HEALTHY
        + "Actual DRAM-write plus Peer-copy bytes, attributed to the source workflow, including partially completed aborted copies and cleanup traffic. Values are cumulative transfer volume, not resident capacity or instantaneous bandwidth. "
        + PAIRED,
        old="P16",
    )
    add(
        "Evaluation",
        "E16",
        "f0-revisit-peer-copy",
        "新增 Peer 路径的传输成本",
        "直接累计 Peer flow 的实际字节。Mooncake 和 DRAM-only 的两条零线重合，因为未启用该路径；不用两个系统的总流量之差估计 Peer 流量。",
        HEALTHY
        + "Peer-copy bytes are counted directly from Peer flows. Mooncake and DRAM-only AegisKV have overlapping zero lines because the path is disabled. Cross-system total-traffic subtraction is not used to estimate this component. "
        + PAIRED,
        old="P17",
    )
    add(
        "Evaluation",
        "E17",
        "f0-revisit-traffic-breakdown",
        "前台读取与后台复制的组成",
        "由实际传输记录互斥分解为正常 GET、DRAM 写入和 Peer 复制，含已传输的中止部分与收尾；TiB=2^40 bytes。Peer 开启后 DRAM 流量本身也会改变。",
        HEALTHY
        + "Transferred bytes are partitioned into foreground GET, DRAM writes and Peer copies, including transferred portions of aborted flows and cleanup. TiB denotes 2^40 bytes. DRAM-write volume also changes when Peer protection is enabled.",
    )
    add(
        "Evaluation",
        "E18",
        "f0-revisit-transfer-service_slowdown",
        "正常 GET 的链路争用",
        "GET 数据服务时间 / 相同字节量的独占瓶颈服务时间，不含固定 setup。成功 GET 样本数为 1,284/773/662，P95 为 33.56/10.71/12.65 倍；不是隔离 Peer 效应的因果对照。",
        HEALTHY
        + "Successful foreground GET data-service time divided by isolated bottleneck service time for the same bytes; fixed setup is excluded. There are 1284, 773 and 662 GETs respectively. Population and byte-size differences prevent an isolated causal interpretation of the CDF separation.",
        old="P18",
    )
    for q, ident in [(25, "E19"), (50, "E20"), (75, "E21")]:
        add(
            "Evaluation",
            ident,
            f"f1-q{q}-workflow-penalty",
            f"{q}% 进度附近故障的逐 Workflow 影响",
            f"按无故障基准完成进度选择最接近 {q}% 的合格请求，在其 prefill 60% 处触发逻辑 GPU 故障。各系统减自身 F0；保留全部 160 个 Workflow 的正负变化，沿用图 E3 的 ID 顺序。",
            FAULT
            + f"A focal request is preselected nearest {q}% baseline workflow completion and failed at 60% fresh prefill progress. All 160 signed workflow WCT differences are shown in the shared ordering used by the no-failure revisit figures; each system is executed once.",
        )
    add(
        "Evaluation",
        "E22",
        "failure-progress-p95-penalty",
        "故障位置与尾部 WCT 代价",
        "三个预定故障位置的逐 Workflow WCT 差值之 P95，横轴为真实基准完成比例。先逐对象求差再求 P95；包含故障前已完成对象，因此跨位置的下降不能直接解释为单次恢复更容易。",
        FAULT
        + "P95 of 160 paired workflow WCT differences at each predeclared fault location, including workflows completed before failure. The x axis is realized baseline completion fraction. Later locations include more already-completed workflows; this curve does not isolate recovery difficulty. Percentiles are taken after pairing, and the three interventions are not independent replicates.",
    )
    add(
        "Evaluation",
        "E23",
        "failure-focal-recovery-phases",
        "故障请求恢复的阶段分解",
        "每位置仅展示预先选定的焦点请求。前段为故障至连续前缀装入，后段为装入后至恢复解码；分别包括对应等待和实际服务。总长才是焦点请求恢复延迟。",
        FAULT
        + "Recovery of the one preselected focal request at each location. The first phase runs from failure to continuous-prefix materialization, including reservation, setup and copying. The second runs to decode resumption, including suffix computation and scheduling. Phase boundaries come from distinct events; bars are not averages over all affected requests.",
    )
    add(
        "Evaluation",
        "E24",
        "sensitivity-bandwidth-mean_wct_s",
        "带宽改变时的完成时间权衡",
        "5/25/50 GB/s 的实际测试点，线性横轴。其他配置相同，每点每系统一次执行、160 个 Workflow。5 GB/s 均值为 150.45/81.00/82.07 s，比较方向反转。",
        "Mean WCT in the two-round mechanism workload at 5, 25 and 50 GB/s; C=16 and DRAM=1 TB are fixed. Each point summarizes 160 workflows in one execution per system. The bandwidth axis is linear and segments only connect tested points; no independent-repeat confidence interval is inferred.",
        old="P19",
    )
    add(
        "Evaluation",
        "E25",
        "sensitivity-concurrency-mean_wct_s",
        "并发压力与 Workflow 完成时间",
        "活跃 Workflow 并发 8/16/32，线性横轴，其他条件相同。点为 160 个 Workflow 的平均 WCT；闭环入场时间随先前完成变化，不能作为开放到达率吞吐曲线。",
        "Mean WCT in the two-round mechanism workload at 8, 16 and 32 active workflows; DRAM=1 TB and bandwidth=25 GB/s are fixed. Each point is one execution with 160 workflows. This closed-loop concurrency sweep is not throughput at a fixed open-loop arrival rate.",
        old="P20",
    )
    add(
        "Evaluation",
        "E26",
        "sensitivity-dram-capacity-dram_hit_pct",
        "DRAM 容量与正常复用率",
        "32/128/931.3 GiB 的实际容量，对数横轴（底 2）。token 命中率包含两轮全部 prompt token；C=16、25 GB/s，每点每系统一次执行。",
        "DRAM prompt-token hit rate in the two-round mechanism workload at 32, 128 and 931.3 GiB, using a base-2 logarithmic capacity axis. C=16 and bandwidth=25 GB/s are fixed. The denominator includes both cold and revisit prompt tokens; each point is one execution per system.",
        old="P21",
    )
    removed = {
        "motivation-exposed-recovery",
        "commit-recoverable-prefix",
        "commit-materialize-recompute",
    }
    result = [r for r in result if r["name"] not in removed]
    by_name = {r["name"]: r for r in result}
    by_name["motivation-kv-capacity"]["id"] = "M2"
    revisions = {
        "system-overview": (
            "保护路径与资源所有权",
            "工作流依赖对应版本化控制状态；Source 分别写 Peer HBM 与 Store DRAM。图中画出 primary、backup、共享消费者和独立复制路径；恢复时备份仍需装入 primary 空间。",
            "AegisKV protection paths and resource ownership. Workflow dependencies produce versioned control state. Sealed source chunks are copied independently to Peer HBM and Store DRAM. Primary buffers, backup buffers and shared consumer references are explicit. Loading a backup into primary memory remains a separate operation. The complete revision-3 design is broader than the evaluated subset.",
        ),
        "design-slack-tickets": (
            "一个 DAG 中的 Slack 与保守 ticket",
            "同起点的 A/B 分支分别执行 3/8 s，在 8 s 汇合。A 的结构 Slack 为 5 s，扣 1 s 保守余量后 ticket 为 4 s；B 为零。epoch=7 和所有时长均为设计示例。",
            "Worked design example for Algorithm 1. Branches A and B start together and take 3 and 8 seconds; their join completes at 8 seconds. A has ES=0 and LS=5; with a one-second conservative margin, its ticket carries four seconds of slack. B has zero slack. Structural nodes cost zero, and invalid versioned tickets fall back to zero. These illustrative values are not predictor measurements.",
        ),
        "design-shared-prefix": (
            "共享前缀的物理容量与联合删除损失",
            "A/B 各引用三个等长 chunk，其中 C0/C1 共享；六次逻辑引用对应 4b 物理字节。删除 C1 的后代闭包释放 3b，而两个 consumer 各损失 2b 可复用前缀；b 为一个 chunk 的字节数。",
            "Worked shared-prefix example for Algorithm 2, with equal chunk size b bytes. Six logical chunk references occupy four physical chunks because A and B share C0 and C1. Evicting C1 and its descendants frees 3b bytes, while each consumer loses 2b of reusable prefix. Capacity and consumer-level loss therefore require different accounting. Values are illustrative, not an admission-performance measurement.",
        ),
        "design-foreground-budget": (
            "显存包络收缩与 free ACK 前的计账",
            "40 GiB 示意包络：固定占用 16、primary 12、前台预留 6、Peer 6。primary 新增 4 GiB 使 Peer 上限降至 2；撤销后仍按 6 计账，收到 free ACK 后才降至 2。示意数值不代表实测 allocator 轨迹。",
            "Illustrative Algorithm 3 memory envelope, not an observed allocator trace. A 40 GiB envelope initially contains 16 GiB fixed memory, 12 GiB primary KV, 6 GiB foreground reserve and 6 GiB charged Peer memory. A four-GiB primary increase reduces the Peer ceiling to two GiB. Revoked bytes remain charged until their free ACK. Copy permission additionally requires source, destination and link budgets and a fresh QoS certificate.",
        ),
        "commit-tier-timeline": (
            "从独立提交到故障后的前缀装入",
            "同一 C1 的 Peer ACK 先于源故障，DRAM pending 随后 abort；故障时 Peer 可恢复 C0–C1，DRAM 仅 C0。备份装入新 primary 后仍需重算 C2 才恢复解码。时间线表示逻辑次序，全部 chunk 为示意。",
            "Independent commit and recovery of the same KV objects. Peer acknowledges C1 before source failure; the pending DRAM copy aborts. The failure snapshot exposes a two-chunk Peer prefix and a one-chunk DRAM prefix. Recovery materializes C0-C1 into a new primary and recomputes C2 before decoding resumes. Filled cells are committed; dashed cells are pending or absent and a crossed cell is aborted. Event spacing is logical order, not measured duration.",
        ),
    }
    for name, (title, zh, en) in revisions.items():
        by_name[name].update(title=title, caption_zh=zh, caption_en=en)
    for row in result:
        row["old_ids"] = [row["old_id"]] if row["old_id"] else []
    by_name["commit-tier-timeline"]["old_ids"] = ["P04", "P05", "P06"]
    return result
