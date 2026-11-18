# 当前算法的实现与复现入口

本轮以用户指定线程 `01a06fb3-0069-74e1-af0f-ef9bcd39310a` 和 `01a079a1-f8f8-7813-b500-1d0b0e911710` 的最终算法为准。Algorithm 2 绑定 2026-09-08 11:00 UTC 的两张决策图，具体哈希见 [算法依据](../../../output/agent-lease-20260908/ALGORITHM_AUTHORITY.json)。

| 模块 | 当前职责 |
|---|---|
| [agent_lease.py](../../../python/moonkvsim/aegiskv/agent_lease.py) | 单物理 chunk、Agent 子租约、同轮不补信用、全部可释放 Q 尾块检查、租金分账、试算与提交 |
| [lease_value.py](../../../python/moonkvsim/aegiskv/lease_value.py) | 已生成 KV 恢复终点、并行 Agent 的固定因果链分支、固定 Agent 顺序的联合 DAG WCT 边际分账 |
| [guarded_aimd.py](../../../python/moonkvsim/aegiskv/guarded_aimd.py) | 独立显存硬上限、稳定窗口、预警退让、无效监测撤销与幂等窗口 |
| [lease_experiment.py](../../../python/moonkvsim/aegiskv/lease_experiment.py) | 连续批处理 DES 接入、物理账本、ACK 排空已生成前缀、Agent 生命周期、CPU 与显存/争用计量 |
| [run_agent_lease_mechanisms.py](scripts/run_agent_lease_mechanisms.py) | 三系统运行、固定 CPU 报价、同一两轮输入与配对故障选点、原始结果清单 |
| [run_agent_lease_campaign.py](scripts/run_agent_lease_campaign.py) | 冻结快照、依赖调度与同配置结果复用；发现失败后停止派发更多任务 |
| [profile_native_interference.py](scripts/profile_native_interference.py) | L40S 上真实 Qwen3-8B forward / DMA / 分配释放组件测量 |

`MechanismRuntime` 增加可替换 pool 类入口。当前 `LeaseRuntime` 实际使用 `AgentLeasePool` 与同粒度 `ChunkLRUPool`，不执行旧 PrefixAdmission 的准入选择；旧入口与结果保留用于历史复现。

清单的 `variant`、`parameters` 保留基类兼容字段，例如 `prefix_frontier_revision3`、旧 `aimd_enabled` 和 1 s 基类间隔。执行审查以 **`algorithm_contract`、`configuration` 和 source-v3 的实际运行类**为准：本轮 `configuration.window_ns=50,000,000`，`foreground_budget` 保存真实控制窗口。`strict_free_gain`、`slack_enabled`、`static_peer` 则标记显式消融，优先于共同设计契约的文字名称。

## 冻结矩阵

[实验协议](AGENT_LEASE_PROTOCOL.md)规定主矩阵 47 次完整执行，另有 [30% DMA 扩展](../../../output/agent-lease-20260908/CONTENTION_EXTENSION.md) 4 次。source-v3 包含 175 个逐文件哈希。分目录并行任务合入主矩阵前核对源码、配置、CPU 报价与 raw 哈希，同一次执行不计成额外重复。磁盘配额导致的写入失败单独归档后原配置补跑，不采用不完整结果。

```bash
.venv/bin/python benchmark/AegisKV/experiments/scripts/run_agent_lease_campaign.py \
  --source output/agent-lease-20260908/source-v3 \
  --output output/agent-lease-20260908/campaign-v3 \
  --cpu-calibration output/agent-lease-20260908/CPU_QUOTES.json \
  --case-plan output/agent-lease-20260908/CASES.json --workers 4
```

修改算法或输入后必须另建快照和输出目录，不能覆盖这批结果。绘图与核对入口为：

```bash
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_agent_lease_story.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_agent_lease_native.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/build_agent_lease_diagrams.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/build_agent_lease_index.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/audit_agent_lease_story.py
```

## 原始证据的持久化

账号的 900 GiB 配额导致部分写入失败后，本任务将大文件暂存到本机缓存；最终原始 gzip 与绘图输入均逐字节归入仓库内的 [evidence.tar.zst](../../../output/agent-lease-20260908/evidence.tar.zst)，[归档清单](../../../output/agent-lease-20260908/EVIDENCE_ARCHIVE.json)保存每个成员原始 SHA-256。实验清单、冻结源码、CPU 报价和最终图像直接保存在仓库中。归档压缩不改变原始 gzip 的字节或故障参考哈希。

如果机器重启或临时缓存被清理，先校验并恢复缓存，再执行绘图或数据审查：

```bash
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/archive_agent_lease_evidence.py --restore
```

恢复器校验归档与全部成员，重建数据路径；临时目录不是原始证据的唯一副本。完整恢复不会重新执行任何实验。

## 验证范围

52 项针对性回归通过。每次完整运行另核对 output exactly-once、HBM 守恒、传输字节/链路容量和 Workflow 覆盖，完整结果见 [DELIVERY_AUDIT.json](../../../output/agent-lease-20260908/DELIVERY_AUDIT.json)。

GPU DES 时序未标定为 A100 kernel，时长估计不是训练后的 GBDT。CPU 图区分固定服务报价与实测 Python 组件 CPU，后者尚未全部成为因果延迟。L40S 数据只验证组件 forward/DMA/释放，不等价于原生三系统端到端 WCT、故障性能或通用 QoS 保证。正、零、负结果均保留。
