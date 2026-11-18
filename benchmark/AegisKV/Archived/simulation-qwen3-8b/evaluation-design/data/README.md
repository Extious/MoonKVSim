# 新协议原始表模板

这些 CSV 只有表头，没有观测值。缺失不是零；绘图前必须完成采集并冻结配置。

- blocks.csv：block_id, system, condition, case_id, evidence_type 等字段。
- workflows.csv：block_id, system, condition, case_id, workflow_id 等字段。
- interventions.csv：case_id, workflow_id, span_id, source_gpu_id, recovery_gpu_id 等字段。
- failure_events.csv：block_id, system, case_id, failure_id, timestamp_ns 等字段。
- recovery_intervals.csv：block_id, system, case_id, workflow_id, span_id 等字段。
- recovery_tokens.csv：block_id, system, case_id, span_id, failure_id 等字段。
- resource_samples.csv：block_id, system, condition, case_id, timestamp_ns 等字段。
- resource_totals.csv：block_id, system, condition, case_id, component 等字段。
- request_metrics.csv：block_id, system, condition, case_id, workflow_id 等字段。
- output_tokens.csv：block_id, system, condition, case_id, span_id 等字段。
- link_intervals.csv：block_id, system, condition, case_id, transfer_id 等字段。
- sweep_points.csv：block_id, system, family, x, condition 等字段。

时间统一为纳秒；CPU 时间、token 计数、字节及硬件测量类型必须分别声明。各表以 block/system/condition/case 和对象 ID 关联，不以行序拼接。恢复 interval 允许重叠，critical_path 必须由依赖重建，不能按阶段名猜测。

output_tokens.csv 用于真实逐 token TBT；request 平均 TPOT 不能替代逐 token P99。未完成 Workflow 保留 status 和 censor_ns；配对不完整的测量块整块标记，不能静默删除慢系统。

protocol.json 仍为 DRAFT；interventions.csv 尚未填写实际 case，不能用历史 q25/50/75 表冒充。
