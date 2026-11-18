"""Twelve argument-selected captions for the compact manuscript edition."""

CAPTIONS = {
    "motivation-branch-gap": ("并行分支的执行时间不均衡", "CC/Weka 中 124 个具有重叠分支的 Workflow；每个对象取最大分支持续时间差。横轴为对数秒。该观测描述不均衡，不直接估计可用 Slack。"),
    "motivation-recovery-exposure": ("重算代价与 Workflow 损失并不等价", "同一五分支轨迹中，分别在 349.5 s 假设单分支故障。柱长为模型化重算时间，分为被并行执行吸收和推迟汇合两部分。旧 Qwen3-235B/A100 配置的反事实推演，不是实测故障或后文 8B 实验。"),
    "motivation-kv-capacity": ("长上下文 KV 的容量约束", "Qwen3-8B BF16 的解析容量，Ki=1,024。参考线从 40 GiB 扣除模型权重与 2 GiB runtime，尚未扣除动态前台 KV，不能当作可借备份额度。"),
    "system-overview": ("AegisKV System Overview", "源端独立向 Peer HBM 和 DRAM 复制同名 KV；复制确认后才可读取。Workflow 价值与池级准入决定保护对象，独立控制器约束 Peer 显存借用。故障后从可用层装入新的 primary C0、C1，再重算 C2。实线为数据，虚线为控制。"),
    "f0-revisit-wct": ("无故障条件下的逐 Workflow WCT", "相同 160 个 Workflow、每个完整 DAG 两轮重访。三系统共用按 Mooncake F0 WCT 排序的 ID 序列，保留全部对象；连线不是执行时间轴。轨迹驱动模拟，默认配置见正文。"),
    "f1-q50-workflow-penalty": ("中期故障引起的配对 WCT 变化", "各系统 F1 减自身 F0，正值为延长，负值保留。故障焦点由 Mooncake 完成 80/160 个 Workflow 时的逻辑进度预选。全部对象沿用图 5 顺序，已完成对象也纳入。"),
    "f0-revisit-dram-hit": ("DRAM 保留策略对正常复用的影响", "每个 Workflow 实际复用的 DRAM token 占全部 prompt token 的比例，包含冷访问与重访，排除恢复 token。三系统使用图 5 的同一对象顺序。"),
    "f0-revisit-hbm-wait": ("前台 HBM 准入等待", "各 Workflow 内请求的平均 HBM 分配等待，保持图 5 的对象顺序。GPU-ready 后的调度等待另行计量，正文表格给出三系统汇总。"),
    "evaluation-resource-cost": ("控制计算与传输成本", "每行分别相对 Mooncake 归一化，横轴为对数倍率。Python CPU 为参考实现实测，其余为模拟服务与传输指标；各行不能相加。GET 的对象总体随命中策略变化，较少读取不等于较高效率。"),
    "evaluation-native-interference": ("复制对真实 GPU forward 的干扰", "Qwen3-8B BF16/SDPA，双 L40S 的一次独占分配，额外分配 8 GiB。两组 batch 共用纵轴，Peer 方向相对于前台 GPU。点为五个配对测量块的倍率中位数，误差线为最小至最大值；无跨条件连线。"),
    "aimd-quota-and-occupancy": ("备份授权与物理占用的动态关系", "30% DMA forward 系数的机制模拟；每 50 ms 汇总八张 GPU 的硬上限、授权与实际副本占用。授权下降不等于地址已释放。该系数不是原生系统标定结果。"),
    "evaluation-configuration-effects": ("不同资源条件下的相对 WCT", "每行只改变默认配置的一个因素，分别相对该行 Mooncake 归一化；负值更快，正值更慢。CPU/DMA 系数为模型敏感性参数。八行代表八种配置，未用异质条件构造误差线。"),
}

PAPER_CAPTIONS_EN = {
    "motivation-branch-gap": "Maximum overlapping-branch duration gap per workflow in 124 CC/Weka workflows. The horizontal axis is logarithmic. Observed duration imbalance is not itself an estimate of usable slack.",
    "motivation-recovery-exposure": "Recovery cost versus workflow delay in five separate branch-fault counterfactuals of one trace fan-out at 349.5 s. Bars partition modeled recomputation into absorbed and exposed delay. Frozen AIConfigurator Qwen3-235B-A22B, A100-80GB, TP8/PP4/EP8; other branches are unchanged. This is neither a measured failure nor the later Qwen3-8B evaluation.",
    "motivation-kv-capacity": "Analytical Qwen3-8B BF16 KV footprint (Ki=1024). The reference subtracts model weights and 2 GiB runtime from 40 GiB, before dynamic foreground KV. It is not a lendable backup quota.",
    "system-overview": "AegisKV overview. The source independently copies sealed C0/C1 to Peer HBM and DRAM; each tier publishes after its own copy acknowledgement. Workflow value and per-tier admission choose shared physical objects. An independent controller constrains Peer borrowing. Either committed tier can restore C0/C1 into a new primary before recomputing C2. P0/P1 belong to unrelated foreground work. Solid arrows carry KV; dashed arrows carry control.",
    "f0-revisit-wct": "No-failure WCT for 160 matched workflows, each with two complete DAG visits, under the default simulation configuration. All workflow views retain the same IDs ordered by Mooncake F0 WCT. Segments connect adjacent objects, not timestamps; markers aid identification without discarding points.",
    "f1-q50-workflow-penalty": "Mid-execution fault increment: each system's F1 WCT minus its own matched F0 WCT, including positive, negative and zero values for all 160 workflows. The focal request is prespecified at 80/160 completed workflows in the Mooncake reference. Workflow ordering matches the no-failure view.",
    "f0-revisit-dram-hit": "DRAM prompt-token hit rate per matched workflow in the default simulation. The denominator includes all cold and revisit prompt tokens; recovery tokens are excluded. Workflow IDs and order match the no-failure WCT view.",
    "f0-revisit-hbm-wait": "Mean foreground HBM-admission wait across requests within each matched workflow. GPU-ready scheduling delay is measured separately. All workflow IDs retain the no-failure WCT order; no observations are thinned.",
    "evaluation-resource-cost": "Control and transfer costs, independently normalized to Mooncake within each row on a logarithmic axis. Reference Python CPU is measured; other rows use simulated service and traffic. Rows are not additive. Successful GET populations differ with cache admission, so fewer bytes or a lower slowdown percentile alone do not establish efficiency.",
    "evaluation-native-interference": "Measured Qwen3-8B BF16/SDPA forward interference with an extra 8 GiB allocation on one exclusive pair of L40S GPUs. Both batch groups share one axis. Peer direction is relative to the foreground GPU. Markers are medians of five within-block ratios; whiskers span observed minima and maxima, not confidence intervals. All 120 observations are retained.",
    "aimd-quota-and-occupancy": "Backup memory ceiling, granted quota and physical occupancy summed over eight GPUs at 50 ms windows, with the modeled DMA forward coefficient set to 30%. Revoked permission does not imply completed physical release. This coefficient is a sensitivity assumption, not native system calibration.",
    "evaluation-configuration-effects": "Mean WCT relative to matched Mooncake in eight distinct simulation configurations. Each nondefault row changes one factor; negative values are faster. CPU/DMA coefficients are model sensitivity assumptions. Heterogeneous configurations are not replicates and are neither connected nor used to construct uncertainty intervals.",
}
