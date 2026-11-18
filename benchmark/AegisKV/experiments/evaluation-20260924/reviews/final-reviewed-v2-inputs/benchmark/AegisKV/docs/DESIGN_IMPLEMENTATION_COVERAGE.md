# 当前设计的实现覆盖与证据边界

2026-09-24 实现核对；源码版本 `checkpoint-decay-hysteresis-incremental-g-20260924-eosfix1-causal-domain1-queued-history1`。
当前 [System Design](../paper/system_design.tex) 仅有编号 **Algorithm 1: Compute Agent
slack**。以下第 2、3 组指 KV Master、Adapter 的控制语义，不冒充当前论文中不存在的
Algorithm 2/3，也不恢复历史 rental/credit 算法。冻结实验版本另见
[分组与复现说明](current-design-simulation.md#实验分组与冻结版本)。

| 设计核心语义 | 当前执行位置 | 直接测试证据与覆盖范围 |
|---|---|---|
| 1. 固定 Agent-task DAG；每 Agent 只计一次剩余工作，未开始用完整 prior；已开始从预测提交时刻扣 elapsed，EF/LF 后减 guard | [tracker.py](../../../python/moonkvsim/aegiskv/current/tracker.py) `Tracker.slack/submit/publish`；[runtime.py](../../../python/moonkvsim/aegiskv/current/runtime.py) `_submit` | [test_current_design.py](../../../tests/aegiskv/test_current_design.py)：`test_cpm_counts_agent_once_and_preserves_full_unstarted_prior`、`test_prediction_timestamp_and_stale_async_publication`、`test_any_invalid_prediction_zeros_entire_workflow`、`test_predictor_sees_only_submission_context_and_predicts_once_per_call` |
| 2a. `E=max(T_full−s,0)>λ`；按 E 降序选择完整 Peer DRAM 检查点；共享主机预算、pending 字节与 TP barrier | `runtime._rebalance_inner/_checkpoint`；[model.py](../../../python/moonkvsim/aegiskv/current/model.py) `Config.checkpoint_bytes` | `test_current_design.py`：`test_high_threshold_disables_backups_without_breaking_recovery`、`test_tp_manifest_waits_for_slowest_shard`、`test_host_dram_is_shared_and_host_failure_fences_all_workers`；[test_current_algorithm_20260924.py](../../../tests/aegiskv/test_current_algorithm_20260924.py)：`test_checkpoint_bytes_include_live_and_pending_atomic_metadata_versions` |
| 2b. per-query 跨 head 去重；Z 边界 `c←β(c+new)`、冻结；提交时前 L 层 Top-K，严格 `(1+ε)` 迟滞与较早 block tie；Peer 本地复制 entrants | `runtime._demand/_forward_done/_checkpoint/_sync_hot`；[policy.py](../../../python/moonkvsim/aegiskv/current/policy.py) `top_blocks` | `test_query_head_dedup_and_decay_apply_once_per_checkpoint`、`test_external_selector_cannot_read_future_blocks`、`test_first_layers_rank_only_when_a_checkpoint_publishes`、`test_hysteresis_is_strict_and_retains_a_near_tie`；外部 native warm 诊断另有 13,824 次实际 `policy.top_blocks` 集合一致性核查，不是独立样本数 |
| 2c. `G=[T_D−s]+−[T_H−s]+`；按 G 降序接纳完整 Top-K+metadata 集合；低 G 优先释放，读租约保留安全性 | `policy.hbm_gain`；`runtime._hbm_gain/_rebalance_inner/_sync_hot` | `test_gain_is_difference_of_exposed_delays_and_skips_no_benefit`、`test_hbm_admits_larger_gain_instead_of_larger_dram_delay`、`test_zero_hbm_budget_retains_dram_checkpoints`；不是无条件抢占有读者的副本 |
| 2d. 先 metadata、再 reveal causal demand；逐层预取，actual miss 抢占并保留已传字节；hit 计算可与 miss 流重叠 | `runtime._restore/_load_next/_require/_pause_prefetch/_layer_step` | `test_metadata_arrives_before_a_layer_can_reveal_sparse_demand`、`test_priority_preemption_preserves_bytes_and_resumes_the_prefetch`、`test_hit_compute_overlaps_a_miss_instead_of_waiting_for_it`、`test_mixed_partial_prefetch_yields_its_undemanded_objects_without_recopy`；仅验证事件模型，不执行数值 LSE |
| 2e. 正常与恢复使用相同完整因果选择域；选择后区分 checkpoint 与本地 tail/self KV，仅前者可需远端召回，后者计入 hit compute | `runtime._demand/_layer_step/_forward_done` | [test_current_recovery_demand_domain.py](../../../tests/aegiskv/test_current_recovery_demand_domain.py)：dense 第一/后续 query 比例、sparse 身份反例、本地 self KV 无需召回、拒绝未来块、跨多块 forward 的正常/恢复 provider 参数一致 |
| 3. per-rank ceiling 与 AIMD；压力乘减、连续稳定且有未接纳需求才加增；前台按实际占用准入 | `policy.Adapter.update`；`runtime._control/_reserve_primary` | `test_adapter_does_not_grow_without_deferred_demand_and_obeys_ceiling`；[结构主矩阵审计](../experiments/evaluation-20260924/structural-campaign-v2-main/TRACE_MECHANISM_AUDIT.json) 保留实际 quota/压力与资源证据，不把 quota 上限当占用 |
| 跨调用 history、Router 故障域、EOS 与去重输出 | `runtime._submit/_choose_peer/_fail/_complete` | `test_compatible_history_survives_invocation_completion`、`test_incompatible_same_agent_prefix_is_not_reused`、`test_execution_migration_revalidates_old_peers_host_not_just_worker_id`；[test_current_eos_restore.py](../../../tests/aegiskv/test_current_eos_restore.py) 覆盖 EOS 提前于 cold restore、下次调用、依赖/排队请求、dense 不变及恢复流取消字节 |
| 故障时排队中的兼容 history 先取得有效 CP 读租约，再在存活 Peer 恢复；不使用未发布版本或已丢失的 GPU counters | `runtime._fail/_enqueue_retry/_admit`；`summary.history_restores` 与中断 active 调用的 `recoveries` 分开 | [test_current_queued_history.py](../../../tests/aegiskv/test_current_queued_history.py)：TP1/2、DRAM/HBM adopt、host 故障、EOS 后第三次调用、CP0 与 counter 丢弃、迁移新请求对空闲 worker 的独立唤醒 |
| 显式零 Slack 控制；保留异步预测但决策 Slack 置零 | `Config.slack_mode`；`runtime._slack` | [test_current_slack_ablation.py](../../../tests/aegiskv/test_current_slack_ablation.py)：隐藏分支更早保护而 F0 完成不变；[32-run 独立审计](../experiments/evaluation-20260924/capacity-slack-ablation-v2-corrected/INDEPENDENT_VARIANT_AUDIT.json) 验证仅该配置改变、资源行为改变但 WCT 无收益 |

代码/测试链接说明已存在的覆盖；重跑命令见实现说明。本轮恢复修复后的 current
回归为 74 项通过，记录见 [QUEUED_HISTORY_APPLICATION.json](../experiments/evaluation-20260924/reviews/QUEUED_HISTORY_APPLICATION.json)；
此前更广的 79 项文档/接口检查属于另一测试范围，不相加为独立测试数。
`output_tokens_exact` 是固定 token 回放的 emitted 数量/去重检查；
没有模型输出数值 identity validation、性能校准或生产故障一致性验证。

**尚未实现或明确简化的部分：**

- **前台执行与时长。** 每 DP 一个 active invocation，FCFS，无 continuous batching、
  实际 TP collective/attention kernel。AIConfigurator HYBRID grid 是离线算子估计，
  恢复 whole-forward 成本按层均分，再按需求 hit/miss 比例拆分；未做端到端硬件校准。
  `T_D/T_H` 预测不建模未来 contention/native miss；实际 DES 另外竞争共享链路。
- **预测与 guard。** 支持可训练、可序列化的上下文回归接口；正式分组使用训练角色/
  输出先验和模型成本，未验证真实 Agent 剩余时长精度或预测 CPU 开销。DAG 在输入时
  固定；后续 invocation 不泄漏给预测器，但不是动态生成 DAG/工具执行引擎。
- **Selector 与计数生命周期。** GPU scatter-add、压缩键语义、数值 softmax/LSE 和
  kernel 开销均未执行；metadata 字节数是配置。只在保护/恢复期间累计访问，不补算
  保护前和保护间隙。native warm 是持续计数、即时检查点的独立 CPU 诊断，不能直接
  推断实际驻留命中、物理 miss 流量或稀疏 WCT；原生采集本身保留历史来源。
- **深度与保护成本。** L/K 离线固定配置；profile campaign 的 L 由模型化带宽与
  checkpoint-aligned 训练上下文推导，不是实测有效带宽。DRAM 优先级使用完整 prefill
  surrogate；HBM 全集合 fit、pending allocation 和读者约束可能影响最终接纳。
- **异步与故障。** Z 是生成/发布粒度，异步 lag 可以大于 Z；failure 边界与 Z 可能
  改变 forward 分区。模拟单次永久 worker/host 失效、同步取消确认与 epoch fence；
  没有实机 DMA 取消/重试、控制面 HA、数值权重/KV 或多次故障验证。EOS 不完整历史
  整体失效，未优化保留可能仍可用的部分前缀。下一调用立即提交，未建模真正的
  调用间 idle gap；queued history 修复不等于验证所有常态迁移/淘汰时的备份复用。
- **对照和观测。** `all_dram` 只绕阈值且仍按 E/容量接纳；`static_hbm` 仍可为前台
  安全回收；zero-Slack 同时影响 E/G。summary-only 只保留聚合计数、峰值和部分事件，
  不能声称每 run 独立逐 flow 守恒重放；没有完整 Master budget-denial 计数。

EOS 与零 Slack 的应用记录分别是 [EOS_FIX_APPLICATION.json](../experiments/evaluation-20260924/reviews/EOS_FIX_APPLICATION.json)
和 [SLACK_ABLATION_APPLICATION.json](../experiments/evaluation-20260924/reviews/SLACK_ABLATION_APPLICATION.json)。
它们不追溯改变旧 `formal-core-v1` / `structural-campaign-v1` 的冻结来源。

完整因果域与 queued-history 的修复已完成各 v2 目录共 483 条同条件重跑和独立审计。
[旧版缺陷范围](../experiments/evaluation-20260924/reviews/DESIGN_CONFORMANCE_SPOTCHECK.md)
与 [重跑计划](../experiments/evaluation-20260924/reviews/RECOVERY_DOMAIN_RERUN_PLAN.md) 保留；
旧组的账本/哈希 PASS 不能解释为修复后语义已经验证。
