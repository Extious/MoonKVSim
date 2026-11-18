"""Reader-facing captions; detailed provenance stays in the source manifests."""

CAPTIONS = {
    'motivation-recompute': (
        'Qwen3-8B/32B 在 A100-80GB、TP4/PP2、BF16 配置下的完整前缀重算预测；每点按 8 Ki-token 分块累计单请求 prefill 时间，Ki=1,024。共八个历史 AIConfigurator SILICON 预测点，不含故障检测、传输与排队，不是物理故障实验。',
        'Predicted full-prefix recomputation for Qwen3-8B/32B on A100-80GB with TP4/PP2 and BF16. Each point sums single-request prefill predictions in 8-Ki-token chunks (Ki=1,024). These eight historical AIConfigurator SILICON predictions exclude detection, transfer and queueing; they are not physical failure measurements.'),
    'eval-workflow-delay': (
        '同一 F0 配置下，全部 160 个 Workflow 相对同 ID Mooncake 的 WCT 差值。三系统共享 Mooncake F0 排序；负值更快，完整尾部保留。标注最大离群对象；各系统一次冻结算法模拟。',
        'WCT difference from the same-ID Mooncake baseline for all 160 workflows in the same no-failure configuration. Systems share the Mooncake F0 ordering; negative is faster. All tails are retained and the largest outlier is annotated. One frozen-algorithm simulation per system.'),
    'eval-initial-reuse': (
        '同一组 Workflow 的第二轮初次 DRAM 查询命中 token 占该轮 prompt token 的比例，排除冷访问；三系统各一次模拟。总体 token 加权命中率为 94.257%、81.568%、82.245%。初次命中不等于抢占后最终避免的计算量。',
        'Initial DRAM-hit tokens divided by second-visit prompt tokens for the same workflows; cold visits are excluded. One simulation per system. Global token-weighted rates are 94.257%, 81.568% and 82.245%. An initial hit does not imply that its computation remains avoided after preemption.'),
    'eval-preemption-progress': (
        '最大离群 Workflow 中同一重访请求的有效 prefill 进度；三系统分别对齐该 Workflow 的首个释放时刻。AegisKV 抢占后进度归零，等待 104.929 s 再入场。三个轨迹来自各系统一次模拟；抢占附近 Peer 占用为零。',
        'Valid prefill progress for the same revisit request in the largest-outlier workflow, aligned to each system\'s workflow release. AegisKV resets progress at preemption and waits 104.929 s before readmission. One trace per system; Peer occupancy is zero around this preemption.'),
    'eval-fixed-event-wct': (
        '追加 180 s/GPU2 故障的同 ID 效应：K1/K2 共享 60 s/GPU0 故障，每次停机 120 s，纵轴为同系统 WCT(K2)−WCT(K1)。七个 ID 为三系统直接受害者的事后并集；实心、空心、叉号分别为含活跃受害请求、仅排队受害、无直接受害。21 对释放时刻相等，负值和零值保留。每系统每日程一次模拟。',
        'Same-ID effect of adding a GPU2 fault at 180 s. K1/K2 share a GPU0 fault at 60 s; each outage lasts 120 s. The ordinate is same-system WCT(K2) minus WCT(K1). The seven IDs form the post-treatment union of direct victims across systems. Filled, hollow and cross markers indicate active, queued-only and no direct victims. Release times match in all 21 pairs; negative and zero changes are retained. One simulation per system per schedule.'),
    'eval-fault-paired-wct': (
        'C1/C2/C3 分别为 Workflow 98ced84a/220852c6/5aa09932，源 GPU 为 6/2/0。箭头从同系统、同 ID 的 F0 指向 F1；各例各系统一次 F1，复用相应 F0。故障固定焦点请求与 token 进度，其他受害者集合不同；该图为机制诊断。',
        'C1/C2/C3 correspond to workflows 98ced84a/220852c6/5aa09932 on source GPUs 6/2/0. Each arrow connects the same system and ID from fault-free F0 to single-fault F1. One F1 execution per system per case reuses the corresponding F0. Injection fixes the focal request and token progress, but other victim sets differ; these are diagnostic cases.'),
    'eval-fault-token-source': (
        '与前图相同焦点请求的 Peer、DRAM 恢复量与重算量，Ki=1,024；每行来自一次 F1 执行。Peer 恢复量全为零，仍保留其图例。本地 primary 复用未计入这些分段；这些 token 数不分解完整 DAG 时间。',
        'Peer/DRAM-restored and recomputed tokens for the focal requests in the preceding figure (Ki=1,024), one F1 execution per row. Peer restoration is zero throughout and remains in the legend. Local-primary reuse is outside these segments; token counts do not decompose DAG completion time.'),
    'eval-concurrency-workflow': (
        'C64 下全部 160 个 Workflow 相对同 ID、同 C64 Mooncake 的 WCT 差值。横轴只沿用 C16 Mooncake 的排序，数值比较均在 C64；每系统一次模拟。AegisKV 有 65 个更快、95 个更慢，保留所有正负变化。',
        'At C64, WCT differences from same-ID, same-C64 Mooncake for all 160 workflows. The abscissa uses C16 Mooncake only to determine order; all numerical contrasts use C64. One simulation per system. AegisKV is faster on 65 workflows and slower on 95; all signed changes are retained.'),
}
