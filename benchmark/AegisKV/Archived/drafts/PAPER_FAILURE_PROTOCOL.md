# 论文图故障补跑协议（2026-09-08）

[论文叙述](Paper_Draft.md) · [共同模型配置](THREE_SYSTEM_PROTOCOL.md)

补跑的目的，是纠正原 F1/F2 在已有 151/160、156/160 个 Workflow 完成时才触发故障的覆盖偏晚问题。实验在结果产生前固定选择规则，不按 AegisKV 的收益选择焦点。

## 冻结设计

- 原始 FanOutQA 派生的 160 个 Workflow、1,304 个请求，保留精确 token 和 DAG；不加两轮重访。
- Mooncake、DRAM-only AegisKV、AegisKV 三系统；每系统一个 F0（无故障）和三个单 GPU 逻辑故障位置，共 **12 次完整执行**。三个位置是不同干预条件，每条件每系统一次，没有独立重复置信区间。
- 与原矩阵相同的 Qwen3-8B、DP8、8×40 GiB、C=16、1 TB DRAM、25 GB/s、4,096-token chunk、固定 CPU 报价及容量受限 Peer 探索模式。
- 使用 [source-v7](../../../output/paper-story-20260908/source-v7/MECHANISM_SOURCE_SNAPSHOT.json)。166 个冻结文件相对 source-v6 仅 `run_three_system_mechanisms.py` 改变；所有核心模拟、资源、算法与输入文件哈希相同。
- 每个系统的无故障执行重新运行，不能将旧 source-v6 的 manifest 改标签后当作 source-v7 执行。

## 预先固定的故障选点

1. 从新的 Mooncake F0 找出 prompt ≥16,384 tokens 的请求；这些请求在 60% fresh-prefill 进度处至少已经越过两个完整 4K chunk。
2. 在未见任何故障运行结果前，对每个合格请求求第一次穿越 prompt 60% 的参考时刻，统计该时刻已经完成的 Workflow 数。
3. 分别选择最接近 25%、50%、75% 已完成 Workflow 比例的候选。距离按整数计数计算；并列时依次取较早参考时刻、较小 span ID。
4. 对三个系统使用相同焦点 span ID 和相同 prefill 60% 进度。运行时故障 GPU 为焦点的实际宿主，绝对时刻可不同。同 GPU 的其他活跃/排队请求按各自实际状态受到影响，不保证三个系统的附带受影响集合完全相同。
5. detection delay=0；模拟 repair-after=120 s。每个条件仅一次 GPU 故障，不把三次故障连续注入同一运行。

请求 ≥16 Ki 的资格、目标进度及 tie-break 规则均在 [case plan](../../../output/paper-story-20260908/failure-cases.json) 和 [冻结协议](../../../output/paper-story-20260908/failure-campaign/PROTOCOL.json) 中可追踪。`failure-plan.json` 中的 `reference_completed_workflow_count` 是实际参考完成数；历史字段 `target_progress_per_mille` 存储该计数向下取整的比例，名义 250/500/750 另由 case plan 和 `selection_scope` 明确记录。绘图使用完成数除以 160，不把向下取整的字段误作精确横坐标。

## 分析口径

- 逐 Workflow 故障代价：`WCT(system, F1, workflow) − WCT(system, F0, workflow)`，保留全部 160 个有符号值。前后均排除活跃 slot 外的入场等待。故障可能改变后续调度顺序，非焦点 Workflow 也可能更快或更慢。
- 尾部：先逐 Workflow 配对相减，再对 160 个差值求 NumPy 线性插值 P95；不是 `P95(F1) − P95(F0)`。
- 图的三个进度坐标使用 Mooncake F0 实际参考完成比例。所有逐 Workflow 图沿用论文版同一个 ID 映射，未分别按每系统或每故障的结果重排序。
- 焦点阶段：故障 → `CONTINUOUS_RECOVERY_PREFIX_MATERIALIZED`；该事件 → `resume_decode_start_ns`。前段包含目的地预留、setup、复制及等待；后段包含未保护后缀计算、相应调度与恢复。必须验证两段非负、和等于完整焦点恢复延迟。
- 对 queued-only 的附带受影响请求，不伪造前缀恢复阶段；阶段图仅显示每个位置预先选定的焦点请求。

## 复现与结果位置

```bash
.venv/bin/python benchmark/AegisKV/experiments/scripts/run_three_system_campaign.py \
  --source output/paper-story-20260908/source-v7 \
  --output output/paper-story-20260908/failure-campaign \
  --cpu-calibration output/three-system-20260908/CPU_QUOTES.json \
  --case-plan output/paper-story-20260908/failure-cases.json --workers 6
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/process_three_system_campaign.py \
  --campaign output/paper-story-20260908/failure-campaign \
  --data output/paper-story-20260908/failure-data --reduce-only --workers 4
```

[运行状态](../../../output/paper-story-20260908/failure-campaign/STATUS.json) · [原始结果](../../../output/paper-story-20260908/failure-campaign/runs) · [核对后的数据](../../../output/paper-story-20260908/failure-data)。最初终端前台会话被时限终止，其日志保留于 `failure-campaign/interrupted-launch`；完成的三个 F0 通过原 manifest 复用，未完成的故障条件在同一冻结协议下重新执行。

这仍是未经目标 GPU 标定的机制模拟。新位置补足的是本输入的受控故障覆盖，不能替代原生服务、多 workload、多故障域、预测器或完整 QoS 控制器实验。
