# AegisKV 当前设计：首轮机制模拟

设计版本：`agent-full-dram-topk-hbm-20260923`。78 个运行全部结束，配对验收通过。

[结果解读与负面结果](FINDINGS.md) · [独立资源审计](AUDIT.json) · [85 项测试记录](VALIDATION.json)

这是 CPU 上执行的未校准离散事件模拟。工作负载为明确构造的固定 Agent DAG，
每个工作负载只执行一次；稀疏场景使用构造 selector，不是原生模型测量。
默认预测器使用提交时可见的时长先验；可训练上下文回归器接口已提供，
本次未把真实任务上的训练精度作为已验证事实。

各策略具有同配置的 F0（无故障）与 F1（故障）运行。故障固定到 wf00/slow
第二次调用、总 token 逻辑进度 80%；注入时刻随各自运行变化。
下表均值以工作流为单位；完整同 ID 配对、p95/p99 和逐次恢复分解保留在数据中。

| 场景 | 策略 | F0 平均 WCT (s) | F1 平均 WCT (s) | 平均增量 (s) |
|---|---|---:|---:|---:|
| dense | none | 10.1700 | 10.9539 | +0.7840 |
| dense | dram | 10.1700 | 10.8157 | +0.6457 |
| dense | aegiskv | 10.1700 | 10.8143 | +0.6443 |
| sparse_fixture | none | 10.1700 | 10.9539 | +0.7840 |
| sparse_fixture | dram | 10.1700 | 10.7829 | +0.6129 |
| sparse_fixture | aegiskv | 10.1700 | 10.7845 | +0.6146 |
| slow_copy | none | 10.2757 | 11.0350 | +0.7593 |
| slow_copy | dram | 10.2757 | 11.0038 | +0.7281 |
| slow_copy | aegiskv | 10.2757 | 11.0024 | +0.7267 |
| dram_pressure | none | 10.2757 | 11.0350 | +0.7593 |
| dram_pressure | dram | 10.2757 | 11.0350 | +0.7593 |
| dram_pressure | aegiskv | 10.2757 | 11.0350 | +0.7593 |
| hbm_growth | none | 10.2757 | 11.0350 | +0.7593 |
| hbm_growth | dram | 10.2757 | 10.8940 | +0.6183 |
| hbm_growth | aegiskv | 10.2757 | 10.8926 | +0.6169 |
| foreground_pressure | none | 10.7579 | 11.2228 | +0.4649 |
| foreground_pressure | dram | 10.7579 | 11.0817 | +0.3239 |
| foreground_pressure | aegiskv | 10.7579 | 11.0804 | +0.3225 |
| shared_host_failure | none | 10.2757 | 13.4647 | +3.1890 |
| shared_host_failure | dram | 10.2757 | 13.0419 | +2.7662 |
| shared_host_failure | aegiskv | 10.2757 | 13.0377 | +2.7620 |
| expired_prediction | none | 10.2757 | 11.0350 | +0.7593 |
| expired_prediction | dram | 10.2757 | 10.8940 | +0.6183 |
| expired_prediction | aegiskv | 10.2757 | 10.8926 | +0.6169 |
| lambda_1s | none | 10.2757 | 11.0350 | +0.7593 |
| lambda_1s | dram | 10.2757 | 11.0350 | +0.7593 |
| lambda_1s | aegiskv | 10.2757 | 11.0350 | +0.7593 |

容量账本包含执行预留、已提交副本及复制中的目标分配。Peer DRAM 按物理主机共享，
Peer HBM 按 TP rank 计费；恢复时原地接管 HBM，避免重复计费。所有运行结束时
占用归零，输出 token 无重复或遗漏。低带宽下的检查点滞后及任何负面 WCT 结果均保留。

局限：前台是每 DP 一个 FCFS 执行队列，没有连续批处理；GPU 计算与 DMA 的内存带宽
干扰尚未校准，F0 相同不能解释为物理备份零开销。故障为单次永久 worker/host 故障；
复制取消在模拟时钟内同步完成；没有模拟真实驱动取消延迟或多次连续故障。
有限合成样本的分位数只是描述性统计，没有给出硬件速度或论文级置信结论。

复现：在 MoonKVSim 仓库根目录执行

```bash
.venv/bin/python -m moonkvsim.aegiskv.current campaign --out /tmp/aegiskv-current-reproduce
```

`MANIFEST.json` 固定代码/设计 SHA-256；`source_snapshot/` 保留当次源文件。
`runs/*/summary.json` 含请求、工作流、重建量、恢复队列/传输时刻、字节与容量数据；
`events.jsonl.gz` 和 `flows.jsonl.gz` 保留原始事件/流速区间。

设计源 SHA-256：`60fde91a9fc75d3a0a3cb360c00a989dee28aac7d405b3a6281c71c6c6607fee`。
