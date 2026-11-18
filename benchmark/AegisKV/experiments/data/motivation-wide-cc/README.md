# 十并行分支的 Motivation 实例（已被替换）

2026-09-18 用户将目标改为 4–5 个分支、gap 约 100 s；当前正文改用相邻 `motivation-compact-cc/`。本目录保留旧例证据。

固定 trace SHA-256 与逐行 SHA 保存在 `SELECTION.json`。从 Figure 1(a) 的 workflow-max 样本中选择分支数至少 5、最长分支不超过 250 s、时长差与总体中位数相差不超过 35 s 的组，优先分支更多者。

当前选择 `c97f752dfb70c09da9a0be90ccc35610f9e5` 的第 3 组，10 个分支，持续时间 24.960–193.273 s，时长差 168.313 s，接近总体中位数 137.758 s，但不等于中位数。所有分支均完成，随后有 Main 请求；fan-in 仍是时序推断。

故障时刻在所有分支都有活跃 LLM 请求且所有前缀 <=128K 的区间内，优先最后完成的分支输入最长的区间，故意突出较大损失；不是随机故障抽样。所选绝对时刻 1438.3 s、相对 fork 36.092 s，在 [1438.269,1438.363] s 区间内。A10 决定 221.843 s 的汇合，Main 在 226.554 s 继续。

CSV 和 trace 摘录共同驱动 (b)/(c)，原始 hash IDs 与分支标识均保留。成本由相邻 `reuse-aiconfigurator-a100/estimate_reuse.py` 查询固定 Qwen3-14B 配置，附加假设的 64-token 尾部，非原模型故障实测。十行代表十个独立单分支故障，不能相加成一次故障的总损失。旧 median/short/real 数据目录保留。

```sh
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/select_motivation_wide_example.py --trace /home/comp/zhanzhao/sglsim/AegisKV/doc/Archived/2026-08-06-pre-kvcache-centric/presentations/presentation/experiments/sglsim_large/traces/cc-traces-weka-062126/traces.materialized.jsonl
```
