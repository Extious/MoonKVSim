# 当前 runtime 的 checkpoint 尾部证据定点检查

**结论：这次限定扫描不能提供可替换 historical 反例的当前版本 `tail > Z`
证据。** 5 个故障目标的严格对齐尾部为 100、100、100、128、77 token；另 6 个
queued-history 故障快照的最大尾部也是 128。所有病例 `Z=256`。
日志缺少正常 forward 完成时的 token frontier，**全运行最大尾部不可重建**；
不能把这次未找到反例写成全时段 `tail ≤ Z` 的证明。

本报告只读已完成并封存的 v2 输入，不读取正在写入的 v3 日志，不运行 DES，
不修改 runtime、论文或旧包。41 个输入文件在检查前后 SHA-256 不变。

## 固定扫描范围

先检查第一条 primary detailed 日志的字段，再向父任务声明固定以下 6 条现有
预声明 detailed cases；之后没有因未找到反例而扩展范围。这是事后只读诊断，
不是新实验协议或新样本。

| Campaign | Detailed case |
|---|---|
| formal-core-v2-corrected | Qwen3-8B-load0.65-aegiskv-F1-2 |
| formal-core-v2-corrected | Qwen3-32B-load0.65-aegiskv-F1-2 |
| sensitivity-campaign-v2-corrected | center-aegiskv-F0 |
| sensitivity-campaign-v2-corrected | center-aegiskv-F1 |
| structural-campaign-v2-main | forkjoin_skew-n8-s7-aegiskv-left.decode |
| structural-campaign-v2-main | long_decode_drift-n8-s7-aegiskv-left.decode |

三个冻结 runtime 的 SHA-256 相同，且与此次检查时 live runtime 相同：
`de3a9ce7791218a74e8d50651c2ba1249b194e500eabc0fd9a91c52b978b8c5f`。
版本为 `checkpoint-decay-hysteresis-incremental-g-20260924-eosfix1-causal-domain1-queued-history1`。
原 MANIFEST/source snapshot 与 COMPLETE/summary 绑定均核对通过。

## 可精确对齐的故障快照

这里的 accepted frontier 是模拟器已经完成 forward 后保存的 `state.durable`，
即截至该时刻完成处理的最高 token frontier；它不是原始 prompt 长度、总输出长度，
也不是 prediction 事件中 `accepted` 的含义。该模型在
`runtime.py:1264–1267` 的 `_forward_done` 更新 computed/durable。
首个故障的目标 `failure.logical_tokens=target.computed`（`:1332–1342`），
且在这 5 条记录中与同故障恢复快照的 `durable_tokens` 严格相等。

`_fail` 保留仍可用的 peer checkpoint 后，将实际 `cp.frontier` 与 `state.durable`
一起写入恢复记录（`:1357–1365`、`:1392–1403`）。检查以这个同一故障时刻的
frontier 做差，并在 **failure 事件之前的文件顺序** 内匹配同 Agent 最近一条
`checkpoint_commit`，核对 frontier、全部 TP ACK 和存活 peer。没有使用首次 CP
尚不存在或完全未保护 Agent 的全部 tokens 作为尾部反例。

| Case | 故障时刻 ns | Accepted | COMMITTED | Tail | Commit 行 / Failure 行 |
|---|---:|---:|---:|---:|---:|
| Primary 8B | 77,666,396,643 | 356 | 256 | 100 | 32734 / 32755 |
| Primary 32B | 92,955,753,331 | 356 | 256 | 100 | 33077 / 33099 |
| Sensitivity F1 | 6,540,857,293 | 16,228 | 16,128 | 100 | 1355 / 1356 |
| Structural forkjoin | 113,699,561,104 | 10,112 | 9,984 | 128 | 18193 / 18450 |
| Structural long-decode | 391,613,512,788 | 17,485 | 17,408 | 77 | 63312 / 63491 |

行号指各 run 的 `events.jsonl.gz` 解压后从 1 开始的行号。`RESULT.json` 保存完整
Agent、invocation、checkpoint identity、commit 时刻、peer 和最后 protected
control sample。该 control sample 可能早于最近一次 CP 发布，**不是故障时刻
快照**；故障时 checkpoint 可用性的证据来自 `_fail` 的实际恢复记录。

这五次均为各运行唯一、首次故障。源码中先前未发生恢复或恢复 EOS 清理，故其
pre-failure recovery epoch 为 0；这是由代码路径推导的 epoch，日志没有直接
输出该字段。结构化病例的 invocation=1，由最后的 submit 记录对齐；CP 可以
合法跨 invocation 保留，不把 invocation 换号当作 recovery epoch 换号。

`publication_pending` 没有直接记录。本次各快照满足 `durable−frontier < Z`，
而 `_checkpoint` 只在 `computed ≥ frontier+Z` 时启动下一次 append
（`:443–449`），并且 `computed ≤ durable`。因此可从源码推导这些同一 CP 在
故障前没有下一次 append pending；JSON 将 **recorded=null** 与
**inferred=false** 分开，不能把它写成独立观测到的 pending 字段。

## 为什么不能得到全运行最大尾部

- 所有 6 条完整 event 流均没有正常 completed-forward / token-accepted 事件。
  `policy_sample` 记录 COMMITTED frontier 与成本估计，不记录当时 completed-token
  frontier；从原 prompt 长度补这个缺失字段不成立。
- `checkpoint_commit` 有 Agent、frontier、CP identity 和 TP ACK，缺少 invocation、
  recovery epoch 与 pending 字段。首次故障前可以做上述局部对齐，不能据此建立
  任意时刻、任意恢复阶段的完整 frontier 时间线。
- Flow interval 的序列化字段没有 Agent/epoch/CP owner identity 映射；不能猜测
  `copy:N` 与 `checkpoint.identity` 的对应关系来恢复 publication pending。
- `recovery_layer.query_start/query_end` 是恢复阶段正在重算的 query 域，不能当作
  新接受 token 的进度。健康 F0 也不能从最终完成信息恢复中途最大差值。

若以后需要同版本全时段证据，最小可观测性补充是在 forward 完成、CP 发布/
退休与故障入口记录 Agent、invocation、recovery epoch、computed/durable、
CP identity/frontier/pending 及 peer 可用性。**此次没有实施该改动或补跑实验。**

## 产物与复现

- `check.py`：固定 6-case 的 stdlib 只读脚本；不导入模拟器。
- `RESULT.json`：范围、字段清单、11 个故障快照、源码和输入哈希、限制。
- `failure-snapshots.csv`：5 个 active target 与 6 个 queued-history 单独标记。
- `SEAL.json`：本报告及脚本/结果的交付哈希；不修改原 campaign 的 seal。

从仓库根目录运行：

```bash
.venv/bin/python benchmark/AegisKV/experiments/evaluation-20260924/reviews/current-tail-publication-check-v1/check.py
```
